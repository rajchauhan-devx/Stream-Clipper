import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
from google.genai import types
from pydantic import ValidationError

import backend.main as studio
from backend.schemas import CropMode, CreatorOverlayRegion
from backend.services.creator_masker import audit_creator_overlays
from backend.services.video_cropper import VideoCropper
from backend.services.creator_inpainter import creator_inpainter
import numpy as np


class TestCreatorMasker(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.mp4'
        self.source.touch()
        self.regions = [
            CreatorOverlayRegion(kind='facecam', x=.75, y=0, width=.25, height=.32),
            CreatorOverlayRegion(kind='channel_logo', x=0, y=0, width=.06, height=.10),
        ]
        self.cropper = VideoCropper()
        self.cropper.temp_dir = self.root

    def test_null_label_no_longer_disables_legacy_camera_mask(self):
        self.assertEqual(studio._resolve_watermark_settings(
            {'watermark_info': {'detected': True, 'label': None, 'corner': 'top_right'}}, True
        ), ('top_right', True, 'top_right'))

    def test_geometry_rejects_empty_or_out_of_frame_masks(self):
        for rect in ({'x': .9, 'y': 0, 'width': .2, 'height': .1},
                     {'x': 0, 'y': 0, 'width': 0, 'height': .1}):
            with self.assertRaises(ValidationError):
                CreatorOverlayRegion(kind='facecam', **rect)

    def _audit(self, payload, localized=None, *, missing_primary=False):
        director = MagicMock()
        director.temp_dir = self.root
        director._unique_models.return_value = ["primary", "fallback"]
        director._prepare_video_part.return_value = (types.Part.from_bytes(data=b'video', mime_type='video/mp4'), None, None)
        if localized is None:
            localized = {'regions': [
                {'kind': r['kind'], 'visible_text': r.get('label', ''),
                 'box_2d': [round(r['y']*1000), round(r['x']*1000), round((r['y']+r['height'])*1000), round((r['x']+r['width'])*1000)]}
                for r in payload.get('regions', [])]}
        responses = [SimpleNamespace(text=json.dumps(payload)), SimpleNamespace(text=json.dumps(localized))]
        if missing_primary:
            class MissingModel(RuntimeError):
                code = 404
            responses.insert(0, MissingModel("Publisher model models/primary was not found"))
        director._generate_content_with_retry.side_effect = responses
        with patch('backend.services.creator_masker.subprocess.run', return_value=SimpleNamespace(stdout=b'jpeg')):
            result = audit_creator_overlays(director, self.source, [(5, 3), (100, 4)])
        calls = director._generate_content_with_retry.call_args_list
        if missing_primary:
            self.assertEqual([call.args[1] for call in calls], ["primary", "fallback", "fallback"])
        contents = calls[0].args[2]
        self.assertEqual([part.video_metadata.fps for part in contents[:2]], [5, 5])
        self.assertEqual([part.inline_data.mime_type for part in contents[2:-1]], ['image/jpeg', 'image/jpeg'])
        self.assertFalse(director._prepare_video_part.call_args.kwargs['allow_compress'])
        return result

    def test_audit_covers_multiple_regions_even_without_text_labels(self):
        result = self._audit({'detected': True, 'label': None, 'corner': 'top_right',
                              'regions': [r.model_dump() for r in self.regions]})
        self.assertEqual(len(result.regions), 2)

    def test_unavailable_model_uses_fallback_for_detection_and_localization(self):
        result = self._audit({'detected': True, 'regions': [r.model_dump() for r in self.regions]},
                             missing_primary=True)
        self.assertEqual([region.kind for region in result.regions], ['facecam', 'channel_logo'])

    def test_incomplete_audit_stops_instead_of_claiming_clean(self):
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            self._audit({'detected': True, 'regions': []})
        self.assertFalse(self._audit({'detected': False, 'regions': []}).detected)

    def test_image_grounding_rejects_invented_text_and_tightens_camera(self):
        candidates = [r.model_dump() for r in self.regions]
        candidates[0]['height'] = .55
        candidates.append(dict(kind='creator_text', label='Inferred channel name', x=.7, y=.9, width=.3, height=.1))
        grounded = {'regions': [
            dict(kind='facecam', visible_text='', box_2d=[0,750,320,1000]),
            dict(kind='channel_logo', visible_text='SG', box_2d=[0,0,100,60]),
        ]}
        result = self._audit({'detected': True, 'regions': candidates}, grounded)
        self.assertEqual(len(result.regions), 2)
        self.assertEqual(result.regions[0].height, .32)
        self.assertEqual(result.corner.value, 'top_right')
        with self.assertRaisesRegex(ValueError, 'camera could not be localized'):
            self._audit({'detected': True, 'regions': candidates}, {'regions': []})

    def test_audit_failure_stops_shared_render_before_any_crop(self):
        clip = dict(clip_id='test', start_time=5, duration=6, video_format='explainer', narration_language='english',
                    verification_passed=True, voice_path=str(self.root / 'test_continuous_voice.wav'),
                    beats=[{'start_time': 5, 'duration': 3}, {'start_time': 100, 'duration': 3}])
        job = {'clips': [clip], 'request': {'enable_watermark_masker': True, 'crop_mode': 'action_track'},
               'metadata': {'raw_path': str(self.source), 'duration': 200, 'cut_start_sec': 10}}
        with patch.dict(studio.JOBS_DB, {'mask_test': job}), \
                patch.object(studio, 'audit_creator_overlays', side_effect=RuntimeError('audit failed')) as audit, \
                patch.object(studio.video_cropper, 'crop_to_vertical') as crop:
            with self.assertRaisesRegex(RuntimeError, 'audit failed'):
                asyncio.run(studio.render_single_clip('mask_test', 0))
            self.assertEqual(audit.call_args.args[2], [(15, 3), (110, 3)])
            crop.assert_not_called()

    def test_protected_ffmpeg_failure_never_uses_unmasked_fallback(self):
        with patch.object(self.cropper, '_get_video_metadata', return_value={'width': 1920, 'height': 1080}), \
                patch.object(creator_inpainter, 'reconstruct_segment', return_value=self.source), \
                patch('backend.services.video_cropper.subprocess.run', return_value=SimpleNamespace(returncode=1, stderr='encoder failed')) as run:
            with self.assertRaisesRegex(RuntimeError, 'unmasked fallback'):
                self.cropper.crop_to_vertical(self.source, 0, 1, self.root / 'bad.mp4', mode=CropMode.CENTER_ZOOM,
                                               mask_webcam=False, creator_regions=self.regions)
            self.assertEqual(run.call_count, 1)

    def test_actual_pixels_hide_camera_and_logo_in_every_layout(self):
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'color=green:s=1920x1080:r=10:d=0.3', '-vf',
                        'drawbox=x=1440:y=0:w=480:h=345:color=red:t=fill,drawbox=x=0:y=0:w=110:h=105:color=blue:t=fill,drawbox=x=960:y=0:w=190:h=210:color=yellow:t=fill',
                        '-c:v', 'libx264', '-preset', 'ultrafast', str(self.source)], check=True)
        for mode in CropMode:
            output = self.root / f'{mode.value}.mp4'
            def generated_green(frames, mask):
                return [np.full_like(frame, (0, 128, 0)) for frame in frames]
            with self.subTest(mode=mode), patch.object(self.cropper, 'calculate_action_track_x', return_value=1300), \
                    patch.object(creator_inpainter, '_predict_rgb', side_effect=generated_green):
                self.cropper.crop_to_vertical(self.source, 0, .3, output, mode=mode,
                                               mask_webcam=False, creator_regions=[
                                                   CreatorOverlayRegion(kind='facecam', x=.75, y=0, width=.22, height=.32),
                                                   self.regions[1],
                                                   CreatorOverlayRegion(kind='creator_text', x=.5, y=0, width=.1, height=.2)])
                cap = cv2.VideoCapture(str(output))
                ok, frame = cap.read()
                cap.release()
                self.assertTrue(ok)
                if mode == CropMode.ACTION_TRACK:
                    camera = frame[100:250, 350:500]
                else:
                    camera = frame[680:800, 850:1075]
                    logo = frame[665:690, 8:45]
                    self.assertGreater(float(logo[:, :, 1].min()), 80)
                    # Both foreground and background use the redacted source.
                    self.assertGreater(float(frame[50:100, 620:670, 1].min()), 80)
                    self.assertGreater(float(frame[950, 500, 1]), 80)
                self.assertGreater(float(camera[:, :, 1].min()), 80)
