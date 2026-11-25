import copy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import torch
import wave

from backend.schemas import CreateJobRequest, ComparisonQuestRequest
from backend.services.creator_inpainter import CreatorInpainter
from backend.services.explainer import ExplainerService, NarrationRewrite
from backend.services.audio_processor import AudioProcessor


class TestEnglishInpainting(unittest.TestCase):
    def test_failed_source_speech_separation_never_reuses_old_dialogue(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.wav';clean=root/'clean.wav'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=400:duration=0.3',str(source)],check=True)
            real_run=subprocess.run
            def run(command, **kwargs):
                if '-m' in command and 'demucs' in command:
                    raise subprocess.CalledProcessError(1,command)
                return real_run(command,**kwargs)
            processor=AudioProcessor();processor.temp_dir=root
            with patch('backend.services.audio_processor.subprocess.run',side_effect=run):
                processor.strip_copyright_radio(source,clean)
            with wave.open(str(clean),'rb') as audio:
                data=np.frombuffer(audio.readframes(audio.getnframes()),np.int16)
                self.assertGreater(len(data),100)
                self.assertEqual(int(np.abs(data).max()),0)

    def test_requests_are_english_only_including_legacy_language_values(self):
        for language in ('english', 'hindi', 'hinglish'):
            self.assertEqual(CreateJobRequest(url_or_path='test.mp4', target_language=language).target_language.value, 'english')
            self.assertEqual(ComparisonQuestRequest(gta6_url_or_path='test.mp4', target_language=language).target_language.value, 'english')

    def test_legacy_narration_migrates_without_moving_verified_scenes_or_reusing_hindi_audio(self):
        clip = {'video_format': 'explainer', 'commentary_script': 'Lester ko chot lagi. Paradox gayab hai.',
                'voice_path': 'old_hindi.wav', 'verification_passed': True,
                'beats': [{'start_time': 7.5, 'duration': 7.8, 'narration': 'Lester ko chot lagi.'},
                          {'start_time': 47.5, 'duration': 5, 'narration': 'Paradox gayab hai.'}]}
        service = ExplainerService(MagicMock())
        with patch.object(service, '_request', side_effect=[NarrationRewrite(narration='Lester is injured.'), NarrationRewrite(narration='Paradox is missing.')]) as request:
            self.assertTrue(service.ensure_english_narration(clip))
            self.assertEqual(request.call_count, 2)
            self.assertEqual(clip['commentary_script'], 'Lester is injured. Paradox is missing.')
            self.assertNotIn('voice_path', clip)
            self.assertEqual([(b['start_time'], b['duration']) for b in clip['beats']], [(7.5,7.8),(47.5,5)])
            self.assertFalse(service.ensure_english_narration(clip))

    def test_failed_translation_preserves_previous_verified_script(self):
        clip = {'commentary_script': 'Test', 'voice_path': 'old.wav'}
        before = copy.deepcopy(clip)
        service = ExplainerService(MagicMock())
        with patch.object(service, '_request', return_value=NarrationRewrite(narration='हिन्दी')):
            with self.assertRaises(ValueError):
                service.ensure_english_narration(clip)
        self.assertEqual(clip, before)

    def test_neural_input_cannot_contain_the_hidden_face_or_lettering(self):
        painter = CreatorInpainter()
        painter.device = torch.device('cpu')
        frame = np.full((16,16,3), 90, np.uint8)
        frame[:8,:8] = (0,0,255)
        mask = np.zeros((16,16), np.uint8); mask[:8,:8] = 255
        def model(images, masks):
            self.assertEqual(float(images[0, :, :8, :8].max()), 0)
            self.assertEqual(float(masks[0,0,:8,:8].min()), 1)
            return torch.full_like(images, .5)
        painter.model = model
        result = painter._predict_rgb([frame], mask)
        self.assertEqual(result[0].shape, frame.shape)
        self.assertGreater(int(result[0].min()), 100)

    def test_video_reconstruction_preserves_unmasked_gameplay_and_all_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/'source.mp4'; output = root/'reconstructed.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=green:s=320x180:r=60:d=0.3',
                            '-vf','drawbox=x=240:y=0:w=80:h=60:color=red:t=fill','-c:v','libx264',str(source)],check=True)
            painter = CreatorInpainter()
            def generated_background(frames, mask):
                return [np.full_like(frame, (30,140,40)) for frame in frames]
            with patch.object(painter, '_predict_rgb', side_effect=generated_background):
                painter.reconstruct_segment(source,0,.3,[(235,0,85,65)],output)
            cap = cv2.VideoCapture(str(output)); count=0
            while True:
                ok, frame=cap.read()
                if not ok: break
                self.assertGreater(float(frame[10:40,260:300,1].min()),100)
                self.assertLess(float(frame[100:150,50:100,0].max()),20)
                self.assertGreater(float(frame[100:150,50:100,1].min()),100)
                count+=1
            cap.release()
            self.assertEqual(count,18)

    def test_inpainting_failure_stops_video_without_exporting_black_or_original_face(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'source.mp4'; output=root/'output.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=green:s=160x96:r=10:d=0.2',str(source)],check=True)
            painter=CreatorInpainter()
            with patch.object(painter,'_predict_rgb',side_effect=RuntimeError('neural model failed')):
                with self.assertRaisesRegex(RuntimeError,'neural model failed'):
                    painter.reconstruct_segment(source,0,.2,[(100,0,60,30)],output)
            self.assertFalse(output.exists())
