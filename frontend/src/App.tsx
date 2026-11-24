import { useState, useEffect, useRef } from 'react';
import {
  Zap,
  FolderPlus,
  Share2,
  Settings as SettingsIcon,
  Cpu,
  Bot,
  CheckCircle2,
  Clock,
  Sparkles,
  ShieldCheck,
  Video,
  Languages,
  PlayCircle,
  TrendingUp,
  Volume2,
  Eye,
  Download,
  Check,
  ExternalLink,
  Youtube,
  Instagram,
  Facebook,
  Save,
  Trash2,
  Terminal,
  ChevronDown,
  ChevronUp,
  Activity,
  Scissors,
  AlertCircle,
  Copy,
  Calendar,
  Globe,
  Lock,
  EyeOff,
  X,
  Columns,
  Layers,
  UploadCloud,
  Loader2
} from 'lucide-react';

interface HardwareStatus {
  os: string;
  architecture: string;
  device_name: string;
  accelerator: string;
  badge_label: string;
  ffmpeg_codec: string;
  whisper_backend: string;
}

interface SocialMetadata {
  youtube: {
    title: string;
    description: string;
    tags: string[];
    privacy: string;
  };
  instagram: {
    caption: string;
    hashtags: string[];
  };
  facebook: {
    caption: string;
    hashtags: string[];
  };
}

interface StoryBeat {
  beat_id: string;
  label: string;
  start_time: number;
  duration: number;
  description?: string;
}

interface Clip {
  clip_id: string;
  clip_type?: 'story_montage' | 'single_moment';
  start_time: number;
  end_time: number;
  duration: number;
  beats?: StoryBeat[];
  virality_score: number;
  reviewer_score?: number;
  reviewer_verdict?: string;
  hook_text: string;
  hook_summary: string;
  commentary_script: string;
  has_copyrighted_music: boolean;
  detected_music_name?: string;
  overlay_prompt: string;
  overlay_path?: string;
  voice_path?: string;
  preview_url?: string;
  status?: string;
  crop_mode: 'action_track' | 'facecam_split' | 'center_zoom';
  caption_style: 'hormozi_yellow' | 'neon_cyan' | 'clean_white';
  tts_voice: string;
  social_metadata?: SocialMetadata;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<'new_project' | 'studio' | 'comparison' | 'youtube' | 'facebook' | 'upload' | 'settings'>('new_project');
  const [hardware, setHardware] = useState<HardwareStatus | null>(null);

  // YouTube Direct Publishing State
  const [ytTitle, setYtTitle] = useState('');
  const [ytDescription, setYtDescription] = useState('');
  const [ytTags, setYtTags] = useState<string[]>([]);
  const [ytTagInput, setYtTagInput] = useState('');
  const [ytPrivacy, setYtPrivacy] = useState<'public' | 'unlisted' | 'private' | 'scheduled'>('public');
  const [ytScheduleDate, setYtScheduleDate] = useState('');
  const [ytScheduleTime, setYtScheduleTime] = useState('18:00');
  const [ytPublishing, setYtPublishing] = useState(false);
  const [ytPublishResult, setYtPublishResult] = useState<{ url: string; video_id: string } | null>(null);
  const [ytPublishError, setYtPublishError] = useState<string | null>(null);
  const [ytAuthStatus, setYtAuthStatus] = useState<{
    has_token: boolean;
    has_client_secret: boolean;
    channel_title?: string | null;
    channel_avatar?: string | null;
    channel_handle?: string | null;
    subscriber_count?: string | null;
  } | null>(null);
  const [ytConnecting, setYtConnecting] = useState(false);
  const [authPopupUrl, setAuthPopupUrl] = useState<string | null>(null);
  const [showYtAuthModal, setShowYtAuthModal] = useState(false);
  const [ytSecretContent, setYtSecretContent] = useState('');

  // Facebook Reels Direct Publishing State
  const [fbCaption, setFbCaption] = useState('');
  const [fbHashtags, setFbHashtags] = useState<string[]>([]);
  const [fbTagInput, setFbTagInput] = useState('');
  const [fbPageId, setFbPageId] = useState('');
  const [fbState, setFbState] = useState<'PUBLISHED' | 'SCHEDULED' | 'DRAFT'>('PUBLISHED');
  const [fbScheduleDate, setFbScheduleDate] = useState('');
  const [fbScheduleTime, setFbScheduleTime] = useState('18:00');
  const [fbPublishing, setFbPublishing] = useState(false);
  const [fbPublishResult, setFbPublishResult] = useState<{ url: string; video_id: string } | null>(null);
  const [fbPublishError, setFbPublishError] = useState<string | null>(null);
  const [fbAuthStatus, setFbAuthStatus] = useState<{ has_token: boolean; has_page_id: boolean; page_id?: string } | null>(null);
  const [showFbAuthModal, setShowFbAuthModal] = useState(false);

  // Comparison Studio State (GTA 5/4 vs GTA 6)
  const [compFormat, setCompFormat] = useState<'shorts_split' | 'long_side_by_side'>('shorts_split');
  const [compBaseGame, setCompBaseGame] = useState<'gta5' | 'gta4'>('gta5');
  const [compGta6Url, setCompGta6Url] = useState('https://youtu.be/2LySmj8f24U');
  const [compGta6StartTime, setCompGta6StartTime] = useState('00:00:40');
  const [compGta6Duration, setCompGta6Duration] = useState(15);
  const [compBaseUrl, setCompBaseUrl] = useState('https://youtu.be/2LySmj8f24U');
  const [compBaseStartTime, setCompBaseStartTime] = useState('00:00:10');
  const [compBaseDuration, setCompBaseDuration] = useState(15);
  const [compQuest, setCompQuest] = useState<any>(null);
  const [isGeneratingQuest, setIsGeneratingQuest] = useState(false);
  const [compUploadedPath, setCompUploadedPath] = useState<string | null>(null);
  const [compUploadedName, setCompUploadedName] = useState<string | null>(null);
  const [isUploadingRec, setIsUploadingRec] = useState(false);
  const [compHookText, setCompHookText] = useState('GTA 5 VS GTA 6 • POLICE AI COMPARISON 🚨');
  const [compCommentaryScript, setCompCommentaryScript] = useState('How did Rockstar completely revolutionize police AI from GTA 5 to GTA 6? In GTA 5, police instantly opened lethal fire with zero warning. But in GTA 6, officers first issue verbal defusal commands and only draw weapons if threatened. Which game has better details?');
  const [compTtsVoice, setCompTtsVoice] = useState('Charon');
  const [isRenderingComp, setIsRenderingComp] = useState(false);
  const [compRenderResult, setCompRenderResult] = useState<any>(null);
  const [compRenderError, setCompRenderError] = useState<string | null>(null);

  // Form states
  const [urlOrFile, setUrlOrFile] = useState('');
  const [language, setLanguage] = useState('hinglish');
  const [clipLength, setClipLength] = useState('30s-55s');
  const [clipCount, setClipCount] = useState(3);
  const [copyrightGuard, setCopyrightGuard] = useState(true);
  const [stripStreamerVoice, setStripStreamerVoice] = useState(true);
  const [voiceoverPacing, setVoiceoverPacing] = useState<'hook_only' | 'full_commentary'>('full_commentary');
  const [selectedVoice, setSelectedVoice] = useState('Charon');
  const [isRevoicing, setIsRevoicing] = useState(false);
  const [isRenderingClip, setIsRenderingClip] = useState(false);
  const [cutStartTime, setCutStartTime] = useState('00:00:00');
  const [cutDurationMins, setCutDurationMins] = useState<number>(20);
  const [autoCutLong, setAutoCutLong] = useState(true);
  const [gameVolumeBoost, setGameVolumeBoost] = useState<number>(1.5);
  const [enableWatermarkMasker, setEnableWatermarkMasker] = useState(true);
  const [enableTopicHeader, setEnableTopicHeader] = useState(true);
  const [longVideoStrategy, setLongVideoStrategy] = useState<'segment_hopper' | 'full_vod_batch' | 'energy_peaks'>('segment_hopper');
  const [jobMetadata, setJobMetadata] = useState<any>(null);
  const [isLaunching, setIsLaunching] = useState(false);

  // Pipeline execution & live WebSocket state
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [progressPct, setProgressPct] = useState(0);
  const [progressMsg, setProgressMsg] = useState('Ready to launch');
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [pipelineStep, setPipelineStep] = useState<'idle' | 'ingesting' | 'analyzing' | 'voicing' | 'completed'>('idle');
  const [clips, setClips] = useState<Clip[]>([]);
  const [selectedClipIndex, setSelectedClipIndex] = useState(0);
  const [showSafeZones, setShowSafeZones] = useState(true);
  const [isResetting, setIsResetting] = useState(false);
  const [resetBanner, setResetBanner] = useState<string | null>(null);
  const [activityLogs, setActivityLogs] = useState<{ timestamp: string; message: string }[]>([]);
  const [showLogs, setShowLogs] = useState(true);
  const logsEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (showLogs && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [activityLogs, showLogs]);

  // Publishing & Export Pack state
  const [copiedToast, setCopiedToast] = useState(false);
  const [publishingPlatform, setPublishingPlatform] = useState<string | null>(null);
  const [publishUrls, setPublishUrls] = useState<{ [platform: string]: string }>({});

  // Settings form states
  const [geminiApiKey, setGeminiApiKey] = useState('');
  const [metaAccessToken, setMetaAccessToken] = useState('');
  const [metaPageId, setMetaPageId] = useState('');
  const [igAccountId, setIgAccountId] = useState('');
  const [publicTunnelUrl, setPublicTunnelUrl] = useState('');
  const [directorModel, setDirectorModel] = useState('gemini-3.8-flash');
  const [ttsModel, setTtsModel] = useState('gemini-3.8-flash-tts');
  const [imageModel, setImageModel] = useState('gemini-3.1-flash-image');
  const [isAdc, setIsAdc] = useState(false);
  const [adcProject, setAdcProject] = useState('');
  const [settingsSaved, setSettingsSaved] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);

  // Fetch real-time hardware status and existing settings
  useEffect(() => {
    fetch('/api/hardware')
      .then((res) => res.json())
      .then((data) => setHardware(data))
      .catch((err) => console.warn('Could not fetch hardware info:', err));

    fetch('/api/settings')
      .then((res) => res.json())
      .then((data) => {
        if (data.is_adc) {
          setIsAdc(true);
          setAdcProject(data.adc_project || '');
        }
        if (data.director_model) setDirectorModel(data.director_model);
        if (data.tts_model) setTtsModel(data.tts_model);
        if (data.image_model) setImageModel(data.image_model);
      })
      .catch(() => {});

    // Automatically restore active or completed job on initial page load
    fetch('/api/jobs/latest')
      .then((res) => (res.ok ? res.json() : null))
      .then((job) => {
        if (job && job.job_id) {
          setActiveJobId(job.job_id);
          setProgressPct(job.progress_pct || 0);
          setProgressMsg(job.step || '');
          if (job.status === 'completed') {
            setPipelineStep('completed');
          }
          if (job.metadata) setJobMetadata(job.metadata);
          if (job.clips && job.clips.length > 0) {
            setClips(job.clips);
            setActiveTab('studio');
          }
        }
      })
      .catch((err) => console.warn('Could not restore latest job:', err));
  }, []);

  const handleLaunch = async (selectedMode: 'manual_studio' | 'auto_pilot' = 'manual_studio') => {
    if (!urlOrFile) {
      alert('Please enter a YouTube link or file path to raw gameplay.');
      return;
    }
    setIsLaunching(true);
    setPipelineError(null);
    setProgressPct(5);
    setProgressMsg(selectedMode === 'manual_studio' ? 'Scanning video to extract all real missions...' : 'Initializing autonomous batch pipeline...');
    setPipelineStep('ingesting');
    const initialTime = new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    setActivityLogs([{
      timestamp: initialTime,
      message: `🚀 Launching ${selectedMode === 'manual_studio' ? 'Topic Discovery (Review & Select First)' : 'Full Auto-Pilot'} on local engine...`
    }]);

    try {
      const res = await fetch('/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url_or_path: urlOrFile,
          mode: selectedMode,
          target_language: language,
          clip_length_range: clipLength,
          clip_count: clipCount,
          copyright_guard: copyrightGuard,
          strip_streamer_voice: stripStreamerVoice,
          voiceover_pacing: voiceoverPacing,
          tts_voice: selectedVoice,
          enable_callout_overlay: false,
          cut_start_time: cutStartTime,
          cut_duration_mins: cutDurationMins,
          auto_cut_long_videos: autoCutLong,
          game_volume_boost: gameVolumeBoost,
          enable_watermark_masker: enableWatermarkMasker,
          enable_topic_header: enableTopicHeader,
          long_video_strategy: longVideoStrategy,
        }),
      });
      const data = await res.json();
      const jobId = data.job_id;
      setActiveJobId(jobId);

      // Establish WebSocket for real-time progress updates
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${wsProtocol}//${window.location.host}/ws/progress/${jobId}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.event === 'progress') {
            setProgressPct(msg.progress_pct);
            setProgressMsg(msg.message);

            const now = new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
            setActivityLogs((prev) => {
              if (prev.length > 0 && prev[prev.length - 1].message === msg.message) {
                return prev;
              }
              return [...prev.slice(-60), { timestamp: now, message: msg.message }];
            });

            if (msg.status === 'ingesting') setPipelineStep('ingesting');
            else if (msg.status === 'analyzing') setPipelineStep('analyzing');
            else if (msg.status === 'voicing') setPipelineStep('voicing');
            else if (msg.status === 'completed' || msg.status === 'cropping') {
              setPipelineStep('completed');
              if (msg.data) {
                if (msg.data.clips) setClips(msg.data.clips);
                if (msg.data.metadata) setJobMetadata(msg.data.metadata);
                setActiveTab('studio');
              }
            }
          } else if (msg.event === 'clip_rendering') {
            setIsRenderingClip(true);
          } else if (msg.event === 'clip_rendered') {
            setClips((prev) =>
              prev.map((c) =>
                c.clip_id === msg.clip_id
                  ? { ...c, preview_url: msg.preview_url, status: 'rendered' }
                  : c
              )
            );
            setIsRenderingClip(false);
          } else if (msg.event === 'job_cancelled') {
            setActiveJobId(null);
            setProgressPct(0);
            setProgressMsg(msg.message || 'Pipeline cancelled.');
            setPipelineStep('idle');
            setIsLaunching(false);
          } else if (msg.event === 'error') {
            setIsLaunching(false);
            setPipelineError(msg.message || 'Pipeline encountered an error.');
            setProgressMsg(msg.message || 'Error occurred');
            const now = new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
            setActivityLogs((prev) => [...prev.slice(-60), { timestamp: now, message: `❌ ${msg.message}` }]);
          }
        } catch (e) {
          console.error('Error parsing WS message:', e);
        }
      };

      ws.onerror = (err) => console.warn('WebSocket error:', err);
    } catch (err) {
      console.error(err);
      alert('Error launching job pipeline.');
    } finally {
      setIsLaunching(false);
    }
  };

  const handleStopAndReset = async (skipConfirm = false) => {
    if (!skipConfirm) {
      const ok = window.confirm(
        '🛑 Are you sure you want to completely RESET all data?\n\nThis will permanently DELETE:\n• All downloaded raw YouTube videos\n• All generated vertical video clips\n• All voiceovers, topic banners, and proxies\n• All jobs history'
      );
      if (!ok) return;
    }

    setIsResetting(true);
    try {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }

      const res = await fetch('/api/pipeline/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: activeJobId,
          delete_all: true,
        }),
      });
      const data = await res.json();

      setActiveJobId(null);
      setProgressPct(0);
      setProgressMsg('All data reset. Workspace is completely clean.');
      setPipelineError(null);
      setPipelineStep('idle');
      setIsLaunching(false);
      setClips([]);
      setSelectedClipIndex(0);
      setUrlOrFile('');
      setPublishUrls({});
      setYtPublishResult(null);
      setYtPublishError(null);
      setJobMetadata(null);
      setActivityLogs((prev) => [
        ...prev,
        {
          timestamp: new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          message: `🗑️ Complete reset performed: Deleted all downloaded videos, clips, and assets. Freed ${data.freed_mb || 0} MB.`,
        },
      ]);

      setResetBanner(
        `✅ Complete reset successful! Deleted all downloaded videos, clips, and assets. Freed ${data.freed_mb || 0} MB disk space.`
      );
      setTimeout(() => setResetBanner(null), 8000);
    } catch (err) {
      console.error('Reset error:', err);
      alert('Error resetting data.');
    } finally {
      setIsResetting(false);
    }
  };

  const handleUpdateCurrentClip = async (fields: Partial<Clip>) => {
    if (!activeJobId || clips.length === 0) return;
    const currentClip = clips[selectedClipIndex];
    const updatedClips = [...clips];
    updatedClips[selectedClipIndex] = { ...currentClip, ...fields };
    setClips(updatedClips);

    try {
      await fetch(`/api/jobs/${activeJobId}/clips/${currentClip.clip_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields),
      });
    } catch (e) {
      console.warn('Could not sync clip update:', e);
    }
  };

  const handleRenderSelectedClip = async () => {
    if (!activeJobId || !activeClip) return;
    setIsRenderingClip(true);
    try {
      await fetch(`/api/jobs/${activeJobId}/clips/${activeClip.clip_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          commentary_script: activeClip.commentary_script,
          hook_text: activeClip.hook_text,
          crop_mode: activeClip.crop_mode,
          caption_style: activeClip.caption_style,
          tts_voice: activeClip.tts_voice || 'Charon',
        }),
      });
      const res = await fetch(`/api/jobs/${activeJobId}/clips/${activeClip.clip_id}/render`, {
        method: 'POST',
      });
      if (!res.ok) throw new Error('Render request failed');
    } catch (err: any) {
      console.error('Failed to render clip:', err);
      alert(`Render error: ${err.message}`);
      setIsRenderingClip(false);
    }
  };

  const handleRegenerateVoiceAndRender = async () => {
    if (!activeJobId || !activeClip) return;
    setIsRevoicing(true);
    try {
      await fetch(`/api/jobs/${activeJobId}/clips/${activeClip.clip_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          commentary_script: activeClip.commentary_script,
          hook_text: activeClip.hook_text,
          tts_voice: activeClip.tts_voice || 'Charon',
        }),
      });
      await fetch(`/api/jobs/${activeJobId}/clips/${activeClip.clip_id}/regenerate-voice`, {
        method: 'POST',
      });
      await fetch(`/api/jobs/${activeJobId}/clips/${activeClip.clip_id}/render`, {
        method: 'POST',
      });
      alert('🎙️ Voiceover regenerated & re-rendering initiated!');
    } catch (err: any) {
      console.error('Failed to regenerate voice and render:', err);
      alert(`Voice regeneration error: ${err.message}`);
    } finally {
      setIsRevoicing(false);
    }
  };

  // Comparison Studio Handlers
  const handleGenerateQuest = async () => {
    if (!compGta6Url) return;
    setIsGeneratingQuest(true);
    setCompRenderError(null);
    try {
      const res = await fetch('/api/comparison/generate-quest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gta6_url_or_path: compGta6Url,
          base_game: compBaseGame,
          target_language: language,
          start_time: compGta6StartTime,
          duration_sec: compGta6Duration,
        }),
      });
      const data = await res.json();
      setCompQuest(data);
      if (data.hook_text) setCompHookText(data.hook_text);
      if (data.commentary_script) setCompCommentaryScript(data.commentary_script);
    } catch (e: any) {
      console.error('Quest generation failed:', e);
      setCompRenderError(e.message || 'Failed to generate comparison quest');
    } finally {
      setIsGeneratingQuest(false);
    }
  };

  const handleUploadRecording = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsUploadingRec(true);
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await fetch('/api/comparison/upload-recording', {
        method: 'POST',
        body: fd,
      });
      const data = await res.json();
      if (data.file_path) {
        setCompUploadedPath(data.file_path);
        setCompUploadedName(data.filename);
        setCompBaseUrl(data.file_path);
      }
    } catch (e: any) {
      console.error('Recording upload failed:', e);
      alert('Upload failed: ' + e.message);
    } finally {
      setIsUploadingRec(false);
    }
  };

  const handleRenderComparison = async () => {
    setIsRenderingComp(true);
    setCompRenderError(null);
    setCompRenderResult(null);
    try {
      const res = await fetch('/api/comparison/render', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          format: compFormat,
          base_game: compBaseGame,
          gta6_url_or_path: compGta6Url,
          gta6_start_time: compGta6StartTime,
          gta6_duration_sec: compGta6Duration,
          base_game_url_or_path: compBaseUrl,
          base_game_start_time: compBaseStartTime,
          base_game_duration_sec: compBaseDuration,
          hook_text: compHookText,
          commentary_script: compCommentaryScript,
          tts_voice: compTtsVoice,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Comparison rendering failed');
      }
      const data = await res.json();
      setCompRenderResult(data);
    } catch (e: any) {
      console.error('Render comparison failed:', e);
      setCompRenderError(e.message || 'Comparison render failed');
    } finally {
      setIsRenderingComp(false);
    }
  };

  // 1-Click Export Pack: Downloads MP4 & copies formatted captions/tags to clipboard
  const handleExportPack = () => {
    if (!activeClip) return;

    // 1. Copy formatted social caption & hashtags to clipboard
    const sm = activeClip.social_metadata;
    const copyText = `🎬 ${sm?.youtube.title || activeClip.hook_text}\n\n` +
      `🔥 Description:\n${sm?.youtube.description || activeClip.commentary_script}\n\n` +
      `🏷️ Tags & Hashtags:\n${(sm?.youtube.tags || ['#GTA6', '#Shorts']).join(' ')} ${(sm?.instagram.hashtags || []).join(' ')}`;

    navigator.clipboard.writeText(copyText);
    setCopiedToast(true);
    setTimeout(() => setCopiedToast(false), 3000);

    // 2. Trigger direct MP4 download if available
    if (activeClip.preview_url) {
      const a = document.createElement('a');
      a.href = activeJobId
        ? `/api/jobs/${activeJobId}/clips/${activeClip.clip_id}/download`
        : activeClip.preview_url;
      a.download = `GTA6_${activeClip.clip_id}_Short.mp4`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }
  };

  // Direct Social Publishing
  const handlePublishPlatform = async (platform: 'youtube' | 'facebook' | 'instagram') => {
    if (!activeJobId || !activeClip) return;
    if (!activeClip.preview_url) {
      alert('Please render this clip first before publishing.');
      return;
    }

    setPublishingPlatform(platform);
    try {
      const res = await fetch(`/api/jobs/${activeJobId}/clips/${activeClip.clip_id}/publish/${platform}`, {
        method: 'POST',
      });
      const data = await res.json();
      if (res.ok && data.url) {
        setPublishUrls((prev) => ({ ...prev, [platform]: data.url }));
        alert(`Published to ${platform.toUpperCase()}! Live URL: ${data.url}`);
      } else {
        alert(`${platform.toUpperCase()} publishing note: ${data.detail || 'API token not configured. Use the 1-Click Export Pack for instant manual posting.'}`);
      }
    } catch (err: any) {
      alert(`Publishing to ${platform} error: ${err.message}`);
    } finally {
      setPublishingPlatform(null);
    }
  };

  const handleSaveSettings = async () => {
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gemini_api_key: geminiApiKey || undefined,
          meta_access_token: metaAccessToken || undefined,
          meta_page_id: metaPageId || undefined,
          instagram_account_id: igAccountId || undefined,
          public_tunnel_url: publicTunnelUrl || undefined,
          director_model: directorModel,
          tts_model: ttsModel,
          image_model: imageModel,
        }),
      });
      if (res.ok) {
        setSettingsSaved(true);
        setTimeout(() => setSettingsSaved(false), 3000);
      }
    } catch (e) {
      console.error(e);
      alert('Failed to save settings.');
    }
  };

  const activeClip = clips[selectedClipIndex];

  // Synchronize active clip metadata with YouTube Direct form
  useEffect(() => {
    if (activeClip) {
      const sm = activeClip.social_metadata?.youtube;
      setYtTitle(sm?.title || `${activeClip.hook_text} #Shorts`);
      setYtDescription(sm?.description || `${activeClip.hook_summary}\n\n#GTA6 #GrandTheftAuto #Gaming #Shorts #Viral`);
      setYtTags(sm?.tags || ['GTA6', 'Shorts', 'Gaming', 'GrandTheftAuto']);
    }
  }, [selectedClipIndex, clips]);

  useEffect(() => {
    const tmrw = new Date();
    tmrw.setDate(tmrw.getDate() + 1);
    setYtScheduleDate(tmrw.toISOString().split('T')[0]);
  }, []);

  const fetchYtAuthStatus = () => {
    fetch('/api/youtube/status')
      .then((res) => res.json())
      .then((data) => setYtAuthStatus(data))
      .catch((err) => console.warn('Could not fetch YouTube auth status:', err));
  };

  useEffect(() => {
    fetchYtAuthStatus();
  }, []);

  const handlePublishYouTubeDirect = async () => {
    if (!activeJobId || !activeClip) return;
    if (!activeClip.preview_url) {
      alert('This clip is still rendering. Please wait until rendering completes.');
      return;
    }
    setYtPublishing(true);
    setYtPublishError(null);
    setYtPublishResult(null);

    let publishAtIso: string | undefined = undefined;
    if (ytPrivacy === 'scheduled') {
      if (!ytScheduleDate || !ytScheduleTime) {
        alert('Please choose both a schedule date and time.');
        setYtPublishing(false);
        return;
      }
      try {
        const localDt = new Date(`${ytScheduleDate}T${ytScheduleTime}:00`);
        publishAtIso = localDt.toISOString();
      } catch (err) {
        alert('Invalid schedule date or time.');
        setYtPublishing(false);
        return;
      }
    }

    try {
      const res = await fetch(`/api/jobs/${activeJobId}/clips/${activeClip.clip_id}/publish/youtube`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: ytTitle,
          description: ytDescription,
          tags: ytTags,
          privacy: ytPrivacy,
          publish_at: publishAtIso,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'YouTube API upload failed.');
      }
      setYtPublishResult({ url: data.url, video_id: data.video_id });
      setPublishUrls((prev) => ({ ...prev, youtube: data.url }));
    } catch (err: any) {
      console.error('YouTube publish error:', err);
      setYtPublishError(err.message || 'Failed to publish to YouTube.');
    } finally {
      setYtPublishing(false);
    }
  };

  const handleOpenStudioUploader = () => {
    const fullText = `TITLE:\n${ytTitle}\n\nDESCRIPTION:\n${ytDescription}\n\nTAGS:\n${ytTags.join(', ')}`;
    navigator.clipboard.writeText(fullText);
    setCopiedToast(true);
    setTimeout(() => setCopiedToast(false), 3000);
    window.open('https://studio.youtube.com/channel/videos/upload?d=pt', '_blank');
  };

  const handleConnectYouTube = async () => {
    setYtConnecting(true);
    setShowYtAuthModal(true);
    try {
      const res = await fetch('/api/youtube/connect', { method: 'POST' });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Failed to authenticate with YouTube');
      }

      if (data.status === 'connected') {
        await fetchYtAuthStatus();
        setYtConnecting(false);
        return;
      }

      if (data.auth_url) {
        setAuthPopupUrl(data.auth_url);
        try {
          window.open(data.auth_url, '_blank');
        } catch (e) {
          console.warn('Popup blocked by browser', e);
        }
      }

      // Start polling for token completion
      const pollInterval = setInterval(async () => {
        try {
          const statusRes = await fetch('/api/youtube/status');
          const statusData = await statusRes.json();
          if (statusData.has_token) {
            clearInterval(pollInterval);
            setYtAuthStatus(statusData);
            setYtConnecting(false);
            setAuthPopupUrl(null);
          }
        } catch (e) {
          // ignore
        }
      }, 1500);

      // Stop polling after 4 minutes
      setTimeout(() => {
        clearInterval(pollInterval);
        setYtConnecting(false);
      }, 240000);

    } catch (e: any) {
      alert(`YouTube Connection Error: ${e.message}`);
      setYtConnecting(false);
    }
  };

  const handleDisconnectYouTube = async () => {
    if (!confirm('Are you sure you want to disconnect this YouTube channel?')) return;
    try {
      await fetch('/api/youtube/disconnect', { method: 'POST' });
      await fetchYtAuthStatus();
    } catch (e: any) {
      alert(`Error disconnecting: ${e.message}`);
    }
  };

  const handleSaveClientSecret = async () => {
    if (!ytSecretContent.trim()) {
      alert('Please paste the client_secret.json contents.');
      return;
    }
    try {
      JSON.parse(ytSecretContent);
      const res = await fetch('/api/youtube/client-secret', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: ytSecretContent }),
      });
      if (res.ok) {
        alert('Client secret saved successfully! You can now authorize your channel.');
        setYtSecretContent('');
        await fetchYtAuthStatus();
      } else {
        const d = await res.json();
        alert(d.detail || 'Failed to save secret.');
      }
    } catch (e: any) {
      alert('Invalid JSON content. Please ensure you pasted the exact client_secret.json file.');
    }
  };

  // Synchronize active clip metadata with Facebook form
  useEffect(() => {
    if (activeClip) {
      const sm = activeClip.social_metadata?.facebook;
      setFbCaption(sm?.caption || `🔥 Epic GTA 6 Moment: ${activeClip.hook_text}! What a scene.`);
      setFbHashtags(sm?.hashtags || ['#GTA6', '#GrandTheftAuto', '#ViceCity', '#Gaming', '#Reels', '#Viral']);
    }
  }, [selectedClipIndex, clips]);

  const fetchFbAuthStatus = () => {
    fetch('/api/facebook/status')
      .then((res) => res.json())
      .then((data) => {
        setFbAuthStatus(data);
        if (data.page_id && !fbPageId) {
          setFbPageId(data.page_id);
        }
      })
      .catch((err) => console.warn('Could not fetch Facebook status:', err));
  };

  useEffect(() => {
    fetchFbAuthStatus();
  }, []);

  const handlePublishFacebookDirect = async () => {
    if (!activeJobId || !activeClip) return;
    if (!activeClip.preview_url) {
      alert('This clip is still rendering. Please wait until rendering completes.');
      return;
    }
    setFbPublishing(true);
    setFbPublishError(null);
    setFbPublishResult(null);

    let scheduledEpoch: number | undefined = undefined;
    if (fbState === 'SCHEDULED') {
      if (!fbScheduleDate || !fbScheduleTime) {
        alert('Please select both a schedule date and time.');
        setFbPublishing(false);
        return;
      }
      try {
        const localDt = new Date(`${fbScheduleDate}T${fbScheduleTime}:00`);
        scheduledEpoch = Math.floor(localDt.getTime() / 1000);
      } catch (e) {
        alert('Invalid schedule date or time.');
        setFbPublishing(false);
        return;
      }
    }

    try {
      const res = await fetch(`/api/jobs/${activeJobId}/clips/${activeClip.clip_id}/publish/facebook`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          caption: fbCaption,
          hashtags: fbHashtags,
          video_state: fbState,
          scheduled_publish_time: scheduledEpoch,
          page_id: fbPageId || undefined,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Facebook Reels upload failed.');
      }
      setFbPublishResult({ url: data.url, video_id: data.video_id });
      setPublishUrls((prev) => ({ ...prev, facebook: data.url }));
    } catch (err: any) {
      console.error('Facebook publish error:', err);
      setFbPublishError(err.message || 'Failed to publish to Facebook Reels.');
    } finally {
      setFbPublishing(false);
    }
  };

  const handleOpenMetaSuite = () => {
    const fullText = `${fbCaption}\n\n${fbHashtags.join(' ')}`;
    navigator.clipboard.writeText(fullText);
    setCopiedToast(true);
    setTimeout(() => setCopiedToast(false), 3000);
    window.open('https://business.facebook.com/creatorstudio/reels', '_blank');
  };

  return (
    <div className="flex h-screen w-screen bg-[#0B0D12] text-[#F8FAFC] font-sans antialiased overflow-hidden">
      {/* ─────────────────────────────────────────────────────────────
          PERSISTENT LEFT SIDEBAR
      ───────────────────────────────────────────────────────────── */}
      <aside className="w-64 border-r border-[#1F2430] bg-[#0E1117] flex flex-col justify-between shrink-0 select-none">
        <div>
          {/* Logo / Header */}
          <div className="h-16 px-5 border-b border-[#1F2430] flex items-center gap-3">
            <div className="h-9 w-9 rounded-xl bg-gradient-to-tr from-indigo-600 to-emerald-400 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <Zap className="h-5 w-5 text-white" />
            </div>
            <div>
              <h1 className="text-sm font-bold tracking-wider text-white">GTA6 AI STUDIO</h1>
              <p className="text-[10px] text-emerald-400 font-mono tracking-tight">V1.0 • M4/RTX ULTRA</p>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="p-3 space-y-1">
            <button
              onClick={() => setActiveTab('new_project')}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === 'new_project'
                  ? 'bg-indigo-600/15 text-indigo-400 border border-indigo-500/30'
                  : 'text-slate-400 hover:text-white hover:bg-[#141821]'
              }`}
            >
              <FolderPlus className="h-4 w-4" />
              <span>1. AI Launchpad</span>
            </button>

            <button
              onClick={() => setActiveTab('studio')}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === 'studio'
                  ? 'bg-indigo-600/15 text-indigo-400 border border-indigo-500/30'
                  : 'text-slate-400 hover:text-white hover:bg-[#141821]'
              }`}
            >
              <PlayCircle className="h-4 w-4" />
              <span>2. AI Shorts Player</span>
              {clips.length > 0 && (
                <span className="ml-auto text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-600 text-white">
                  {clips.length}
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('comparison')}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === 'comparison'
                  ? 'bg-gradient-to-r from-pink-600/25 to-cyan-600/25 text-pink-300 border border-pink-500/40 shadow-sm shadow-pink-950/20'
                  : 'text-slate-400 hover:text-white hover:bg-[#141821]'
              }`}
            >
              <Columns className="h-4 w-4 text-pink-400" />
              <span className="font-semibold text-white">3. Comparison VS</span>
              <span className="ml-auto text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-gradient-to-r from-pink-500 to-cyan-400 text-black font-mono">
                VS
              </span>
            </button>

            <button
              onClick={() => setActiveTab('youtube')}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === 'youtube'
                  ? 'bg-red-600/20 text-red-400 border border-red-500/40 shadow-sm shadow-red-950/20'
                  : 'text-slate-400 hover:text-white hover:bg-[#141821]'
              }`}
            >
              <Youtube className="h-4 w-4 text-red-500" />
              <span className="font-semibold text-white">4. YouTube Direct Hub</span>
              <span className="ml-auto text-[9px] font-bold px-1.5 py-0.5 rounded bg-red-600/30 text-red-300 font-mono">
                DIRECT
              </span>
            </button>

            <button
              onClick={() => setActiveTab('facebook')}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === 'facebook'
                  ? 'bg-blue-600/20 text-blue-400 border border-blue-500/40 shadow-sm shadow-blue-950/20'
                  : 'text-slate-400 hover:text-white hover:bg-[#141821]'
              }`}
            >
              <Facebook className="h-4 w-4 text-blue-500" />
              <span className="font-semibold text-white">4. Facebook Reels Hub</span>
              <span className="ml-auto text-[9px] font-bold px-1.5 py-0.5 rounded bg-blue-600/30 text-blue-300 font-mono">
                REELS
              </span>
            </button>

            <button
              onClick={() => setActiveTab('upload')}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === 'upload'
                  ? 'bg-indigo-600/15 text-indigo-400 border border-indigo-500/30'
                  : 'text-slate-400 hover:text-white hover:bg-[#141821]'
              }`}
            >
              <Share2 className="h-4 w-4" />
              <span>5. Multi-Platform Hub</span>
            </button>

            <button
              onClick={() => setActiveTab('settings')}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === 'settings'
                  ? 'bg-indigo-600/15 text-indigo-400 border border-indigo-500/30'
                  : 'text-slate-400 hover:text-white hover:bg-[#141821]'
              }`}
            >
              <SettingsIcon className="h-4 w-4" />
              <span>6. AI Engine Settings</span>
            </button>
          </nav>
        </div>

        {/* Real-time Hardware Badge */}
        <div className="p-4 border-t border-[#1F2430] bg-[#0B0D12]">
          <div className="flex items-center gap-2 mb-1.5">
            <Cpu className="h-3.5 w-3.5 text-emerald-400" />
            <span className="text-[11px] font-semibold text-slate-300 uppercase tracking-wider">
              Hardware Engine
            </span>
          </div>
          <div className="rounded-lg bg-[#141821] border border-[#1F2430] p-2.5">
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse"></span>
              <p className="text-[11px] font-medium text-slate-200 truncate">
                {hardware ? hardware.badge_label : 'Apple M4 VideoToolbox Active'}
              </p>
            </div>
            {hardware && (
              <p className="text-[10px] text-slate-400 mt-1 font-mono">
                Encoder: {hardware.ffmpeg_codec}
              </p>
            )}
          </div>
        </div>
      </aside>

      {/* ─────────────────────────────────────────────────────────────
          MAIN CONTENT AREA
      ───────────────────────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col h-full overflow-hidden bg-[#0B0D12]">
        {/* Top Header Bar */}
        <header className="h-16 border-b border-[#1F2430] px-8 flex items-center justify-between bg-[#0E1117]/80 backdrop-blur-md shrink-0">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2.5 px-3.5 py-1.5 rounded-xl bg-indigo-600/15 border border-indigo-500/30 text-indigo-300 font-semibold text-xs shadow-inner">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </span>
              <Bot className="h-4 w-4 text-indigo-400" />
              <span>100% Autonomous AI Pipeline</span>
            </div>
            <span className="text-[11px] text-slate-500 font-mono hidden md:inline">
              Gemini Vision • Zero-Touch Director • Auto NVENC Render
            </span>
          </div>

          <div className="flex items-center gap-3 text-xs">
            <button
              onClick={() => handleStopAndReset(false)}
              disabled={isResetting}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-500/15 hover:bg-rose-500/25 border border-rose-500/40 text-rose-300 hover:text-white transition-all font-semibold shadow-md shadow-rose-950/30 disabled:opacity-50"
              title="Permanently delete all downloaded YouTube videos, clips, voiceovers, and jobs"
            >
              <Trash2 className="h-3.5 w-3.5 text-rose-400" />
              <span>{isResetting ? 'Wiping All Data...' : '🛑 Reset All Data'}</span>
            </button>

            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#141821] border border-[#1F2430] text-slate-300">
              <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
              <span>{isAdc ? `🟢 Google Cloud ADC (${adcProject})` : `${directorModel} Ready`}</span>
            </div>

            {ytAuthStatus?.has_token ? (
              <div
                onClick={() => setActiveTab('youtube')}
                className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-[#141821] border border-red-500/40 text-slate-300 hover:text-white cursor-pointer hover:border-red-400 transition-all shadow-sm"
                title={`Connected YouTube Channel: ${ytAuthStatus.channel_title || 'Channel'}`}
              >
                {ytAuthStatus.channel_avatar ? (
                  <img
                    src={ytAuthStatus.channel_avatar}
                    alt="YouTube Avatar"
                    className="h-5 w-5 rounded-full border border-red-500 object-cover"
                  />
                ) : (
                  <Youtube className="h-4 w-4 text-red-500" />
                )}
                <span className="text-[11px] font-semibold text-slate-200 max-w-[120px] truncate">
                  {ytAuthStatus.channel_title}
                </span>
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              </div>
            ) : ytAuthStatus?.has_client_secret ? (
              <button
                onClick={handleConnectYouTube}
                disabled={ytConnecting}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-red-600/20 border border-red-500/40 text-red-300 hover:bg-red-600/30 text-[11px] font-semibold transition-all"
                title="Click to sign in with Google & authorize your YouTube channel"
              >
                <Youtube className="h-3.5 w-3.5 text-red-400" />
                <span>{ytConnecting ? 'Signing in...' : 'Connect YouTube'}</span>
              </button>
            ) : null}
          </div>
        </header>

        {/* Dynamic View Body */}
        <div className="flex-1 overflow-y-auto p-8">
          {/* VIEW 1: NEW PROJECT */}
          {activeTab === 'new_project' && (
            <div className="max-w-4xl mx-auto space-y-6">
              <div>
                <h2 className="text-xl font-bold text-white tracking-tight">Create Viral Short-Form Project</h2>
                <p className="text-xs text-slate-400 mt-1">
                  Upload raw 1080p GTA gameplay or paste a YouTube VOD link to initiate Gemini AI multimodal director.
                </p>
              </div>

              {/* Ingest Dropzone Card */}
              <div className="bg-[#141821] rounded-2xl border border-[#1F2430] p-6 shadow-xl">
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-300 mb-2">
                  Gameplay Source (YouTube URL or Local File Path)
                </label>
                <div className="relative">
                  <input
                    type="text"
                    value={urlOrFile}
                    onChange={(e) => setUrlOrFile(e.target.value)}
                    placeholder="https://www.youtube.com/watch?v=... or /Users/.../gameplay.mp4"
                    className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition-colors"
                  />
                  <div className="absolute right-3 top-2.5">
                    <span className="text-[10px] font-mono px-2 py-1 rounded bg-[#1F2430] text-slate-400">
                      yt-dlp
                    </span>
                  </div>
                </div>

                {/* Settings Grid */}
                <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mt-6">
                  {/* Language */}
                  <div className="bg-[#0B0D12] border border-[#1F2430] p-4 rounded-xl">
                    <div className="flex items-center gap-2 mb-2 text-slate-300">
                      <Languages className="h-4 w-4 text-indigo-400" />
                      <span className="text-xs font-semibold">Target Language</span>
                    </div>
                    <select
                      value={language}
                      onChange={(e) => setLanguage(e.target.value)}
                      className="w-full bg-[#141821] border border-[#1F2430] rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                    >
                      <option value="hinglish">Hinglish (Viral Gaming Tone)</option>
                      <option value="english">English (US/UK Energetic)</option>
                      <option value="hindi">Hindi (Pure Hindi)</option>
                    </select>
                  </div>

                  {/* Length & Count */}
                  <div className="bg-[#0B0D12] border border-[#1F2430] p-4 rounded-xl">
                    <div className="flex items-center gap-2 mb-2 text-slate-300">
                      <Clock className="h-4 w-4 text-emerald-400" />
                      <span className="text-xs font-semibold">Clip Length & Count</span>
                    </div>
                    <div className="flex gap-2">
                      <select
                        value={clipLength}
                        onChange={(e) => setClipLength(e.target.value)}
                        className="w-1/2 bg-[#141821] border border-[#1F2430] rounded-lg px-2 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                      >
                        <option value="30s-45s">30s – 45s</option>
                        <option value="30s-55s">30s – 55s</option>
                        <option value="45s-60s">45s – 60s</option>
                      </select>
                      <select
                        value={clipCount}
                        onChange={(e) => setClipCount(Number(e.target.value))}
                        className="w-1/2 bg-[#141821] border border-[#1F2430] rounded-lg px-2 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                      >
                        <option value={1}>1 Clip</option>
                        <option value={3}>3 Clips</option>
                        <option value={5}>5 Clips</option>
                      </select>
                    </div>
                  </div>

                  {/* Copyright Guard */}
                  <div className="bg-[#0B0D12] border border-[#1F2430] p-4 rounded-xl flex flex-col justify-between">
                    <div className="flex items-center gap-2 mb-2 text-slate-300">
                      <ShieldCheck className="h-4 w-4 text-emerald-400" />
                      <span className="text-xs font-semibold">Copyright Guard</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] text-slate-400">Strip GTA Radio</span>
                      <button
                        onClick={() => setCopyrightGuard(!copyrightGuard)}
                        className={`w-11 h-6 flex items-center rounded-full p-1 transition-colors ${
                          copyrightGuard ? 'bg-emerald-500' : 'bg-slate-700'
                        }`}
                      >
                        <div
                          className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${
                            copyrightGuard ? 'translate-x-5' : 'translate-x-0'
                          }`}
                        />
                      </button>
                    </div>
                  </div>

                  {/* Streamer Mic Voice Removal */}
                  <div className="bg-[#0B0D12] border border-[#1F2430] p-4 rounded-xl flex flex-col justify-between">
                    <div>
                      <div className="flex items-center gap-2 mb-1 text-slate-300">
                        <Volume2 className="h-4 w-4 text-emerald-400" />
                        <span className="text-xs font-semibold">Remove Streamer Voice</span>
                      </div>
                      <p className="text-[10px] text-slate-500 leading-tight">Demucs AI isolates pure game SFX & wipes streamer commentary</p>
                    </div>
                    <div className="flex items-center justify-between mt-2">
                      <span className="text-[11px] text-emerald-400 font-medium">Demucs AI Active</span>
                      <button
                        onClick={() => setStripStreamerVoice(!stripStreamerVoice)}
                        className={`w-11 h-6 flex items-center rounded-full p-1 transition-colors ${
                          stripStreamerVoice ? 'bg-indigo-500' : 'bg-slate-700'
                        }`}
                      >
                        <div
                          className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${
                            stripStreamerVoice ? 'translate-x-5' : 'translate-x-0'
                          }`}
                        />
                      </button>
                    </div>
                  </div>
                </div>

                {/* AI Watermark & Facecam Masker */}
                <div className="flex items-center justify-between p-3.5 bg-[#0B0D12] rounded-xl border border-[#1F2430] mt-4">
                  <div className="flex items-center gap-2.5">
                    <ShieldCheck className="h-4 w-4 text-emerald-400" />
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-white">AI Watermark & Facecam Masker</span>
                        <span className="text-[9px] bg-emerald-500/20 text-emerald-300 px-1.5 py-0.5 rounded font-mono font-bold">SMART COVER</span>
                      </div>
                      <p className="text-[10px] text-slate-400">Gemini Vision detects third-party channel watermarks, creator handles, and webcams, auto-covering them with a sleek GTA VI 4K 60FPS badge.</p>
                    </div>
                  </div>
                  <button
                    onClick={() => setEnableWatermarkMasker(!enableWatermarkMasker)}
                    className={`w-11 h-6 flex items-center rounded-full p-1 transition-colors ${
                      enableWatermarkMasker ? 'bg-emerald-500' : 'bg-slate-700'
                    }`}
                  >
                    <div
                      className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${
                        enableWatermarkMasker ? 'translate-x-5' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>

                {/* Top Topic Headline Banner */}
                <div className="flex items-center justify-between p-3.5 bg-[#0B0D12] rounded-xl border border-[#1F2430] mt-4">
                  <div className="flex items-center gap-2.5">
                    <Zap className="h-4 w-4 text-fuchsia-400" />
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-white">Top Topic Headline Banner</span>
                        <span className="text-[9px] bg-fuchsia-500/20 text-fuchsia-300 px-1.5 py-0.5 rounded font-mono font-bold">VIRAL HOOK</span>
                      </div>
                      <p className="text-[10px] text-slate-400">Renders an attractive glassmorphic topic headline card in the upper blurred zone to hook mute scrollers.</p>
                    </div>
                  </div>
                  <button
                    onClick={() => setEnableTopicHeader(!enableTopicHeader)}
                    className={`w-11 h-6 flex items-center rounded-full p-1 transition-colors ${
                      enableTopicHeader ? 'bg-fuchsia-500' : 'bg-slate-700'
                    }`}
                  >
                    <div
                      className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${
                        enableTopicHeader ? 'translate-x-5' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>

                {/* Voiceover Pacing Mode */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between p-3.5 bg-[#0B0D12] rounded-xl border border-[#1F2430] mt-4 gap-3">
                  <div className="flex items-center gap-2.5">
                    <Sparkles className="h-4 w-4 text-amber-400 shrink-0" />
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-white">Voiceover Commentary & Pacing</span>
                        <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 font-bold">
                          REELS VIRAL ENGINE
                        </span>
                      </div>
                      <p className="text-[10px] text-slate-400 mt-0.5">
                        {voiceoverPacing === 'full_commentary'
                          ? '🔥 Story Lore Breakdown: Curiosity hook question, step-by-step mission progression, moral choices, and twist ending.'
                          : '⚡ 3-6s Hook Only: Speaks a quick viral hook at the start, then raw gameplay audio takes over.'}
                      </p>
                    </div>
                  </div>
                  <div className="flex bg-[#141821] p-1 rounded-lg border border-[#1F2430] shrink-0">
                    <button
                      onClick={() => setVoiceoverPacing('full_commentary')}
                      className={`px-3 py-1 rounded text-xs font-semibold transition-all ${
                        voiceoverPacing === 'full_commentary'
                          ? 'bg-indigo-600/40 text-indigo-200 border border-indigo-500/50 shadow-sm'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      🎙️ Story Breakdown (Viral Reels)
                    </button>
                    <button
                      onClick={() => setVoiceoverPacing('hook_only')}
                      className={`px-3 py-1 rounded text-xs font-semibold transition-all ${
                        voiceoverPacing === 'hook_only'
                          ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40 shadow-sm'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      ⚡ 3–6s Hook Only
                    </button>
                  </div>
                </div>

                {/* Voice Persona Selector */}
                <div className="bg-[#0B0D12] border border-[#1F2430] p-3.5 rounded-xl mt-3 flex items-center justify-between">
                  <div>
                    <span className="text-xs font-bold text-white flex items-center gap-1.5">
                      <Volume2 className="h-3.5 w-3.5 text-cyan-400" />
                      TTS Voice Persona
                    </span>
                    <p className="text-[10px] text-slate-400 mt-0.5">
                      Select cinematic narrator voice (Charon = deep cinematic narrator, Aoede = calm engaging, Puck = energetic).
                    </p>
                  </div>
                  <select
                    value={selectedVoice}
                    onChange={(e) => setSelectedVoice(e.target.value)}
                    className="bg-[#141821] border border-[#1F2430] text-xs text-white rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-cyan-500 font-mono"
                  >
                    <option value="Charon">Charon (Deep Cinematic Male)</option>
                    <option value="Aoede">Aoede (Calm Engaging Female)</option>
                    <option value="Kore">Kore (Warm Natural Female)</option>
                    <option value="Fenrir">Fenrir (Intense Resonant Male)</option>
                    <option value="Puck">Puck (Fast-Paced Male)</option>
                  </select>
                </div>



                {/* Video Cutter & AI Analysis Window */}
                <div className="bg-[#0B0D12] border border-[#1F2430] p-4 rounded-xl mt-3">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-2">
                    <div className="flex items-center gap-2">
                      <Scissors className="h-4 w-4 text-amber-400" />
                      <span className="text-xs font-bold text-white">Video Cutter & AI Analysis Window</span>
                      <span className="text-[10px] px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 font-mono font-semibold">
                        Gemini 1M Token Guard
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] text-slate-400">Auto-Cap Streams &gt;60m</span>
                      <button
                        onClick={() => setAutoCutLong(!autoCutLong)}
                        className={`w-9 h-5 flex items-center rounded-full p-0.5 transition-colors ${
                          autoCutLong ? 'bg-amber-500' : 'bg-slate-700'
                        }`}
                      >
                        <div
                          className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${
                            autoCutLong ? 'translate-x-4' : 'translate-x-0'
                          }`}
                        />
                      </button>
                    </div>
                  </div>

                  <p className="text-[11px] text-slate-400 mb-3">
                    Cuts raw multi-hour livestreams/walkthroughs into an optimized segment (up to 60 min) before AI Vision analysis. Uses adaptive frame rates to stay strictly within Gemini's 1M token ceiling.
                  </p>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-[11px] font-semibold text-slate-300 mb-1">
                        Cut Start Timestamp (HH:MM:SS)
                      </label>
                      <input
                        type="text"
                        value={cutStartTime}
                        onChange={(e) => setCutStartTime(e.target.value)}
                        placeholder="00:00:00 (e.g. 01:15:00)"
                        className="w-full bg-[#141821] border border-[#1F2430] rounded-lg px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-amber-500"
                      />
                    </div>

                    <div>
                      <label className="block text-[11px] font-semibold text-slate-300 mb-1">
                        Analysis Window Duration
                      </label>
                      <div className="flex gap-1.5">
                        <button
                          type="button"
                          onClick={() => setCutDurationMins(15)}
                          className={`flex-1 py-2 rounded-lg text-xs font-semibold transition-all ${
                            cutDurationMins === 15
                              ? 'bg-amber-500 text-black font-bold shadow-sm'
                              : 'bg-[#141821] text-slate-400 hover:text-white border border-[#1F2430]'
                          }`}
                        >
                          ⚡ 15m
                        </button>
                        <button
                          type="button"
                          onClick={() => setCutDurationMins(20)}
                          className={`flex-1 py-2 rounded-lg text-xs font-semibold transition-all ${
                            cutDurationMins === 20
                              ? 'bg-amber-500 text-black font-bold shadow-sm'
                              : 'bg-[#141821] text-slate-400 hover:text-white border border-[#1F2430]'
                          }`}
                        >
                          🔥 20m
                        </button>
                        <button
                          type="button"
                          onClick={() => setCutDurationMins(30)}
                          className={`flex-1 py-2 rounded-lg text-xs font-semibold transition-all ${
                            cutDurationMins === 30
                              ? 'bg-amber-500 text-black font-bold shadow-sm'
                              : 'bg-[#141821] text-slate-400 hover:text-white border border-[#1F2430]'
                          }`}
                        >
                          🎬 30m
                        </button>
                        <button
                          type="button"
                          onClick={() => setCutDurationMins(60)}
                          className={`flex-1 py-2 rounded-lg text-xs font-semibold transition-all ${
                            cutDurationMins === 60
                              ? 'bg-amber-500 text-black font-bold shadow-sm'
                              : 'bg-[#141821] text-slate-400 hover:text-white border border-[#1F2430]'
                          }`}
                        >
                          🚀 60m Max
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Multi-Hour VOD Ingestion Strategy Dropdown */}
                  <div className="mt-3.5 pt-3 border-t border-[#1F2430]">
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="text-[11px] font-semibold text-slate-300">
                        Multi-Hour VOD Strategy
                      </label>
                      <span className="text-[9px] text-amber-400 font-mono font-bold bg-amber-500/10 px-1.5 py-0.5 rounded border border-amber-500/20">
                        1h–3h+ Solved
                      </span>
                    </div>

                    <select
                      value={longVideoStrategy}
                      onChange={(e) => setLongVideoStrategy(e.target.value as any)}
                      className="w-full bg-[#141821] border border-[#1F2430] rounded-lg px-3 py-2 text-xs font-semibold text-white focus:outline-none focus:border-amber-500"
                    >
                      <option value="segment_hopper">
                        ⚡ Sequential Segment Hopper (1-Click Next Segment)
                      </option>
                      <option value="energy_peaks">
                        🎯 Audio Energy Peak Scanner (Smart Action Peaks)
                      </option>
                      <option value="full_vod_batch">
                        🤖 Full VOD Auto-Batch (Continuous Queue)
                      </option>
                    </select>

                    <div className="mt-2 text-[10px] text-slate-400 bg-[#0B0D12] p-2.5 rounded-lg border border-[#1F2430] leading-relaxed">
                      {longVideoStrategy === 'segment_hopper' && (
                        <span>⚡ <strong>Interactive Hopper:</strong> Processes 20 mins now and provides a 1-click button to jump & harvest the next segment from the locally cached video (0s download).</span>
                      )}
                      {longVideoStrategy === 'energy_peaks' && (
                        <span>🎯 <strong>Audio Energy Peak Scanner:</strong> Fast 4-second audio analysis across the full 2 hours to detect the highest gunfire, explosion, and combat density window automatically.</span>
                      )}
                      {longVideoStrategy === 'full_vod_batch' && (
                        <span>🤖 <strong>Full VOD Queue:</strong> Automatically divides the multi-hour VOD into sequential chunks and processes all of them in the background.</span>
                      )}
                    </div>
                  </div>
                </div>

                {/* AI Watermark & Facecam Masker */}
                <div className="flex items-center justify-between p-3.5 bg-[#0B0D12] rounded-xl border border-[#1F2430] mt-4">
                  <div className="flex items-center gap-2.5">
                    <ShieldCheck className="h-4 w-4 text-emerald-400" />
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-white">AI Watermark & Facecam Masker</span>
                        <span className="text-[9px] bg-emerald-500/20 text-emerald-300 px-1.5 py-0.5 rounded font-mono font-bold">SMART COVER</span>
                      </div>
                      <p className="text-[10px] text-slate-400">Gemini Vision detects third-party channel watermarks, creator handles, and webcams, auto-covering them with a sleek GTA VI 4K 60FPS badge.</p>
                    </div>
                  </div>
                  <button
                    onClick={() => setEnableWatermarkMasker(!enableWatermarkMasker)}
                    className={`w-11 h-6 flex items-center rounded-full p-1 transition-colors ${
                      enableWatermarkMasker ? 'bg-emerald-500' : 'bg-slate-700'
                    }`}
                  >
                    <div
                      className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${
                        enableWatermarkMasker ? 'translate-x-5' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>

                {/* Top Topic Headline Banner */}
                <div className="flex items-center justify-between p-3.5 bg-[#0B0D12] rounded-xl border border-[#1F2430] mt-4">
                  <div className="flex items-center gap-2.5">
                    <Zap className="h-4 w-4 text-fuchsia-400" />
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-white">Top Topic Headline Banner</span>
                        <span className="text-[9px] bg-fuchsia-500/20 text-fuchsia-300 px-1.5 py-0.5 rounded font-mono font-bold">VIRAL HOOK</span>
                      </div>
                      <p className="text-[10px] text-slate-400">Renders an attractive glassmorphic topic headline card in the upper blurred zone to hook mute scrollers.</p>
                    </div>
                  </div>
                  <button
                    onClick={() => setEnableTopicHeader(!enableTopicHeader)}
                    className={`w-11 h-6 flex items-center rounded-full p-1 transition-colors ${
                      enableTopicHeader ? 'bg-fuchsia-500' : 'bg-slate-700'
                    }`}
                  >
                    <div
                      className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${
                        enableTopicHeader ? 'translate-x-5' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>

                {/* Game Audio SFX Boost */}
                <div className="flex items-center justify-between p-3.5 bg-[#0B0D12] rounded-xl border border-[#1F2430] mt-3">
                  <div className="flex items-center gap-2.5">
                    <Volume2 className="h-4 w-4 text-cyan-400" />
                    <div>
                      <span className="text-xs font-bold text-white">Game SFX Volume Boost</span>
                      <p className="text-[10px] text-slate-400">Amplifies quiet in-game engines, sirens & crashes with an FFmpeg peak limiter to prevent distortion.</p>
                    </div>
                  </div>
                  <div className="flex bg-[#141821] p-1 rounded-lg border border-[#1F2430] gap-1">
                    <button
                      type="button"
                      onClick={() => setGameVolumeBoost(1.0)}
                      className={`px-2.5 py-1 rounded text-xs font-semibold transition-all ${
                        gameVolumeBoost === 1.0
                          ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      100% Normal
                    </button>
                    <button
                      type="button"
                      onClick={() => setGameVolumeBoost(1.5)}
                      className={`px-2.5 py-1 rounded text-xs font-semibold transition-all ${
                        gameVolumeBoost === 1.5
                          ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      🔊 150% Boosted
                    </button>
                    <button
                      type="button"
                      onClick={() => setGameVolumeBoost(2.0)}
                      className={`px-2.5 py-1 rounded text-xs font-semibold transition-all ${
                        gameVolumeBoost === 2.0
                          ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      💥 200% Max
                    </button>
                  </div>
                </div>

                {/* Pipeline Error Alert Banner */}
                {pipelineError && (
                  <div className="mt-4 p-4 bg-rose-500/15 border border-rose-500/40 rounded-xl text-xs text-rose-300 flex items-start justify-between gap-3 shadow-lg shadow-rose-950/30">
                    <div className="flex items-start gap-2.5">
                      <AlertCircle className="h-5 w-5 text-rose-400 shrink-0 mt-0.5" />
                      <div>
                        <span className="font-bold text-rose-200">Pipeline Execution Halted</span>
                        <p className="mt-0.5 text-rose-300/90 text-[11px] leading-relaxed font-mono">{pipelineError}</p>
                      </div>
                    </div>
                    <button
                      onClick={() => handleStopAndReset(false)}
                      className="px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs shrink-0 transition-colors"
                    >
                      Reset & Clear
                    </button>
                  </div>
                )}

                {/* Reset Alert Banner */}
                {resetBanner && (
                  <div className="mt-4 p-3 bg-emerald-500/15 border border-emerald-500/30 rounded-xl text-xs text-emerald-300 flex items-center justify-between">
                    <span>{resetBanner}</span>
                    <button onClick={() => setResetBanner(null)} className="text-slate-400 hover:text-white text-xs">✕</button>
                  </div>
                )}

                {/* Launch & Stop Action Buttons */}
                <div className="mt-6 flex flex-col sm:flex-row items-center gap-3">
                  <button
                    onClick={() => handleLaunch('manual_studio')}
                    disabled={isLaunching || isResetting}
                    className="flex-1 w-full bg-gradient-to-r from-indigo-600 via-purple-600 to-pink-600 hover:opacity-95 text-white font-extrabold py-3.5 px-6 rounded-xl shadow-lg shadow-indigo-600/20 flex items-center justify-center gap-2 transition-all disabled:opacity-50"
                  >
                    <Sparkles className="h-5 w-5 text-amber-300" />
                    <span>{isLaunching ? 'EXTRACTING REAL TOPICS...' : '🔍 SCAN & EXTRACT REAL TOPICS (REVIEW FIRST)'}</span>
                  </button>

                  <button
                    onClick={() => handleLaunch('auto_pilot')}
                    disabled={isLaunching || isResetting}
                    className="w-full sm:w-auto px-5 py-3.5 bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 hover:text-white border border-emerald-500/40 rounded-xl font-bold flex items-center justify-center gap-2 transition-all shadow-lg shadow-emerald-950/40 disabled:opacity-50"
                    title="Scan video and immediately render all extracted viral shorts"
                  >
                    <PlayCircle className="h-4 w-4 text-emerald-400" />
                    <span>⚡ AUTO-PILOT (RENDER ALL)</span>
                  </button>

                  <button
                    onClick={() => handleStopAndReset(false)}
                    disabled={isResetting}
                    className="w-full sm:w-auto px-5 py-3.5 bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 hover:text-white border border-rose-500/40 rounded-xl font-bold flex items-center justify-center gap-2 transition-all shadow-lg shadow-rose-950/40 disabled:opacity-50"
                    title="Permanently delete all downloaded YouTube videos, clips, voiceovers, and jobs"
                  >
                    <Trash2 className="h-4 w-4 text-rose-400" />
                    <span>{isResetting ? 'WIPING...' : '🗑️ RESET ALL'}</span>
                  </button>
                </div>
              </div>

              {/* Real-time Progress & Stepper */}
              <div className="bg-[#141821] rounded-2xl border border-[#1F2430] p-6 space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Live Progress Stepper
                    </h3>
                    {(activeJobId || pipelineStep !== 'idle') && (
                      <button
                        onClick={() => handleStopAndReset(false)}
                        disabled={isResetting}
                        className="text-[11px] px-2.5 py-0.5 rounded-full bg-rose-500/20 text-rose-400 border border-rose-500/30 hover:bg-rose-500 hover:text-white transition-all font-semibold flex items-center gap-1.5 disabled:opacity-50"
                        title="Cancel job and delete all downloaded video files"
                      >
                        <Trash2 className="h-3 w-3" />
                        <span>{isResetting ? 'Wiping...' : 'Stop & Delete Downloads'}</span>
                      </button>
                    )}
                  </div>
                  {activeJobId && (
                    <span className="text-xs font-mono text-emerald-400 font-bold">
                      {progressPct}% • {progressMsg}
                    </span>
                  )}
                </div>

                {/* Progress Bar */}
                {activeJobId && (
                  <div className="w-full bg-[#0B0D12] h-2 rounded-full overflow-hidden border border-[#1F2430]">
                    <div
                      className="bg-gradient-to-r from-indigo-500 to-emerald-400 h-full transition-all duration-300"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                )}

                {/* 4 Steps */}
                <div className="grid grid-cols-4 gap-3 text-center pt-2">
                  <div className={`border rounded-xl p-3 transition-colors ${
                    pipelineStep === 'ingesting' || pipelineStep === 'analyzing' || pipelineStep === 'voicing' || pipelineStep === 'completed'
                      ? 'bg-emerald-950/20 border-emerald-500/40 text-emerald-400'
                      : 'bg-[#0B0D12] border-[#1F2430] text-slate-500'
                  }`}>
                    <div className="flex items-center justify-center mb-1">
                      <CheckCircle2 className="h-5 w-5" />
                    </div>
                    <p className="text-xs font-bold text-white">1. Ingest</p>
                    <p className="text-[10px] font-mono">yt-dlp + 480p</p>
                  </div>

                  <div className={`border rounded-xl p-3 transition-colors ${
                    pipelineStep === 'analyzing' || pipelineStep === 'voicing' || pipelineStep === 'completed'
                      ? 'bg-indigo-950/20 border-indigo-500/40 text-indigo-400'
                      : 'bg-[#0B0D12] border-[#1F2430] text-slate-500'
                  }`}>
                    <div className="flex items-center justify-center mb-1">
                      <Sparkles className="h-5 w-5" />
                    </div>
                    <p className="text-xs font-bold text-white">2. Gemini Vision</p>
                    <p className="text-[10px] font-mono">Multimodal Director</p>
                  </div>

                  <div className={`border rounded-xl p-3 transition-colors ${
                    pipelineStep === 'voicing' || pipelineStep === 'completed'
                      ? 'bg-emerald-950/20 border-emerald-500/40 text-emerald-400'
                      : 'bg-[#0B0D12] border-[#1F2430] text-slate-500'
                  }`}>
                    <div className="flex items-center justify-center mb-1">
                      <Volume2 className="h-5 w-5" />
                    </div>
                    <p className="text-xs font-bold text-white">3. TTS & Crops</p>
                    <p className="text-[10px] font-mono">Flash-TTS + Overlays</p>
                  </div>

                  <div className={`border rounded-xl p-3 transition-colors ${
                    pipelineStep === 'completed'
                      ? 'bg-indigo-950/20 border-indigo-500/40 text-indigo-400'
                      : 'bg-[#0B0D12] border-[#1F2430] text-slate-500'
                  }`}>
                    <div className="flex items-center justify-center mb-1">
                      <Video className="h-5 w-5" />
                    </div>
                    <p className="text-xs font-bold text-white">4. 9:16 Render</p>
                    <p className="text-[10px] font-mono">Hardware VideoToolbox</p>
                  </div>
                </div>

                {/* Real-time Activity Terminal / Console */}
                <div className="mt-4 pt-4 border-t border-[#1F2430]">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Terminal className="h-3.5 w-3.5 text-indigo-400" />
                      <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-300">
                        Live Engine Activity & Download Console
                      </span>
                      {pipelineStep !== 'idle' && (
                        <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-ping"></span>
                          <span>LIVE STREAMING</span>
                        </span>
                      )}
                    </div>
                    <button
                      onClick={() => setShowLogs(!showLogs)}
                      className="text-[11px] text-slate-400 hover:text-white flex items-center gap-1 font-mono transition-colors"
                    >
                      <span>{showLogs ? 'Hide Console' : 'Show Console'}</span>
                      {showLogs ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                    </button>
                  </div>

                  {showLogs && (
                    <div className="bg-[#0A0C10] border border-[#1A1F2B] rounded-xl p-3 font-mono text-[11px] space-y-1.5 max-h-52 overflow-y-auto shadow-inner">
                      {activityLogs.length === 0 ? (
                        <div className="flex items-center gap-2 text-slate-500 italic py-1">
                          <Activity className="h-3 w-3 text-slate-600 animate-pulse" />
                          <span>Console idle. Ready to stream live download speed, proxy generation, and render events.</span>
                        </div>
                      ) : (
                        activityLogs.map((log, idx) => (
                          <div key={idx} className="flex items-start gap-2 text-slate-300 leading-relaxed font-mono">
                            <span className="text-slate-500 shrink-0 select-none">[{log.timestamp}]</span>
                            <span className={
                              log.message.includes('Downloading')
                                ? 'text-cyan-300 font-semibold'
                                : log.message.includes('Encoding') || log.message.includes('480p')
                                ? 'text-amber-300'
                                : log.message.includes('Gemini') || log.message.includes('Vision')
                                ? 'text-indigo-300 font-semibold'
                                : log.message.includes('Demucs') || log.message.includes('audio')
                                ? 'text-emerald-300'
                                : log.message.includes('Hardware') || log.message.includes('M4') || log.message.includes('rendered')
                                ? 'text-emerald-400 font-bold'
                                : log.message.includes('stopped') || log.message.includes('Error')
                                ? 'text-rose-400'
                                : 'text-slate-300'
                            }>
                              {log.message}
                            </span>
                          </div>
                        ))
                      )}
                      <div ref={logsEndRef} />
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* VIEW 2: AI STUDIO (MANUAL REVIEW & REFINE WORKSPACE) */}
          {activeTab === 'studio' && (
            <div className="h-full flex gap-6 overflow-hidden">
              {/* Left Panel: Clip Selector Cards */}
              <div className="w-80 shrink-0 flex flex-col gap-3 overflow-y-auto pr-1">
                <div className="flex items-center justify-between pb-2 border-b border-[#1F2430]">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                    Viral Clips ({clips.length})
                  </h3>
                  <span className="text-[10px] text-indigo-400 font-mono">Gemini Scored</span>
                </div>

                {/* Segment Hopper: Next Chapter Action Banner */}
                {jobMetadata?.has_more_segments && (
                  <div className="bg-gradient-to-r from-amber-500/15 to-fuchsia-500/15 border border-amber-500/30 rounded-xl p-3 shadow-md mb-1">
                    <div className="flex items-center gap-2 mb-1.5">
                      <Sparkles className="h-3.5 w-3.5 text-amber-400 animate-pulse" />
                      <span className="text-[11px] font-bold text-white">Segment Finished</span>
                      <span className="text-[9px] bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded font-mono font-bold">NEXT READY</span>
                    </div>
                    <p className="text-[10px] text-slate-300 mb-2">
                      Next chapter starts at <span className="font-mono text-amber-400 font-bold">{jobMetadata.next_segment_start}</span>. Raw video is cached!
                    </p>
                    <button
                      onClick={() => {
                        setCutStartTime(jobMetadata.next_segment_start);
                        setActiveTab('new_project');
                        setTimeout(() => handleLaunch(), 100);
                      }}
                      disabled={isLaunching}
                      className="w-full bg-amber-500 hover:bg-amber-400 text-black py-1.5 px-3 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 shadow-sm"
                    >
                      <Zap className="h-3.5 w-3.5" />
                      Harvest Next Segment
                    </button>
                  </div>
                )}

                {clips.map((clip, idx) => (
                  <div
                    key={clip.clip_id}
                    onClick={() => setSelectedClipIndex(idx)}
                    className={`p-3.5 rounded-xl border cursor-pointer transition-all ${
                      selectedClipIndex === idx
                        ? 'bg-[#1E2433] border-indigo-500/60 shadow-lg shadow-indigo-500/10'
                        : 'bg-[#141821] border-[#1F2430] hover:border-slate-700'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1.5">
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-bold text-white uppercase tracking-tight">
                          Clip #{idx + 1} ({clip.duration}s)
                        </span>
                        {clip.beats && clip.beats.length > 1 ? (
                          <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30 font-bold">
                            🎬 {clip.beats.length} BEATS
                          </span>
                        ) : (
                          <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 font-bold">
                            ⚡ CLIMAX
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-1 bg-emerald-500/15 border border-emerald-500/30 px-2 py-0.5 rounded-full">
                        <TrendingUp className="h-3 w-3 text-emerald-400" />
                        <span className="text-[10px] font-bold text-emerald-400 font-mono">
                          {clip.reviewer_score || clip.virality_score}/100
                        </span>
                      </div>
                    </div>
                    <p className="text-xs font-medium text-indigo-300 line-clamp-1">{clip.hook_text}</p>
                    <p className="text-[11px] text-slate-400 line-clamp-2 mt-1">{clip.hook_summary}</p>
                  </div>
                ))}

                {clips.length === 0 && (
                  <div className="p-8 text-center text-slate-500 border border-dashed border-[#1F2430] rounded-xl">
                    <p className="text-xs">No clips analyzed yet.</p>
                    <button
                      onClick={() => setActiveTab('new_project')}
                      className="mt-3 text-xs text-indigo-400 underline font-medium"
                    >
                      Launch a project first
                    </button>
                  </div>
                )}
              </div>

              {/* Center Panel: Interactive 9:16 Video Player with Safe-Zone Guides */}
              <div className="flex-1 flex flex-col items-center justify-center bg-[#141821] rounded-2xl border border-[#1F2430] p-4 relative overflow-hidden">
                <div className="absolute top-4 left-4 z-10 flex items-center gap-2">
                  <button
                    onClick={() => setShowSafeZones(!showSafeZones)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                      showSafeZones
                        ? 'bg-indigo-600/20 border-indigo-500/50 text-indigo-300'
                        : 'bg-[#0B0D12] border-[#1F2430] text-slate-400'
                    }`}
                  >
                    <Eye className="h-3.5 w-3.5" />
                    <span>Safe Zones: {showSafeZones ? 'ON' : 'OFF'}</span>
                  </button>
                </div>

                {/* 9:16 Vertical Video Frame */}
                <div className="relative aspect-[9/16] h-[90%] max-h-[640px] rounded-2xl overflow-hidden bg-black border-2 border-[#1F2430] shadow-2xl flex items-center justify-center">
                  {activeClip?.preview_url ? (
                    <video
                      key={activeClip.preview_url}
                      src={activeClip.preview_url}
                      controls
                      autoPlay
                      loop
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="text-center p-6 text-slate-600">
                      <Video className="h-12 w-12 mx-auto mb-2 text-indigo-500/50" />
                      <p className="text-xs font-semibold text-slate-400">9:16 Vertical Canvas</p>
                      <p className="text-[10px] text-slate-500 font-mono mt-1">
                        {activeClip ? `Mode: ${activeClip.crop_mode.toUpperCase()}` : '1080 x 1920'}
                      </p>
                      {activeClip && (
                        <p className="text-[10px] text-indigo-400 font-semibold mt-2">
                          ⏳ Autonomous AI rendering in progress...
                        </p>
                      )}
                    </div>
                  )}

                  {/* Simulated Safe-Zone Guides (Shorts & Reels UI Buttons Overlay) */}
                  {showSafeZones && (
                    <div className="absolute inset-0 pointer-events-none select-none flex flex-col justify-between p-4">
                      {/* Top Bar */}
                      <div className="border border-dashed border-red-500/40 rounded bg-red-500/10 p-2 text-center">
                        <span className="text-[9px] font-mono text-red-300 font-bold uppercase tracking-wider">
                          ⚠️ Top Danger Zone (Search / Audio)
                        </span>
                      </div>

                      {/* Right Action Icons Simulated */}
                      <div className="self-end space-y-3 pr-2">
                        <div className="h-8 w-8 rounded-full bg-red-500/20 border border-red-500/40 flex items-center justify-center text-[9px] text-red-300">
                          Like
                        </div>
                        <div className="h-8 w-8 rounded-full bg-red-500/20 border border-red-500/40 flex items-center justify-center text-[9px] text-red-300">
                          Chat
                        </div>
                        <div className="h-8 w-8 rounded-full bg-red-500/20 border border-red-500/40 flex items-center justify-center text-[9px] text-red-300">
                          Share
                        </div>
                      </div>

                      {/* Bottom Description Zone */}
                      <div className="border border-dashed border-red-500/40 rounded bg-red-500/10 p-2 text-center">
                        <span className="text-[9px] font-mono text-red-300 font-bold uppercase tracking-wider">
                          ⚠️ Bottom Danger Zone (Channel & Captions)
                        </span>
                      </div>
                    </div>
                  )}

                  {/* Clean preview - callout box removed */}
                </div>
              </div>

              {/* Right Panel: AI Director Intelligence & Instant Export */}
              {activeClip && (
                <div className="w-96 shrink-0 bg-[#141821] rounded-2xl border border-[#1F2430] p-5 flex flex-col gap-4 overflow-y-auto shadow-xl">
                  <div className="flex items-center justify-between pb-3 border-b border-[#1F2430]">
                    <div>
                      <span className="text-[10px] font-mono uppercase tracking-wider text-indigo-400">Autonomous Cut</span>
                      <h3 className="text-sm font-bold text-white tracking-tight">
                        Clip #{selectedClipIndex + 1}: {activeClip.hook_text}
                      </h3>
                    </div>
                    <div className="flex items-center gap-1 bg-emerald-500/15 border border-emerald-500/30 px-2.5 py-1 rounded-full">
                      <TrendingUp className="h-3 w-3 text-emerald-400" />
                      <span className="text-xs font-bold text-emerald-400 font-mono">
                        {activeClip.virality_score}/100
                      </span>
                    </div>
                  </div>

                  {/* Senior Reviewer Quality Card */}
                  <div className="bg-[#0B0D12] rounded-xl p-3 border border-indigo-500/30 bg-gradient-to-r from-indigo-950/20 to-purple-950/20 space-y-2">
                    <div className="flex items-center justify-between text-xs font-semibold text-slate-300">
                      <div className="flex items-center gap-1.5">
                        <Sparkles className="h-3.5 w-3.5 text-amber-400" />
                        <span className="text-indigo-300 font-bold">Senior Reviewer & Quality Gate</span>
                      </div>
                      <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 font-bold">
                        ⭐ Rating: {activeClip.reviewer_score || activeClip.virality_score}/100
                      </span>
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed font-mono">
                      {activeClip.reviewer_verdict || activeClip.hook_summary}
                    </p>
                  </div>

                  {/* Story Beats Montage Breakdown */}
                  {activeClip.beats && activeClip.beats.length > 0 && (
                    <div className="bg-[#0B0D12] rounded-xl p-3 border border-purple-500/30 space-y-2">
                      <div className="flex items-center justify-between text-xs font-semibold text-slate-300">
                        <div className="flex items-center gap-1.5">
                          <Layers className="h-3.5 w-3.5 text-purple-400" />
                          <span className="text-white font-bold">Story Arc Montage ({activeClip.beats.length} Beats)</span>
                        </div>
                        <span className="text-[10px] text-purple-300 font-mono">
                          {activeClip.duration}s total
                        </span>
                      </div>
                      <div className="space-y-1.5 pt-1">
                        {activeClip.beats.map((beat, bIdx) => (
                          <div key={bIdx} className="bg-[#141821] border border-[#1F2430] rounded-lg p-2 flex items-center justify-between gap-2">
                            <div className="min-w-0">
                              <p className="text-xs font-semibold text-slate-200 truncate">{beat.label}</p>
                              {beat.description && (
                                <p className="text-[10px] text-slate-400 truncate">{beat.description}</p>
                              )}
                            </div>
                            <span className="text-[10px] font-mono text-cyan-300 bg-cyan-950/40 border border-cyan-800/40 px-1.5 py-0.5 rounded shrink-0">
                              {beat.duration}s
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* AI Virality Analysis */}
                  <div className="bg-[#0B0D12] rounded-xl p-3 border border-[#1F2430]">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-300 mb-1">
                      <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
                      <span>Gemini Viral Hook Analysis</span>
                    </div>
                    <p className="text-xs text-slate-400 leading-relaxed">
                      {activeClip.hook_summary}
                    </p>
                  </div>

                  {/* AI Generated Commentary */}
                  <div className="bg-[#0B0D12] rounded-xl p-3 border border-[#1F2430]">
                    <div className="flex items-center justify-between text-xs font-semibold text-slate-300 mb-1.5">
                      <div className="flex items-center gap-1.5">
                        <Volume2 className="h-3.5 w-3.5 text-cyan-400" />
                        <span>AI Voiceover Script</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-slate-500 font-mono">
                          Voice: {activeClip.tts_voice || 'Charon'}
                        </span>
                        <button
                          onClick={handleRegenerateVoiceAndRender}
                          disabled={isRevoicing}
                          className="text-[10px] bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 px-2 py-0.5 rounded border border-cyan-500/40 font-mono flex items-center gap-1 transition-colors"
                        >
                          {isRevoicing ? (
                            <>
                              <Loader2 className="h-2.5 w-2.5 animate-spin" />
                              Revoicing...
                            </>
                          ) : (
                            <>
                              <Sparkles className="h-2.5 w-2.5" />
                              Regen Voice
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                    <p className="text-xs text-slate-300 italic bg-[#141821] p-2.5 rounded-lg border border-[#1F2430]/60">
                      "{activeClip.commentary_script}"
                    </p>
                  </div>

                  {/* Automated Production Decisions */}
                  <div className="space-y-1.5">
                    <label className="block text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                      Autonomous Production Decisions
                    </label>
                    <div className="grid grid-cols-2 gap-2 text-[11px] font-mono">
                      <div className="bg-[#0B0D12] border border-[#1F2430] p-2 rounded-lg flex items-center gap-1.5 text-slate-300">
                        <Check className="h-3 w-3 text-emerald-400 shrink-0" />
                        <span className="truncate">9:16 {activeClip.crop_mode}</span>
                      </div>
                      <div className="bg-[#0B0D12] border border-[#1F2430] p-2 rounded-lg flex items-center gap-1.5 text-slate-300">
                        <Check className="h-3 w-3 text-emerald-400 shrink-0" />
                        <span className="truncate">60fps NVENC High</span>
                      </div>
                      <div className="bg-[#0B0D12] border border-[#1F2430] p-2 rounded-lg flex items-center gap-1.5 text-slate-300">
                        <Check className="h-3 w-3 text-emerald-400 shrink-0" />
                        <span className="truncate">Hormozi Captions</span>
                      </div>
                      <div className="bg-[#0B0D12] border border-[#1F2430] p-2 rounded-lg flex items-center gap-1.5 text-slate-300">
                        <Check className="h-3 w-3 text-emerald-400 shrink-0" />
                        <span className="truncate">-14 LUFS Audio</span>
                      </div>
                    </div>
                  </div>

                  {/* Quick Export & Actions */}
                  <div className="pt-2 space-y-2 mt-auto">
                    {activeClip.preview_url ? (
                      <a
                        href={activeJobId ? `/api/jobs/${activeJobId}/clips/${activeClip.clip_id}/download` : activeClip.preview_url}
                        download={`GTA6_${activeClip.clip_id}_Short.mp4`}
                        className="w-full bg-gradient-to-r from-emerald-500 to-teal-600 hover:opacity-95 text-white font-bold py-3 px-4 rounded-xl shadow-lg shadow-emerald-500/20 flex items-center justify-center gap-2 text-xs transition-all"
                      >
                        <Download className="h-4 w-4" />
                        <span>📥 Download 1080x1920 Short (MP4)</span>
                      </a>
                    ) : (
                      <button
                        onClick={handleRenderSelectedClip}
                        disabled={isRenderingClip}
                        className="w-full bg-gradient-to-r from-amber-500 via-orange-500 to-pink-500 hover:opacity-95 text-black font-extrabold py-3.5 px-4 rounded-xl shadow-lg shadow-amber-500/30 flex items-center justify-center gap-2 text-xs transition-all disabled:opacity-50"
                      >
                        {isRenderingClip ? (
                          <>
                            <Loader2 className="h-4 w-4 animate-spin text-black" />
                            <span>⚡ RENDERING 9:16 SHORT ({activeClip.duration}s)...</span>
                          </>
                        ) : (
                          <>
                            <Zap className="h-4 w-4 text-black" />
                            <span>⚡ RENDER THIS MISSION SHORT ({activeClip.duration}s)</span>
                          </>
                        )}
                      </button>
                    )}

                    <button
                      onClick={handleExportPack}
                      className="w-full bg-[#0B0D12] hover:bg-[#1A202C] border border-[#1F2430] text-slate-200 font-semibold py-2.5 px-4 rounded-xl flex items-center justify-center gap-2 text-xs transition-colors"
                    >
                      {copiedToast ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4 text-indigo-400" />}
                      <span>{copiedToast ? '✓ Copied Title & Hashtags!' : '📋 Copy YouTube Title & Description'}</span>
                    </button>

                    <button
                      onClick={() => setActiveTab('youtube')}
                      className="w-full bg-red-600/20 hover:bg-red-600/30 border border-red-500/40 text-red-300 font-bold py-2.5 px-4 rounded-xl flex items-center justify-center gap-2 text-xs transition-colors shadow-sm shadow-red-950/20"
                    >
                      <Youtube className="h-4 w-4 text-red-400" />
                      <span>🚀 Publish to YouTube Directly</span>
                    </button>

                    <button
                      onClick={() => setActiveTab('upload')}
                      className="w-full bg-indigo-600/15 hover:bg-indigo-600/25 border border-indigo-500/30 text-indigo-300 font-semibold py-2 px-4 rounded-xl flex items-center justify-center gap-2 text-xs transition-colors"
                    >
                      <Share2 className="h-3.5 w-3.5" />
                      <span>Open Multi-Platform Hub</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ─────────────────────────────────────────────────────────────
              VIEW: COMPARISON STUDIO (GTA 5/4 vs GTA 6)
          ───────────────────────────────────────────────────────────── */}
          {activeTab === 'comparison' && (
            <div className="max-w-7xl mx-auto space-y-6">
              {/* Top Hero Banner */}
              <div className="flex flex-col md:flex-row md:items-center justify-between bg-[#141821] border border-[#1F2430] rounded-2xl p-6 shadow-xl gap-4">
                <div className="flex items-center gap-4">
                  <div className="h-12 w-12 rounded-2xl bg-gradient-to-tr from-pink-600 to-cyan-400 p-0.5 shadow-lg shadow-pink-950/40 shrink-0">
                    <div className="w-full h-full bg-[#0E1117] rounded-[14px] flex items-center justify-center">
                      <Columns className="h-6 w-6 text-pink-400" />
                    </div>
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-lg font-bold text-white tracking-wide">GTA Comparison Studio</h2>
                      <span className="text-[10px] font-extrabold px-2 py-0.5 rounded bg-gradient-to-r from-pink-500 to-cyan-400 text-black font-mono">
                        VICE CITY VS ENGINE
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 mt-0.5">
                      Create viral comparison videos in 9:16 Shorts (Top/Bottom) or 16:9 Long (Side-by-Side) with neon gradient VS badges and Charon commentary.
                    </p>
                  </div>
                </div>

                {/* Format & Game Toggles */}
                <div className="flex flex-wrap items-center gap-3">
                  {/* Game Toggle */}
                  <div className="flex bg-[#0B0D12] p-1 rounded-xl border border-[#1F2430]">
                    <button
                      onClick={() => {
                        setCompBaseGame('gta5');
                        setCompHookText('GTA 5 VS GTA 6 • POLICE AI COMPARISON 🚨');
                      }}
                      className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                        compBaseGame === 'gta5'
                          ? 'bg-purple-600/30 text-purple-200 border border-purple-500/50 shadow-sm'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      GTA V vs GTA VI
                    </button>
                    <button
                      onClick={() => {
                        setCompBaseGame('gta4');
                        setCompHookText('GTA 4 VS GTA 6 • PHYSICS COMPARISON 🚨');
                      }}
                      className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                        compBaseGame === 'gta4'
                          ? 'bg-amber-600/30 text-amber-200 border border-amber-500/50 shadow-sm'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      GTA IV vs GTA VI
                    </button>
                  </div>

                  {/* Format Toggle */}
                  <div className="flex bg-[#0B0D12] p-1 rounded-xl border border-[#1F2430]">
                    <button
                      onClick={() => setCompFormat('shorts_split')}
                      className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all ${
                        compFormat === 'shorts_split'
                          ? 'bg-gradient-to-r from-pink-600/40 to-cyan-600/40 text-white border border-pink-500/50 shadow-sm'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      <Layers className="h-3.5 w-3.5 text-pink-400" />
                      <span>📱 9:16 Shorts (Top/Bottom)</span>
                    </button>
                    <button
                      onClick={() => setCompFormat('long_side_by_side')}
                      className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all ${
                        compFormat === 'long_side_by_side'
                          ? 'bg-gradient-to-r from-pink-600/40 to-cyan-600/40 text-white border border-pink-500/50 shadow-sm'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      <Columns className="h-3.5 w-3.5 text-cyan-400" />
                      <span>🖥️ 16:9 Long (Side-by-Side)</span>
                    </button>
                  </div>
                </div>
              </div>

              {/* Error Alert */}
              {compRenderError && (
                <div className="p-4 bg-rose-500/15 border border-rose-500/40 rounded-xl text-xs text-rose-300 flex items-start justify-between gap-3 shadow-lg shadow-rose-950/30">
                  <div className="flex items-start gap-2.5">
                    <AlertCircle className="h-4 w-4 text-rose-400 shrink-0 mt-0.5" />
                    <div>
                      <p className="font-bold text-white">Comparison Generation Note</p>
                      <p className="text-[11px] text-rose-300/90 font-mono mt-0.5">{compRenderError}</p>
                    </div>
                  </div>
                  <button onClick={() => setCompRenderError(null)} className="text-slate-400 hover:text-white">
                    <X className="h-4 w-4" />
                  </button>
                </div>
              )}

              {/* 3-Column Studio Grid */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
                {/* Column 1: GTA 6 YouTube Source */}
                <div className="bg-[#141821] rounded-2xl border border-[#1F2430] p-5 space-y-4 shadow-xl">
                  <div className="flex items-center justify-between pb-3 border-b border-[#1F2430]">
                    <div className="flex items-center gap-2">
                      <div className="h-2.5 w-2.5 rounded-full bg-pink-500 animate-pulse" />
                      <h3 className="text-sm font-bold text-white uppercase tracking-wider">1. GTA 6 Source (YouTube)</h3>
                    </div>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-pink-500/20 text-pink-300 border border-pink-500/30 font-bold">
                      VICE CITY
                    </span>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                      GTA 6 YouTube URL (Trailer, Leak, or Comparison)
                    </label>
                    <input
                      type="text"
                      value={compGta6Url}
                      onChange={(e) => setCompGta6Url(e.target.value)}
                      placeholder="https://youtu.be/..."
                      className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-pink-500 font-mono"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-[11px] font-semibold text-slate-400 mb-1">
                        Start Timestamp
                      </label>
                      <input
                        type="text"
                        value={compGta6StartTime}
                        onChange={(e) => setCompGta6StartTime(e.target.value)}
                        placeholder="00:00:40"
                        className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-3 py-2 text-xs text-white font-mono"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] font-semibold text-slate-400 mb-1">
                        Duration (Sec)
                      </label>
                      <input
                        type="number"
                        value={compGta6Duration}
                        onChange={(e) => setCompGta6Duration(Number(e.target.value))}
                        min={5}
                        max={60}
                        className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-3 py-2 text-xs text-white font-mono"
                      />
                    </div>
                  </div>

                  <button
                    onClick={handleGenerateQuest}
                    disabled={isGeneratingQuest || !compGta6Url}
                    className="w-full bg-gradient-to-r from-pink-600 to-indigo-600 hover:opacity-95 text-white font-bold py-2.5 px-4 rounded-xl shadow-lg shadow-pink-950/40 flex items-center justify-center gap-2 text-xs transition-all disabled:opacity-50"
                  >
                    {isGeneratingQuest ? (
                      <>
                        <span className="h-3 w-3 rounded-full bg-white animate-spin" />
                        <span>Gemini Vision Scanning GTA 6...</span>
                      </>
                    ) : (
                      <>
                        <Sparkles className="h-4 w-4 text-cyan-300" />
                        <span>🔍 Scan GTA 6 & Get {compBaseGame.toUpperCase()} Quest</span>
                      </>
                    )}
                  </button>

                  <p className="text-[10px] text-slate-500 italic">
                    Tip: If using comparison videos like ENXGMA, set GTA 6 start time to the 2nd half of the chapter (e.g. 00:00:40) and GTA 5 to the 1st half (e.g. 00:00:10).
                  </p>
                </div>

                {/* Column 2: Gameplay Match Mission & Base Game Source */}
                <div className="bg-[#141821] rounded-2xl border border-[#1F2430] p-5 space-y-4 shadow-xl">
                  <div className="flex items-center justify-between pb-3 border-b border-[#1F2430]">
                    <div className="flex items-center gap-2">
                      <div className="h-2.5 w-2.5 rounded-full bg-purple-500 animate-pulse" />
                      <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                        2. {compBaseGame === 'gta5' ? 'GTA V' : 'GTA IV'} Match Quest
                      </h3>
                    </div>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30 font-bold">
                      {compBaseGame === 'gta5' ? 'LOS SANTOS' : 'LIBERTY CITY'}
                    </span>
                  </div>

                  {/* AI Mission Card Display */}
                  {compQuest ? (
                    <div className="bg-[#0B0D12] border border-cyan-500/30 rounded-xl p-3.5 space-y-2.5 shadow-sm">
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-mono text-cyan-400 uppercase font-bold tracking-wider">
                          🎯 Mission Objective
                        </span>
                        <span className="text-[10px] font-mono text-emerald-400 bg-emerald-500/20 px-1.5 py-0.5 rounded">
                          15s RECORDING
                        </span>
                      </div>
                      <h4 className="text-xs font-bold text-white">{compQuest.test_title}</h4>
                      <div className="text-[11px] text-slate-300 space-y-1 bg-[#141821] p-2 rounded-lg border border-[#1F2430]">
                        <p className="text-amber-400 font-semibold">📍 Location: {compQuest.location}</p>
                        <div className="space-y-0.5 pt-1">
                          {(compQuest.gta5_steps || []).map((step: string, idx: number) => (
                            <p key={idx} className="text-slate-300">• {step}</p>
                          ))}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="bg-[#0B0D12] border border-dashed border-[#1F2430] rounded-xl p-3.5 text-center text-xs text-slate-400 space-y-1">
                      <Bot className="h-5 w-5 text-indigo-400 mx-auto mb-1" />
                      <p className="font-semibold text-slate-300">No Quest Generated Yet</p>
                      <p className="text-[10px] text-slate-500">
                        Click "Scan GTA 6" to let Gemini detect the exact mechanic and give you a 15-second recording checklist.
                      </p>
                    </div>
                  )}

                  {/* Option A: Upload Local Recording */}
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">
                      Option A: Drop Your 15s {compBaseGame.toUpperCase()} Recording
                    </label>
                    <label className="flex flex-col items-center justify-center p-3.5 border-2 border-dashed border-[#1F2430] hover:border-purple-500/60 rounded-xl cursor-pointer bg-[#0B0D12] transition-colors">
                      {isUploadingRec ? (
                        <Loader2 className="h-5 w-5 text-purple-400 mb-1 animate-spin" />
                      ) : (
                        <UploadCloud className="h-5 w-5 text-purple-400 mb-1" />
                      )}
                      <span className="text-xs font-semibold text-slate-300">
                        {isUploadingRec
                          ? 'Uploading recording...'
                          : compUploadedName
                          ? `✓ ${compUploadedName}`
                          : 'Upload local MP4 clip'}
                      </span>
                      <span className="text-[10px] text-slate-500">
                        {compUploadedPath ? `Loaded: ${compUploadedPath}` : 'OBS, GeForce Experience, or screen recording'}
                      </span>
                      <input
                        type="file"
                        accept="video/mp4,video/quicktime,video/webm"
                        onChange={handleUploadRecording}
                        disabled={isUploadingRec}
                        className="hidden"
                      />
                    </label>
                  </div>

                  {/* Option B: YouTube URL */}
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">
                      Option B: Or {compBaseGame.toUpperCase()} YouTube URL
                    </label>
                    <input
                      type="text"
                      value={compBaseUrl}
                      onChange={(e) => setCompBaseUrl(e.target.value)}
                      placeholder="https://youtu.be/..."
                      className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-purple-500 font-mono"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-[11px] font-semibold text-slate-400 mb-1">
                        Start Timestamp
                      </label>
                      <input
                        type="text"
                        value={compBaseStartTime}
                        onChange={(e) => setCompBaseStartTime(e.target.value)}
                        placeholder="00:00:10"
                        className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-3 py-2 text-xs text-white font-mono"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] font-semibold text-slate-400 mb-1">
                        Duration (Sec)
                      </label>
                      <input
                        type="number"
                        value={compBaseDuration}
                        onChange={(e) => setCompBaseDuration(Number(e.target.value))}
                        min={5}
                        max={60}
                        className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-3 py-2 text-xs text-white font-mono"
                      />
                    </div>
                  </div>
                </div>

                {/* Column 3: Narration & Final 1-Click Compositor */}
                <div className="bg-[#141821] rounded-2xl border border-[#1F2430] p-5 space-y-4 shadow-xl flex flex-col justify-between">
                  <div>
                    <div className="flex items-center justify-between pb-3 border-b border-[#1F2430] mb-3">
                      <div className="flex items-center gap-2">
                        <Volume2 className="h-4 w-4 text-cyan-400" />
                        <h3 className="text-sm font-bold text-white uppercase tracking-wider">3. Comparison Narration</h3>
                      </div>
                      <select
                        value={compTtsVoice}
                        onChange={(e) => setCompTtsVoice(e.target.value)}
                        className="bg-[#0B0D12] text-cyan-300 border border-[#1F2430] rounded px-2 py-0.5 text-[10px] font-mono focus:outline-none cursor-pointer"
                      >
                        <option value="Charon">🎙️ Charon (Lore)</option>
                        <option value="Aoede">✨ Aoede (Female)</option>
                        <option value="Kore">🌿 Kore (Calm)</option>
                        <option value="Fenrir">⚡ Fenrir (Deep)</option>
                        <option value="Puck">🔥 Puck (Fast)</option>
                      </select>
                    </div>

                    <div className="space-y-3">
                      <div>
                        <label className="block text-[11px] font-semibold text-slate-300 mb-1">
                          Topic Headline (Top Banner)
                        </label>
                        <input
                          type="text"
                          value={compHookText}
                          onChange={(e) => setCompHookText(e.target.value)}
                          className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-3 py-2 text-xs text-white font-bold focus:outline-none focus:border-cyan-500"
                        />
                      </div>

                      <div>
                        <label className="block text-[11px] font-semibold text-slate-300 mb-1">
                          Charon Documentary Comparison Script
                        </label>
                        <textarea
                          rows={4}
                          value={compCommentaryScript}
                          onChange={(e) => setCompCommentaryScript(e.target.value)}
                          className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl p-2.5 text-xs text-slate-200 leading-relaxed focus:outline-none focus:border-cyan-500 resize-none font-sans"
                        />
                      </div>
                    </div>
                  </div>

                  <div className="pt-3">
                    <button
                      onClick={handleRenderComparison}
                      disabled={isRenderingComp || !compGta6Url || !compBaseUrl}
                      className="w-full bg-gradient-to-r from-pink-500 via-purple-600 to-cyan-500 hover:opacity-95 text-white font-extrabold py-3 px-4 rounded-xl shadow-lg shadow-pink-950/40 flex items-center justify-center gap-2 text-xs transition-all tracking-wide disabled:opacity-50"
                    >
                      {isRenderingComp ? (
                        <>
                          <span className="h-3.5 w-3.5 rounded-full bg-white animate-spin" />
                          <span>Rendering {compFormat === 'shorts_split' ? '9:16 Short' : '16:9 Long'} with VS Badge...</span>
                        </>
                      ) : (
                        <>
                          <Zap className="h-4 w-4 text-amber-300" />
                          <span>⚡ Render {compFormat === 'shorts_split' ? '9:16 Short' : '16:9 Long'} (Vice City VS)</span>
                        </>
                      )}
                    </button>
                  </div>
                </div>
              </div>

              {/* Live Preview Player & Download Section (Shows when rendered) */}
              {compRenderResult && (
                <div className="bg-[#141821] border border-emerald-500/40 rounded-2xl p-6 shadow-2xl space-y-4">
                  <div className="flex items-center justify-between pb-3 border-b border-[#1F2430]">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                      <div>
                        <h3 className="text-sm font-bold text-white">Comparison Video Rendered Successfully!</h3>
                        <p className="text-[11px] text-slate-400">
                          Format: {compRenderResult.format === 'shorts_split' ? '9:16 Vertical Short' : '16:9 Landscape Video'} • 1080p 60fps
                        </p>
                      </div>
                    </div>
                    <a
                      href={compRenderResult.preview_url}
                      download={`GTA_${compBaseGame.toUpperCase()}_vs_GTA6_${compRenderResult.comp_id}.mp4`}
                      className="bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-2 px-4 rounded-xl flex items-center gap-2 text-xs transition-all shadow-md shadow-emerald-950/40"
                    >
                      <Download className="h-4 w-4" />
                      <span>Download Video (MP4)</span>
                    </a>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-center">
                    <div className="flex justify-center bg-[#0B0D12] rounded-xl p-4 border border-[#1F2430]">
                      <video
                        src={compRenderResult.preview_url}
                        controls
                        className={`rounded-lg shadow-xl max-h-[480px] ${
                          compRenderResult.format === 'shorts_split' ? 'w-auto aspect-[9/16]' : 'w-full aspect-video'
                        }`}
                      />
                    </div>

                    <div className="space-y-3 text-xs">
                      <div className="bg-[#0B0D12] p-3.5 rounded-xl border border-[#1F2430] space-y-1">
                        <span className="text-[10px] font-mono text-cyan-400 uppercase font-bold">Suggested YouTube Title</span>
                        <p className="text-white font-semibold">{compRenderResult.social_metadata?.youtube?.title}</p>
                      </div>

                      <div className="bg-[#0B0D12] p-3.5 rounded-xl border border-[#1F2430] space-y-1">
                        <span className="text-[10px] font-mono text-purple-400 uppercase font-bold">Tags & Hashtags</span>
                        <p className="text-slate-300 font-mono text-[11px]">
                          {(compRenderResult.social_metadata?.youtube?.tags || []).join(' ')}
                        </p>
                      </div>

                      <div className="flex gap-3 pt-2">
                        <button
                          onClick={() => {
                            const copyTxt = `${compRenderResult.social_metadata?.youtube?.title}\n\n${compRenderResult.commentary_script}\n\n${(compRenderResult.social_metadata?.youtube?.tags || []).join(' ')}`;
                            navigator.clipboard.writeText(copyTxt);
                            alert('Copied formatted YouTube/Reels metadata to clipboard!');
                          }}
                          className="flex-1 bg-indigo-600/30 hover:bg-indigo-600/50 border border-indigo-500/40 text-indigo-200 py-2.5 px-4 rounded-xl font-bold flex items-center justify-center gap-2 transition-all"
                        >
                          <Copy className="h-4 w-4" />
                          <span>Copy Social Metadata</span>
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* VIEW: DEDICATED YOUTUBE DIRECT PUBLISHING HUB */}
          {activeTab === 'youtube' && (
            <div className="max-w-6xl mx-auto space-y-6">
              {/* Top Banner */}
              <div className="flex flex-col md:flex-row md:items-center justify-between bg-[#141821] border border-[#1F2430] rounded-2xl p-6 shadow-xl gap-4">
                <div className="flex items-center gap-4">
                  <div className="h-12 w-12 rounded-2xl bg-red-600/20 border border-red-500/40 flex items-center justify-center text-red-500 shadow-lg shadow-red-950/40 shrink-0">
                    <Youtube className="h-6 w-6" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-xl font-bold text-white tracking-tight">YouTube Shorts Direct Publisher</h2>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-red-600/30 text-red-300 font-bold border border-red-500/40">
                        DIRECT API
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 mt-1">
                      Directly upload your vertical 1080x1920 60fps Shorts to YouTube with auto-generated viral titles, descriptions, and schedule times.
                    </p>
                  </div>
                </div>

                <div className="flex items-center flex-wrap gap-3 shrink-0">
                  {ytAuthStatus?.has_token ? (
                    <div className="flex items-center gap-3 px-3.5 py-2 rounded-2xl bg-[#0B0D12] border border-emerald-500/40 shadow-lg shadow-emerald-950/20">
                      {ytAuthStatus.channel_avatar ? (
                        <img
                          src={ytAuthStatus.channel_avatar}
                          alt={ytAuthStatus.channel_title || 'YouTube Channel'}
                          className="h-10 w-10 rounded-full border-2 border-emerald-400 object-cover shadow-sm shrink-0"
                        />
                      ) : (
                        <div className="h-10 w-10 rounded-full bg-red-600 flex items-center justify-center text-white font-bold text-xs shrink-0">
                          <Youtube className="h-5 w-5" />
                        </div>
                      )}
                      <div className="flex flex-col">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-bold text-white max-w-[160px] truncate">
                            {ytAuthStatus.channel_title || 'Connected Channel'}
                          </span>
                          <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse shrink-0" title="Connected" />
                        </div>
                        <span className="text-[10px] text-slate-400 font-mono">
                          {ytAuthStatus.channel_handle || 'Direct 1-Click Publishing Active'}
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5 ml-1 border-l border-[#1F2430] pl-2">
                        <button
                          onClick={() => setShowYtAuthModal(true)}
                          className="p-1.5 rounded-lg bg-[#141821] hover:bg-[#1E2433] text-slate-400 hover:text-white transition-colors"
                          title="Manage OAuth & Channel"
                        >
                          <SettingsIcon className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={handleDisconnectYouTube}
                          className="text-[10px] text-rose-400 hover:text-rose-300 font-medium px-1 hover:underline"
                          title="Disconnect Channel"
                        >
                          Disconnect
                        </button>
                      </div>
                    </div>
                  ) : ytAuthStatus?.has_client_secret ? (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={handleConnectYouTube}
                        disabled={ytConnecting}
                        className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-red-600 via-rose-600 to-red-700 hover:from-red-500 hover:to-rose-500 text-white text-xs font-bold shadow-lg shadow-red-950/40 transition-all disabled:opacity-50"
                      >
                        <Youtube className={`h-4 w-4 ${ytConnecting ? 'animate-spin' : ''}`} />
                        <span>{ytConnecting ? 'Opening Google Auth in Browser...' : '🔴 Connect YouTube Channel'}</span>
                      </button>
                      <button
                        onClick={() => setShowYtAuthModal(true)}
                        className="p-2.5 rounded-xl bg-[#0B0D12] border border-[#1F2430] hover:border-slate-600 text-slate-300 hover:text-white text-xs transition-all"
                        title="OAuth Secret Settings"
                      >
                        <SettingsIcon className="h-3.5 w-3.5 text-slate-400" />
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setShowYtAuthModal(true)}
                      className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-[#0B0D12] border border-[#1F2430] hover:border-slate-600 text-slate-300 hover:text-white text-xs font-semibold transition-all"
                    >
                      <SettingsIcon className="h-3.5 w-3.5 text-slate-400" />
                      <span>⚙️ Setup OAuth Secret</span>
                    </button>
                  )}

                  <button
                    onClick={handleOpenStudioUploader}
                    className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[#1A1F2C] hover:bg-[#252C3D] border border-indigo-500/30 text-indigo-300 font-bold text-xs transition-all shadow-md"
                    title="Copies all metadata and opens studio.youtube.com upload page"
                  >
                    <ExternalLink className="h-3.5 w-3.5 text-indigo-400" />
                    <span>{copiedToast ? '✓ Copied & Opened!' : 'Open in YouTube Studio'}</span>
                  </button>
                </div>
              </div>

              {/* Horizontal Clip Selector Bar */}
              {clips.length > 0 && (
                <div className="bg-[#141821] border border-[#1F2430] rounded-2xl p-4 shadow-md">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <PlayCircle className="h-4 w-4 text-red-400" />
                      <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                        Select Clip to Publish ({clips.length} ready)
                      </span>
                    </div>
                    <span className="text-[11px] text-slate-400 font-mono">
                      Selected: Clip #{selectedClipIndex + 1} ({activeClip?.duration || 0}s)
                    </span>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
                    {clips.map((c, idx) => (
                      <div
                        key={c.clip_id}
                        onClick={() => setSelectedClipIndex(idx)}
                        className={`p-3 rounded-xl border cursor-pointer transition-all ${
                          selectedClipIndex === idx
                            ? 'bg-red-600/15 border-red-500/60 shadow-lg shadow-red-950/30 ring-1 ring-red-500/40'
                            : 'bg-[#0B0D12] border-[#1F2430] hover:border-slate-700'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-bold text-white uppercase">Clip #{idx + 1}</span>
                          <span className="text-[10px] font-mono text-emerald-400 font-bold">{c.virality_score}/100</span>
                        </div>
                        <p className="text-[11px] font-medium text-slate-300 line-clamp-1">{c.hook_text}</p>
                        <div className="flex items-center justify-between mt-2 pt-1 border-t border-[#1F2430]/60 text-[9px] text-slate-400 font-mono">
                          <span>{c.duration}s</span>
                          <span className={c.preview_url ? 'text-emerald-400 font-bold' : 'text-amber-400'}>
                            {c.preview_url ? '✓ Ready' : '⏳ Rendering'}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Main 2-Column Publishing Studio */}
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
                {/* Left Column: 9:16 Video Player Card (5 cols) */}
                <div className="lg:col-span-5 bg-[#141821] rounded-2xl border border-[#1F2430] p-5 shadow-xl flex flex-col items-center justify-between space-y-4">
                  <div className="w-full flex items-center justify-between pb-3 border-b border-[#1F2430]">
                    <span className="text-xs font-bold text-white uppercase tracking-wider">Shorts Video Preview</span>
                    <span className="text-[10px] font-mono text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/30 font-bold">
                      1080x1920 60FPS NVENC
                    </span>
                  </div>

                  {/* 9:16 Vertical Video Frame */}
                  <div className="relative aspect-[9/16] w-full max-w-[280px] rounded-2xl overflow-hidden bg-black border-2 border-[#1F2430] shadow-2xl flex items-center justify-center">
                    {activeClip?.preview_url ? (
                      <video
                        key={activeClip.preview_url}
                        src={activeClip.preview_url}
                        controls
                        autoPlay
                        loop
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <div className="text-center p-6 text-slate-600">
                        <Video className="h-10 w-10 mx-auto mb-2 text-red-500/50" />
                        <p className="text-xs font-semibold text-slate-400">Rendering Clip...</p>
                        <p className="text-[10px] text-slate-500 mt-1">Autonomous hardware encoder active</p>
                      </div>
                    )}
                  </div>

                  {/* Video Specs & Local Download */}
                  <div className="w-full space-y-2 pt-2 border-t border-[#1F2430]">
                    <div className="grid grid-cols-2 gap-2 text-[11px] font-mono text-slate-400">
                      <div className="bg-[#0B0D12] p-2 rounded-lg border border-[#1F2430]">
                        <span className="text-slate-500 block text-[9px] uppercase">Format</span>
                        <span className="text-white font-bold">MP4 (mp42)</span>
                      </div>
                      <div className="bg-[#0B0D12] p-2 rounded-lg border border-[#1F2430]">
                        <span className="text-slate-500 block text-[9px] uppercase">Audio</span>
                        <span className="text-white font-bold">AAC Stereo -14 LUFS</span>
                      </div>
                    </div>

                    {activeClip?.preview_url && (
                      <a
                        href={activeJobId ? `/api/jobs/${activeJobId}/clips/${activeClip.clip_id}/download` : activeClip.preview_url}
                        download={`GTA6_${activeClip.clip_id}_Short.mp4`}
                        className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl bg-[#0B0D12] hover:bg-[#191F2C] border border-[#1F2430] text-slate-300 hover:text-white font-semibold text-xs transition-colors"
                      >
                        <Download className="h-3.5 w-3.5 text-emerald-400" />
                        <span>Download MP4 for Backup</span>
                      </a>
                    )}
                  </div>
                </div>

                {/* Right Column: Detailed YouTube Metadata & Upload Form (7 cols) */}
                <div className="lg:col-span-7 bg-[#141821] rounded-2xl border border-[#1F2430] p-6 shadow-xl space-y-5">
                  {/* Results Banner (if uploaded) */}
                  {ytPublishResult && (
                    <div className="bg-emerald-500/15 border border-emerald-500/40 rounded-xl p-4 shadow-lg flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <CheckCircle2 className="h-6 w-6 text-emerald-400 shrink-0" />
                        <div>
                          <h4 className="text-xs font-bold text-white">Successfully Uploaded to YouTube Shorts!</h4>
                          <p className="text-[11px] text-emerald-300 font-mono mt-0.5">{ytPublishResult.url}</p>
                        </div>
                      </div>
                      <a
                        href={ytPublishResult.url}
                        target="_blank"
                        rel="noreferrer"
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500 text-black text-xs font-bold hover:bg-emerald-400 transition-colors"
                      >
                        <span>Watch Short</span>
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    </div>
                  )}

                  {/* Error Banner */}
                  {ytPublishError && (
                    <div className="bg-rose-500/15 border border-rose-500/40 rounded-xl p-4 shadow-lg flex items-start gap-3">
                      <AlertCircle className="h-5 w-5 text-rose-400 shrink-0 mt-0.5" />
                      <div className="flex-1">
                        <h4 className="text-xs font-bold text-white">Upload Error</h4>
                        <p className="text-[11px] text-rose-300 mt-0.5 leading-relaxed">{ytPublishError}</p>
                        {ytPublishError.includes('credentials') || ytPublishError.includes('OAuth') || ytPublishError.includes('client_secret') ? (
                          <button
                            onClick={() => setShowYtAuthModal(true)}
                            className="mt-2 text-xs text-indigo-400 underline font-semibold"
                          >
                            Click here to configure client_secret.json
                          </button>
                        ) : null}
                      </div>
                    </div>
                  )}

                  {/* 1. Title Input */}
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                        <span>Shorts Title</span>
                        <span className="text-red-400">*</span>
                      </label>
                      <div className="flex items-center gap-2">
                        <span className={`text-[11px] font-mono ${ytTitle.length > 90 ? 'text-amber-400' : 'text-slate-400'}`}>
                          {ytTitle.length}/100
                        </span>
                        <button
                          onClick={() => {
                            if (activeClip) {
                              setYtTitle(activeClip.social_metadata?.youtube.title || `${activeClip.hook_text} #Shorts`);
                            }
                          }}
                          className="text-[10px] text-indigo-400 hover:text-indigo-300 underline font-mono"
                        >
                          Reset AI Title
                        </button>
                      </div>
                    </div>
                    <input
                      type="text"
                      maxLength={100}
                      value={ytTitle}
                      onChange={(e) => setYtTitle(e.target.value)}
                      placeholder="Catchy viral hook title with #Shorts"
                      className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-4 py-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-red-500 font-semibold transition-colors"
                    />
                    <p className="text-[10px] text-slate-500 mt-1">
                      💡 Tip: Keep #Shorts in your title to guarantee algorithmic vertical Shorts indexing.
                    </p>
                  </div>

                  {/* 2. Description Textarea */}
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="text-xs font-bold uppercase tracking-wider text-slate-300">
                        Description & Hashtags
                      </label>
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] font-mono text-slate-400">{ytDescription.length}/5000</span>
                        <button
                          onClick={() => {
                            if (activeClip) {
                              setYtDescription(activeClip.social_metadata?.youtube.description || `${activeClip.hook_summary}\n\n#GTA6 #GrandTheftAuto #Gaming #Shorts #Viral`);
                            }
                          }}
                          className="text-[10px] text-indigo-400 hover:text-indigo-300 underline font-mono"
                        >
                          Reset AI Description
                        </button>
                      </div>
                    </div>
                    <textarea
                      rows={5}
                      maxLength={5000}
                      value={ytDescription}
                      onChange={(e) => setYtDescription(e.target.value)}
                      placeholder="Detailed description and hashtags for YouTube SEO..."
                      className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl p-3 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-red-500 resize-none font-sans leading-relaxed"
                    />
                  </div>

                  {/* 3. Tags Badges */}
                  <div>
                    <label className="block text-xs font-bold uppercase tracking-wider text-slate-300 mb-1.5">
                      SEO Tags ({ytTags.length})
                    </label>
                    <div className="flex flex-wrap gap-1.5 p-2 bg-[#0B0D12] border border-[#1F2430] rounded-xl min-h-[42px] items-center">
                      {ytTags.map((tag, tIdx) => (
                        <span
                          key={tIdx}
                          className="flex items-center gap-1 bg-[#1A202C] border border-[#2D3748] text-slate-300 px-2 py-0.5 rounded-lg text-xs font-mono"
                        >
                          <span>#{tag.replace(/^#/, '')}</span>
                          <button
                            type="button"
                            onClick={() => setYtTags(ytTags.filter((_, i) => i !== tIdx))}
                            className="hover:text-rose-400"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </span>
                      ))}
                      <div className="flex items-center gap-1 pl-1">
                        <input
                          type="text"
                          value={ytTagInput}
                          onChange={(e) => setYtTagInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && ytTagInput.trim()) {
                              e.preventDefault();
                              const clean = ytTagInput.trim().replace(/^#/, '');
                              if (!ytTags.includes(clean)) {
                                setYtTags([...ytTags, clean]);
                              }
                              setYtTagInput('');
                            }
                          }}
                          placeholder="+ Add tag (Enter)"
                          className="bg-transparent text-xs text-white placeholder-slate-600 focus:outline-none w-28 font-mono"
                        />
                      </div>
                    </div>
                  </div>

                  {/* 4. Privacy & Scheduling Selector */}
                  <div className="space-y-3 pt-2 border-t border-[#1F2430]">
                    <label className="block text-xs font-bold uppercase tracking-wider text-slate-300">
                      Visibility & Publishing Schedule
                    </label>

                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
                      {/* Public */}
                      <button
                        type="button"
                        onClick={() => setYtPrivacy('public')}
                        className={`p-3 rounded-xl border text-left flex flex-col justify-between transition-all ${
                          ytPrivacy === 'public'
                            ? 'bg-emerald-600/15 border-emerald-500 text-white shadow-md shadow-emerald-950/30 ring-1 ring-emerald-500/40'
                            : 'bg-[#0B0D12] border-[#1F2430] text-slate-400 hover:text-white'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <Globe className={`h-4 w-4 ${ytPrivacy === 'public' ? 'text-emerald-400' : 'text-slate-500'}`} />
                          <span className={`h-2 w-2 rounded-full ${ytPrivacy === 'public' ? 'bg-emerald-400' : 'bg-slate-600'}`} />
                        </div>
                        <div>
                          <span className="text-xs font-bold block">Public</span>
                          <span className="text-[10px] text-slate-400">Instant release</span>
                        </div>
                      </button>

                      {/* Unlisted */}
                      <button
                        type="button"
                        onClick={() => setYtPrivacy('unlisted')}
                        className={`p-3 rounded-xl border text-left flex flex-col justify-between transition-all ${
                          ytPrivacy === 'unlisted'
                            ? 'bg-amber-600/15 border-amber-500 text-white shadow-md shadow-amber-950/30 ring-1 ring-amber-500/40'
                            : 'bg-[#0B0D12] border-[#1F2430] text-slate-400 hover:text-white'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <EyeOff className={`h-4 w-4 ${ytPrivacy === 'unlisted' ? 'text-amber-400' : 'text-slate-500'}`} />
                          <span className={`h-2 w-2 rounded-full ${ytPrivacy === 'unlisted' ? 'bg-amber-400' : 'bg-slate-600'}`} />
                        </div>
                        <div>
                          <span className="text-xs font-bold block">Unlisted</span>
                          <span className="text-[10px] text-slate-400">Link-only access</span>
                        </div>
                      </button>

                      {/* Private */}
                      <button
                        type="button"
                        onClick={() => setYtPrivacy('private')}
                        className={`p-3 rounded-xl border text-left flex flex-col justify-between transition-all ${
                          ytPrivacy === 'private'
                            ? 'bg-indigo-600/15 border-indigo-500 text-white shadow-md shadow-indigo-950/30 ring-1 ring-indigo-500/40'
                            : 'bg-[#0B0D12] border-[#1F2430] text-slate-400 hover:text-white'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <Lock className={`h-4 w-4 ${ytPrivacy === 'private' ? 'text-indigo-400' : 'text-slate-500'}`} />
                          <span className={`h-2 w-2 rounded-full ${ytPrivacy === 'private' ? 'bg-indigo-400' : 'bg-slate-600'}`} />
                        </div>
                        <div>
                          <span className="text-xs font-bold block">Private</span>
                          <span className="text-[10px] text-slate-400">Only you</span>
                        </div>
                      </button>

                      {/* Schedule */}
                      <button
                        type="button"
                        onClick={() => setYtPrivacy('scheduled')}
                        className={`p-3 rounded-xl border text-left flex flex-col justify-between transition-all ${
                          ytPrivacy === 'scheduled'
                            ? 'bg-fuchsia-600/15 border-fuchsia-500 text-white shadow-md shadow-fuchsia-950/30 ring-1 ring-fuchsia-500/40'
                            : 'bg-[#0B0D12] border-[#1F2430] text-slate-400 hover:text-white'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <Calendar className={`h-4 w-4 ${ytPrivacy === 'scheduled' ? 'text-fuchsia-400' : 'text-slate-500'}`} />
                          <span className={`h-2 w-2 rounded-full ${ytPrivacy === 'scheduled' ? 'bg-fuchsia-400' : 'bg-slate-600'}`} />
                        </div>
                        <div>
                          <span className="text-xs font-bold block">Schedule</span>
                          <span className="text-[10px] text-slate-400">Set future date</span>
                        </div>
                      </button>
                    </div>

                    {/* Schedule Date & Time Picker */}
                    {ytPrivacy === 'scheduled' && (
                      <div className="bg-[#0B0D12] border border-fuchsia-500/40 rounded-xl p-4 shadow-inner space-y-3">
                        <div className="flex items-center gap-2 text-fuchsia-300 text-xs font-bold">
                          <Calendar className="h-4 w-4" />
                          <span>Choose Scheduled Premiere Time (YouTube Shorts)</span>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <div>
                            <label className="block text-[10px] font-mono text-slate-400 mb-1 uppercase">
                              Publish Date
                            </label>
                            <input
                              type="date"
                              value={ytScheduleDate}
                              onChange={(e) => setYtScheduleDate(e.target.value)}
                              className="w-full bg-[#141821] border border-[#1F2430] rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-fuchsia-500 font-mono"
                            />
                          </div>
                          <div>
                            <label className="block text-[10px] font-mono text-slate-400 mb-1 uppercase">
                              Publish Time
                            </label>
                            <input
                              type="time"
                              value={ytScheduleTime}
                              onChange={(e) => setYtScheduleTime(e.target.value)}
                              className="w-full bg-[#141821] border border-[#1F2430] rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-fuchsia-500 font-mono"
                            />
                          </div>
                        </div>
                        <p className="text-[10px] text-slate-400 font-mono">
                          ⏰ Will go public on: <span className="text-white font-bold">{ytScheduleDate || 'Select Date'} at {ytScheduleTime || '18:00'}</span>. The video will be uploaded as Private until this time.
                        </p>
                      </div>
                    )}
                  </div>

                  {/* Primary Direct Upload Button */}
                  <div className="pt-3 border-t border-[#1F2430]">
                    <button
                      onClick={handlePublishYouTubeDirect}
                      disabled={ytPublishing}
                      className="w-full bg-gradient-to-r from-red-600 via-rose-600 to-red-700 hover:opacity-95 text-white font-bold py-3.5 px-6 rounded-xl shadow-xl shadow-red-950/40 flex items-center justify-center gap-2.5 text-sm transition-all disabled:opacity-50"
                    >
                      <Youtube className={`h-5 w-5 ${ytPublishing ? 'animate-bounce' : ''}`} />
                      <span>
                        {ytPublishing
                          ? 'Uploading to YouTube Shorts directly...'
                          : ytPrivacy === 'scheduled'
                          ? `🚀 Schedule on YouTube Shorts (${ytScheduleDate} ${ytScheduleTime})`
                          : `🚀 Publish to YouTube Shorts Directly [${ytPrivacy.toUpperCase()}]`}
                      </span>
                    </button>
                    <p className="text-[10px] text-slate-500 text-center mt-2">
                      Uses YouTube Data API v3 resumable chunk upload with automated 9:16 vertical tags.
                    </p>
                  </div>
                </div>
              </div>

              {/* YouTube OAuth Setup Modal */}
              {showYtAuthModal && (
                <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
                  <div className="bg-[#141821] border border-[#1F2430] rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
                    <div className="flex items-center justify-between pb-3 border-b border-[#1F2430]">
                      <div className="flex items-center gap-2 text-red-400">
                        <Youtube className="h-5 w-5" />
                        <h3 className="text-sm font-bold text-white">YouTube Channel OAuth & Account Setup</h3>
                      </div>
                      <button onClick={() => setShowYtAuthModal(false)} className="text-slate-400 hover:text-white">
                        <X className="h-4 w-4" />
                      </button>
                    </div>

                    {/* Status Display: Connected Account Card */}
                    {ytAuthStatus?.has_token ? (
                      <div className="bg-[#0B0D12] border border-emerald-500/40 rounded-2xl p-4 flex items-center gap-4 shadow-lg shadow-emerald-950/20">
                        {ytAuthStatus.channel_avatar ? (
                          <img
                            src={ytAuthStatus.channel_avatar}
                            alt={ytAuthStatus.channel_title || 'Channel Avatar'}
                            className="h-16 w-16 rounded-full border-2 border-emerald-400 shadow-md object-cover shrink-0"
                          />
                        ) : (
                          <div className="h-16 w-16 rounded-full bg-red-600 flex items-center justify-center text-white shrink-0 font-bold text-lg">
                            <Youtube className="h-8 w-8" />
                          </div>
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-bold text-white truncate">
                              {ytAuthStatus.channel_title || 'Connected Channel'}
                            </span>
                            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 font-bold shrink-0">
                              ✓ Connected
                            </span>
                          </div>
                          <p className="text-xs text-slate-400 font-mono mt-0.5">
                            {ytAuthStatus.channel_handle || 'Direct 1-Click Publishing Ready'}
                          </p>
                          {ytAuthStatus.subscriber_count && (
                            <p className="text-[10px] text-slate-500 font-mono mt-0.5">
                              {parseInt(ytAuthStatus.subscriber_count).toLocaleString()} subscribers
                            </p>
                          )}
                          <p className="text-[11px] text-emerald-400/90 mt-1.5 flex items-center gap-1.5 font-medium">
                            <Check className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
                            <span>Authorized for vertical Shorts publishing</span>
                          </p>
                        </div>
                      </div>
                    ) : (ytConnecting || authPopupUrl) ? (
                      <div className="bg-[#0B0D12] border-2 border-red-500/60 rounded-2xl p-5 space-y-3.5 shadow-xl">
                        <div className="flex items-center gap-3 text-red-400">
                          <Youtube className="h-6 w-6 animate-pulse shrink-0" />
                          <div>
                            <h4 className="text-sm font-bold text-white">Google Authorization Active</h4>
                            <p className="text-[11px] text-slate-400">Complete the sign-in in your Google window</p>
                          </div>
                        </div>

                        <p className="text-xs text-slate-300 leading-relaxed">
                          A Google authorization page was launched. Choose your Google account and YouTube channel, then click <strong>Allow</strong>.
                        </p>

                        {authPopupUrl && (
                          <a
                            href={authPopupUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="w-full bg-red-600 hover:bg-red-500 text-white font-bold py-3 px-4 rounded-xl shadow-lg flex items-center justify-center gap-2 text-xs transition-all"
                          >
                            <ExternalLink className="h-4 w-4" />
                            <span>👉 Click Here to Open Google Sign-In Window</span>
                          </a>
                        )}

                        <div className="flex items-center gap-2 text-[11px] text-amber-300 bg-amber-500/10 border border-amber-500/20 p-2.5 rounded-xl">
                          <span className="h-2 w-2 rounded-full bg-amber-400 animate-ping shrink-0" />
                          <span>Waiting for you to authorize in Google... This modal will automatically update with your YouTube profile picture as soon as you approve.</span>
                        </div>

                        <div className="text-[10px] text-slate-400 space-y-1 bg-[#141821] p-3 rounded-xl border border-[#1F2430]">
                          <p className="font-semibold text-slate-300">💡 Important Google Screen Tips:</p>
                          <p>• If it says <em>"Google hasn't verified this app"</em>: Click <strong>Advanced</strong> → <strong>Go to Stream-Clipper (unsafe)</strong> → <strong>Continue</strong>.</p>
                          <p>• If it says <em>"Access blocked: This app is in testing"</em>: In Google Cloud Console, add your email to the <strong>Test users</strong> list under OAuth consent screen.</p>
                        </div>
                      </div>
                    ) : ytAuthStatus?.has_client_secret ? (
                      <div className="bg-[#0B0D12] border border-amber-500/40 rounded-2xl p-4 space-y-3">
                        <div className="flex items-center gap-2 text-amber-300">
                          <Check className="h-4 w-4 text-emerald-400 shrink-0" />
                          <span className="text-xs font-bold text-white">OAuth Secret Configured (client_secret.json)</span>
                        </div>
                        <p className="text-xs text-slate-300 leading-relaxed">
                          Your client secrets are saved. Click below to sign in with Google in your browser to authorize your YouTube channel and load your profile icon.
                        </p>
                        <button
                          onClick={handleConnectYouTube}
                          disabled={ytConnecting}
                          className="w-full bg-gradient-to-r from-red-600 via-rose-600 to-red-700 hover:opacity-95 text-white font-bold py-3 px-4 rounded-xl shadow-lg shadow-red-950/40 flex items-center justify-center gap-2 text-xs transition-all disabled:opacity-50"
                        >
                          <Youtube className="h-4 w-4" />
                          <span>🔴 Sign In with Google & Authorize Channel</span>
                        </button>
                      </div>
                    ) : null}

                    {/* Instructions and Client Secret JSON Field */}
                    <div className="space-y-3 text-xs text-slate-300 leading-relaxed pt-2 border-t border-[#1F2430]">
                      <p className="text-slate-400">
                        {ytAuthStatus?.has_client_secret
                          ? 'To switch Google Cloud projects, paste a new client_secret.json below:'
                          : 'To enable direct 1-click publishing, Google requires an OAuth 2.0 Client ID (Desktop Application):'}
                      </p>
                      {!ytAuthStatus?.has_client_secret && (
                        <ol className="list-decimal list-inside space-y-1 text-slate-400 text-[11px]">
                          <li>Go to Google Cloud Console → APIs & Services → Credentials.</li>
                          <li>Create an <strong>OAuth 2.0 Client ID</strong> (Desktop Application).</li>
                          <li>Download the JSON and paste its contents below (or place as <code className="text-amber-300">client_secret.json</code> in project root).</li>
                        </ol>
                      )}

                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="text-[11px] font-semibold text-slate-300">
                            Paste client_secret.json contents:
                          </label>
                          {ytAuthStatus?.has_client_secret && (
                            <span className="text-[10px] text-emerald-400 font-mono">✓ File Present</span>
                          )}
                        </div>
                        <textarea
                          rows={4}
                          value={ytSecretContent}
                          onChange={(e) => setYtSecretContent(e.target.value)}
                          placeholder='{"installed":{"client_id":"...","project_id":"...","auth_uri":"...","token_uri":"...","client_secret":"..."}}'
                          className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl p-3 font-mono text-[11px] text-slate-300 focus:outline-none focus:border-red-500 resize-none"
                        />
                      </div>
                    </div>

                    <div className="flex items-center justify-between gap-2 pt-2 border-t border-[#1F2430]">
                      {ytAuthStatus?.has_token ? (
                        <button
                          onClick={handleDisconnectYouTube}
                          className="px-3.5 py-2 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 hover:bg-rose-500/20 text-xs font-semibold transition-all"
                        >
                          Disconnect Channel
                        </button>
                      ) : (
                        <div />
                      )}

                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => setShowYtAuthModal(false)}
                          className="px-4 py-2 rounded-xl bg-[#0B0D12] text-slate-400 hover:text-white text-xs font-semibold"
                        >
                          Close
                        </button>
                        {ytSecretContent.trim() ? (
                          <button
                            onClick={handleSaveClientSecret}
                            className="px-4 py-2 rounded-xl bg-red-600 hover:bg-red-500 text-white text-xs font-bold shadow-md shadow-red-950/30"
                          >
                            Save Client Secret
                          </button>
                        ) : ytAuthStatus?.has_client_secret && !ytAuthStatus?.has_token ? (
                          <button
                            onClick={handleConnectYouTube}
                            disabled={ytConnecting}
                            className="px-4 py-2 rounded-xl bg-red-600 hover:bg-red-500 text-white text-xs font-bold shadow-md shadow-red-950/30 disabled:opacity-50"
                          >
                            {ytConnecting ? 'Signing in...' : 'Sign In with Google'}
                          </button>
                        ) : null}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* VIEW: DEDICATED FACEBOOK REELS DIRECT PUBLISHING HUB */}
          {activeTab === 'facebook' && (
            <div className="max-w-6xl mx-auto space-y-6">
              {/* Top Banner */}
              <div className="flex flex-col md:flex-row md:items-center justify-between bg-[#141821] border border-[#1F2430] rounded-2xl p-6 shadow-xl gap-4">
                <div className="flex items-center gap-4">
                  <div className="h-12 w-12 rounded-2xl bg-blue-600/20 border border-blue-500/40 flex items-center justify-center text-blue-500 shadow-lg shadow-blue-950/40 shrink-0">
                    <Facebook className="h-6 w-6" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-xl font-bold text-white tracking-tight">Facebook Reels Direct Publisher</h2>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-blue-600/30 text-blue-300 font-bold border border-blue-500/40">
                        GRAPH API v21
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 mt-1">
                      Directly upload your vertical 1080x1920 60fps Reels to your Facebook Page with auto-generated viral captions, hashtags, and schedule times.
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3 shrink-0">
                  <button
                    onClick={() => setShowFbAuthModal(true)}
                    className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-[#0B0D12] border border-[#1F2430] hover:border-slate-600 text-slate-300 hover:text-white text-xs font-semibold transition-all"
                  >
                    <SettingsIcon className="h-3.5 w-3.5 text-slate-400" />
                    <span>{fbAuthStatus?.has_token ? '🔑 Meta Token Connected' : '⚙️ Setup Meta Token'}</span>
                  </button>

                  <button
                    onClick={handleOpenMetaSuite}
                    className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[#1A1F2C] hover:bg-[#252C3D] border border-blue-500/30 text-blue-300 font-bold text-xs transition-all shadow-md"
                    title="Copies caption + hashtags and opens Meta Business Suite Reels composer"
                  >
                    <ExternalLink className="h-3.5 w-3.5 text-blue-400" />
                    <span>{copiedToast ? '✓ Copied & Opened!' : 'Open in Meta Business Suite'}</span>
                  </button>
                </div>
              </div>

              {/* Horizontal Clip Selector Bar */}
              {clips.length > 0 && (
                <div className="bg-[#141821] border border-[#1F2430] rounded-2xl p-4 shadow-md">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <PlayCircle className="h-4 w-4 text-blue-400" />
                      <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                        Select Clip to Publish ({clips.length} ready)
                      </span>
                    </div>
                    <span className="text-[11px] text-slate-400 font-mono">
                      Selected: Clip #{selectedClipIndex + 1} ({activeClip?.duration || 0}s)
                    </span>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
                    {clips.map((c, idx) => (
                      <div
                        key={c.clip_id}
                        onClick={() => setSelectedClipIndex(idx)}
                        className={`p-3 rounded-xl border cursor-pointer transition-all ${
                          selectedClipIndex === idx
                            ? 'bg-blue-600/15 border-blue-500/60 shadow-lg shadow-blue-950/30 ring-1 ring-blue-500/40'
                            : 'bg-[#0B0D12] border-[#1F2430] hover:border-slate-700'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-bold text-white uppercase">Clip #{idx + 1}</span>
                          <span className="text-[10px] font-mono text-emerald-400 font-bold">{c.virality_score}/100</span>
                        </div>
                        <p className="text-[11px] font-medium text-slate-300 line-clamp-1">{c.hook_text}</p>
                        <div className="flex items-center justify-between mt-2 pt-1 border-t border-[#1F2430]/60 text-[9px] text-slate-400 font-mono">
                          <span>{c.duration}s</span>
                          <span className={c.preview_url ? 'text-emerald-400 font-bold' : 'text-amber-400'}>
                            {c.preview_url ? '✓ Ready' : '⏳ Rendering'}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Main 2-Column Publishing Studio */}
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
                {/* Left Column: 9:16 Video Player Card (5 cols) */}
                <div className="lg:col-span-5 bg-[#141821] rounded-2xl border border-[#1F2430] p-5 shadow-xl flex flex-col items-center justify-between space-y-4">
                  <div className="w-full flex items-center justify-between pb-3 border-b border-[#1F2430]">
                    <span className="text-xs font-bold text-white uppercase tracking-wider">Reels Video Preview</span>
                    <span className="text-[10px] font-mono text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded border border-blue-500/30 font-bold">
                      1080x1920 60FPS NVENC
                    </span>
                  </div>

                  {/* 9:16 Vertical Video Frame */}
                  <div className="relative aspect-[9/16] w-full max-w-[280px] rounded-2xl overflow-hidden bg-black border-2 border-[#1F2430] shadow-2xl flex items-center justify-center">
                    {activeClip?.preview_url ? (
                      <video
                        key={activeClip.preview_url}
                        src={activeClip.preview_url}
                        controls
                        autoPlay
                        loop
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <div className="text-center p-6 text-slate-600">
                        <Video className="h-10 w-10 mx-auto mb-2 text-blue-500/50" />
                        <p className="text-xs font-semibold text-slate-400">Rendering Clip...</p>
                        <p className="text-[10px] text-slate-500 mt-1">Autonomous hardware encoder active</p>
                      </div>
                    )}
                  </div>

                  {/* Video Specs & Local Download */}
                  <div className="w-full space-y-2 pt-2 border-t border-[#1F2430]">
                    <div className="grid grid-cols-2 gap-2 text-[11px] font-mono text-slate-400">
                      <div className="bg-[#0B0D12] p-2 rounded-lg border border-[#1F2430]">
                        <span className="text-slate-500 block text-[9px] uppercase">Format</span>
                        <span className="text-white font-bold">MP4 (mp42)</span>
                      </div>
                      <div className="bg-[#0B0D12] p-2 rounded-lg border border-[#1F2430]">
                        <span className="text-slate-500 block text-[9px] uppercase">Audio</span>
                        <span className="text-white font-bold">AAC Stereo -14 LUFS</span>
                      </div>
                    </div>

                    {activeClip?.preview_url && (
                      <a
                        href={activeJobId ? `/api/jobs/${activeJobId}/clips/${activeClip.clip_id}/download` : activeClip.preview_url}
                        download={`GTA6_${activeClip.clip_id}_Short.mp4`}
                        className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl bg-[#0B0D12] hover:bg-[#191F2C] border border-[#1F2430] text-slate-300 hover:text-white font-semibold text-xs transition-colors"
                      >
                        <Download className="h-3.5 w-3.5 text-blue-400" />
                        <span>Download MP4 for Backup</span>
                      </a>
                    )}
                  </div>
                </div>

                {/* Right Column: Detailed Facebook Reels Form (7 cols) */}
                <div className="lg:col-span-7 bg-[#141821] rounded-2xl border border-[#1F2430] p-6 shadow-xl space-y-5">
                  {/* Results Banner (if uploaded) */}
                  {fbPublishResult && (
                    <div className="bg-emerald-500/15 border border-emerald-500/40 rounded-xl p-4 shadow-lg flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <CheckCircle2 className="h-6 w-6 text-emerald-400 shrink-0" />
                        <div>
                          <h4 className="text-xs font-bold text-white">Successfully Processed Facebook Reel!</h4>
                          <p className="text-[11px] text-emerald-300 font-mono mt-0.5">{fbPublishResult.url}</p>
                        </div>
                      </div>
                      <a
                        href={fbPublishResult.url}
                        target="_blank"
                        rel="noreferrer"
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500 text-black text-xs font-bold hover:bg-emerald-400 transition-colors"
                      >
                        <span>View on Facebook</span>
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    </div>
                  )}

                  {/* Error Banner */}
                  {fbPublishError && (
                    <div className="bg-rose-500/15 border border-rose-500/40 rounded-xl p-4 shadow-lg flex items-start gap-3">
                      <AlertCircle className="h-5 w-5 text-rose-400 shrink-0 mt-0.5" />
                      <div className="flex-1">
                        <h4 className="text-xs font-bold text-white">Facebook Upload Error</h4>
                        <p className="text-[11px] text-rose-300 mt-0.5 leading-relaxed">{fbPublishError}</p>
                        {fbPublishError.includes('META_ACCESS_TOKEN') || fbPublishError.includes('META_PAGE_ID') ? (
                          <button
                            onClick={() => setShowFbAuthModal(true)}
                            className="mt-2 text-xs text-blue-400 underline font-semibold"
                          >
                            Click here to configure Meta Token & Page ID
                          </button>
                        ) : null}
                      </div>
                    </div>
                  )}

                  {/* 1. Facebook Page ID Input */}
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                        <span>Facebook Page ID</span>
                        <span className="text-blue-400">*</span>
                      </label>
                      <span className="text-[11px] font-mono text-slate-500">
                        {fbAuthStatus?.page_id ? `Configured in .env: ${fbAuthStatus.page_id}` : 'Required for Reels API'}
                      </span>
                    </div>
                    <input
                      type="text"
                      value={fbPageId}
                      onChange={(e) => setFbPageId(e.target.value)}
                      placeholder="e.g. 109283746581928"
                      className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-4 py-2.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 font-mono transition-colors"
                    />
                  </div>

                  {/* 2. Reels Caption Textarea */}
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                        <span>Reels Caption</span>
                        <span className="text-blue-400">*</span>
                      </label>
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] font-mono text-slate-400">{fbCaption.length}/2000</span>
                        <button
                          onClick={() => {
                            if (activeClip) {
                              setFbCaption(activeClip.social_metadata?.facebook.caption || `🔥 Epic GTA 6 Moment: ${activeClip.hook_text}! What a scene.`);
                            }
                          }}
                          className="text-[10px] text-blue-400 hover:text-blue-300 underline font-mono"
                        >
                          Reset AI Caption
                        </button>
                      </div>
                    </div>
                    <textarea
                      rows={5}
                      maxLength={2000}
                      value={fbCaption}
                      onChange={(e) => setFbCaption(e.target.value)}
                      placeholder="Engaging caption for Facebook Reels viewers..."
                      className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl p-3 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 resize-none font-sans leading-relaxed"
                    />
                  </div>

                  {/* 3. Hashtags Badges */}
                  <div>
                    <label className="block text-xs font-bold uppercase tracking-wider text-slate-300 mb-1.5">
                      Reels Hashtags ({fbHashtags.length})
                    </label>
                    <div className="flex flex-wrap gap-1.5 p-2 bg-[#0B0D12] border border-[#1F2430] rounded-xl min-h-[42px] items-center">
                      {fbHashtags.map((tag, tIdx) => (
                        <span
                          key={tIdx}
                          className="flex items-center gap-1 bg-[#1A202C] border border-[#2D3748] text-blue-300 px-2 py-0.5 rounded-lg text-xs font-mono"
                        >
                          <span>{tag.startsWith('#') ? tag : `#${tag}`}</span>
                          <button
                            type="button"
                            onClick={() => setFbHashtags(fbHashtags.filter((_, i) => i !== tIdx))}
                            className="hover:text-rose-400"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </span>
                      ))}
                      <div className="flex items-center gap-1 pl-1">
                        <input
                          type="text"
                          value={fbTagInput}
                          onChange={(e) => setFbTagInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && fbTagInput.trim()) {
                              e.preventDefault();
                              const clean = '#' + fbTagInput.trim().replace(/^#/, '');
                              if (!fbHashtags.includes(clean)) {
                                setFbHashtags([...fbHashtags, clean]);
                              }
                              setFbTagInput('');
                            }
                          }}
                          placeholder="+ Add hashtag (Enter)"
                          className="bg-transparent text-xs text-white placeholder-slate-600 focus:outline-none w-32 font-mono"
                        />
                      </div>
                    </div>
                  </div>

                  {/* 4. Visibility & Publishing Mode Selector */}
                  <div className="space-y-3 pt-2 border-t border-[#1F2430]">
                    <label className="block text-xs font-bold uppercase tracking-wider text-slate-300">
                      Publishing State & Schedule
                    </label>

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                      {/* Publish Now */}
                      <button
                        type="button"
                        onClick={() => setFbState('PUBLISHED')}
                        className={`p-3 rounded-xl border text-left flex flex-col justify-between transition-all ${
                          fbState === 'PUBLISHED'
                            ? 'bg-blue-600/15 border-blue-500 text-white shadow-md shadow-blue-950/30 ring-1 ring-blue-500/40'
                            : 'bg-[#0B0D12] border-[#1F2430] text-slate-400 hover:text-white'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <Globe className={`h-4 w-4 ${fbState === 'PUBLISHED' ? 'text-blue-400' : 'text-slate-500'}`} />
                          <span className={`h-2 w-2 rounded-full ${fbState === 'PUBLISHED' ? 'bg-blue-400' : 'bg-slate-600'}`} />
                        </div>
                        <div>
                          <span className="text-xs font-bold block">Publish Now</span>
                          <span className="text-[10px] text-slate-400">Immediate live Reel</span>
                        </div>
                      </button>

                      {/* Schedule */}
                      <button
                        type="button"
                        onClick={() => setFbState('SCHEDULED')}
                        className={`p-3 rounded-xl border text-left flex flex-col justify-between transition-all ${
                          fbState === 'SCHEDULED'
                            ? 'bg-fuchsia-600/15 border-fuchsia-500 text-white shadow-md shadow-fuchsia-950/30 ring-1 ring-fuchsia-500/40'
                            : 'bg-[#0B0D12] border-[#1F2430] text-slate-400 hover:text-white'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <Calendar className={`h-4 w-4 ${fbState === 'SCHEDULED' ? 'text-fuchsia-400' : 'text-slate-500'}`} />
                          <span className={`h-2 w-2 rounded-full ${fbState === 'SCHEDULED' ? 'bg-fuchsia-400' : 'bg-slate-600'}`} />
                        </div>
                        <div>
                          <span className="text-xs font-bold block">Schedule Reel</span>
                          <span className="text-[10px] text-slate-400">Pick date & time</span>
                        </div>
                      </button>

                      {/* Draft */}
                      <button
                        type="button"
                        onClick={() => setFbState('DRAFT')}
                        className={`p-3 rounded-xl border text-left flex flex-col justify-between transition-all ${
                          fbState === 'DRAFT'
                            ? 'bg-amber-600/15 border-amber-500 text-white shadow-md shadow-amber-950/30 ring-1 ring-amber-500/40'
                            : 'bg-[#0B0D12] border-[#1F2430] text-slate-400 hover:text-white'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <Lock className={`h-4 w-4 ${fbState === 'DRAFT' ? 'text-amber-400' : 'text-slate-500'}`} />
                          <span className={`h-2 w-2 rounded-full ${fbState === 'DRAFT' ? 'bg-amber-400' : 'bg-slate-600'}`} />
                        </div>
                        <div>
                          <span className="text-xs font-bold block">Save as Draft</span>
                          <span className="text-[10px] text-slate-400">Draft in Page studio</span>
                        </div>
                      </button>
                    </div>

                    {/* Schedule Date & Time Picker */}
                    {fbState === 'SCHEDULED' && (
                      <div className="bg-[#0B0D12] border border-fuchsia-500/40 rounded-xl p-4 shadow-inner space-y-3">
                        <div className="flex items-center gap-2 text-fuchsia-300 text-xs font-bold">
                          <Calendar className="h-4 w-4" />
                          <span>Choose Scheduled Premiere Time (Facebook Reels)</span>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <div>
                            <label className="block text-[10px] font-mono text-slate-400 mb-1 uppercase">
                              Publish Date
                            </label>
                            <input
                              type="date"
                              value={fbScheduleDate}
                              onChange={(e) => setFbScheduleDate(e.target.value)}
                              className="w-full bg-[#141821] border border-[#1F2430] rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-fuchsia-500 font-mono"
                            />
                          </div>
                          <div>
                            <label className="block text-[10px] font-mono text-slate-400 mb-1 uppercase">
                              Publish Time
                            </label>
                            <input
                              type="time"
                              value={fbScheduleTime}
                              onChange={(e) => setFbScheduleTime(e.target.value)}
                              className="w-full bg-[#141821] border border-[#1F2430] rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-fuchsia-500 font-mono"
                            />
                          </div>
                        </div>
                        <p className="text-[10px] text-slate-400 font-mono">
                          ⏰ Will publish on Facebook: <span className="text-white font-bold">{fbScheduleDate || 'Select Date'} at {fbScheduleTime || '18:00'}</span>. Must be at least 10 minutes from now.
                        </p>
                      </div>
                    )}
                  </div>

                  {/* Primary Direct Upload Button */}
                  <div className="pt-3 border-t border-[#1F2430]">
                    <button
                      onClick={handlePublishFacebookDirect}
                      disabled={fbPublishing}
                      className="w-full bg-gradient-to-r from-blue-600 via-indigo-600 to-blue-700 hover:opacity-95 text-white font-bold py-3.5 px-6 rounded-xl shadow-xl shadow-blue-950/40 flex items-center justify-center gap-2.5 text-sm transition-all disabled:opacity-50"
                    >
                      <Facebook className={`h-5 w-5 ${fbPublishing ? 'animate-bounce' : ''}`} />
                      <span>
                        {fbPublishing
                          ? 'Publishing to Facebook Reels directly...'
                          : fbState === 'SCHEDULED'
                          ? `🚀 Schedule Facebook Reel (${fbScheduleDate} ${fbScheduleTime})`
                          : fbState === 'DRAFT'
                          ? `📝 Save Reel as Page Draft`
                          : `🚀 Publish to Facebook Reels Directly`}
                      </span>
                    </button>
                    <p className="text-[10px] text-slate-500 text-center mt-2">
                      Uses Meta Graph API v21.0 3-step binary rupload pipeline.
                    </p>
                  </div>
                </div>
              </div>

              {/* Meta Credentials Setup Modal */}
              {showFbAuthModal && (
                <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
                  <div className="bg-[#141821] border border-[#1F2430] rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
                    <div className="flex items-center justify-between pb-3 border-b border-[#1F2430]">
                      <div className="flex items-center gap-2 text-blue-400">
                        <Facebook className="h-5 w-5" />
                        <h3 className="text-sm font-bold text-white">Meta / Facebook Credentials Setup</h3>
                      </div>
                      <button onClick={() => setShowFbAuthModal(false)} className="text-slate-400 hover:text-white">
                        <X className="h-4 w-4" />
                      </button>
                    </div>

                    <div className="space-y-3 text-xs text-slate-300 leading-relaxed">
                      <p>
                        To publish directly to Facebook Reels, configure your Page Access Token and Page ID in the Engine Settings:
                      </p>
                      <div className="space-y-2">
                        <div>
                          <label className="block text-[11px] font-semibold text-slate-400 mb-1">Facebook Page ID</label>
                          <input
                            type="text"
                            value={fbPageId}
                            onChange={(e) => setFbPageId(e.target.value)}
                            placeholder="e.g. 109283746581928"
                            className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-3 py-2 text-xs text-white font-mono"
                          />
                        </div>
                      </div>
                      <p className="text-[11px] text-slate-400">
                        You can also set these permanently in the <strong>AI Engine Settings</strong> tab or in your <code className="text-blue-300">.env</code> file.
                      </p>
                    </div>

                    <div className="flex items-center justify-end gap-2 pt-2 border-t border-[#1F2430]">
                      <button
                        onClick={() => setShowFbAuthModal(false)}
                        className="px-4 py-2 rounded-xl bg-[#0B0D12] text-slate-400 hover:text-white text-xs font-semibold"
                      >
                        Close
                      </button>
                      <button
                        onClick={() => {
                          setShowFbAuthModal(false);
                          setActiveTab('settings');
                        }}
                        className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold"
                      >
                        Open Full Settings
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* VIEW 3: MULTI-PLATFORM UPLOAD HUB */}
          {activeTab === 'upload' && (
            <div className="max-w-6xl mx-auto space-y-6">
              {/* Top Hub Bar with Export Pack */}
              <div className="flex items-center justify-between bg-[#141821] border border-[#1F2430] rounded-2xl p-6">
                <div>
                  <h2 className="text-xl font-bold text-white tracking-tight">Multi-Platform Publishing Center</h2>
                  <p className="text-xs text-slate-400 mt-1">
                    Direct API upload to YouTube Shorts, Instagram Reels, and Facebook Reels with 1-Click Export.
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  {/* Clip Selector if multiple */}
                  {clips.length > 1 && (
                    <select
                      value={selectedClipIndex}
                      onChange={(e) => setSelectedClipIndex(Number(e.target.value))}
                      className="bg-[#0B0D12] border border-[#1F2430] rounded-xl px-3 py-2.5 text-xs text-white"
                    >
                      {clips.map((c, i) => (
                        <option key={c.clip_id} value={i}>
                          Clip #{i + 1} ({c.duration}s) - Score {c.virality_score}
                        </option>
                      ))}
                    </select>
                  )}

                  {/* 1-Click Export Pack */}
                  <button
                    onClick={handleExportPack}
                    className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 hover:opacity-95 text-white font-bold text-xs shadow-lg shadow-emerald-500/20 transition-all"
                  >
                    {copiedToast ? <Check className="h-4 w-4" /> : <Download className="h-4 w-4" />}
                    <span>{copiedToast ? '✓ Copied & Downloaded!' : '📥 1-Click Export Pack'}</span>
                  </button>
                </div>
              </div>

              {/* 3-Column Platform Publishing Grid */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* 1. YouTube Shorts Card */}
                <div className="bg-[#141821] rounded-2xl border border-[#1F2430] p-6 flex flex-col justify-between shadow-xl">
                  <div className="space-y-4">
                    <div className="flex items-center justify-between pb-3 border-b border-[#1F2430]">
                      <div className="flex items-center gap-2.5 text-red-400">
                        <Youtube className="h-5 w-5" />
                        <h3 className="text-sm font-bold text-white">YouTube Shorts</h3>
                      </div>
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-red-500/15 border border-red-500/30 text-red-300 font-mono">
                        #Shorts
                      </span>
                    </div>

                    {/* YouTube Channel Connected Avatar & Status */}
                    {ytAuthStatus?.has_token ? (
                      <div className="flex items-center gap-2.5 p-2 rounded-xl bg-[#0B0D12] border border-emerald-500/30">
                        {ytAuthStatus.channel_avatar ? (
                          <img
                            src={ytAuthStatus.channel_avatar}
                            alt="Channel Avatar"
                            className="h-7 w-7 rounded-full border border-emerald-400 object-cover shrink-0"
                          />
                        ) : (
                          <div className="h-7 w-7 rounded-full bg-red-600 flex items-center justify-center text-white shrink-0">
                            <Youtube className="h-3.5 w-3.5" />
                          </div>
                        )}
                        <div className="flex-1 min-w-0">
                          <span className="text-xs font-bold text-white truncate block">
                            {ytAuthStatus.channel_title}
                          </span>
                          <span className="text-[10px] text-slate-400 font-mono truncate block">
                            {ytAuthStatus.channel_handle || 'Connected Channel'}
                          </span>
                        </div>
                        <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/40">
                          Ready
                        </span>
                      </div>
                    ) : (
                      <div className="flex items-center justify-between p-2 rounded-xl bg-amber-500/10 border border-amber-500/30 text-[11px] text-amber-300">
                        <span>{ytAuthStatus?.has_client_secret ? 'YouTube not signed in' : 'OAuth not configured'}</span>
                        <button
                          onClick={() => {
                            if (ytAuthStatus?.has_client_secret) {
                              handleConnectYouTube();
                            } else {
                              setShowYtAuthModal(true);
                            }
                          }}
                          className="text-[10px] font-bold bg-amber-500 text-black px-2 py-0.5 rounded hover:bg-amber-400"
                        >
                          {ytAuthStatus?.has_client_secret ? 'Sign In' : 'Setup'}
                        </button>
                      </div>
                    )}

                    <div>
                      <div className="flex justify-between text-[11px] text-slate-400 mb-1">
                        <span>Shorts Title</span>
                        <span>{activeClip?.social_metadata?.youtube.title.length || 0}/100</span>
                      </div>
                      <input
                        type="text"
                        value={activeClip?.social_metadata?.youtube.title || ''}
                        onChange={(e) => {
                          if (activeClip?.social_metadata) {
                            const updated = { ...activeClip.social_metadata };
                            updated.youtube.title = e.target.value;
                            handleUpdateCurrentClip({ social_metadata: updated });
                          }
                        }}
                        className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-lg px-3 py-2 text-xs text-white"
                      />
                    </div>

                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">Description & Tags</label>
                      <textarea
                        rows={4}
                        value={activeClip?.social_metadata?.youtube.description || ''}
                        onChange={(e) => {
                          if (activeClip?.social_metadata) {
                            const updated = { ...activeClip.social_metadata };
                            updated.youtube.description = e.target.value;
                            handleUpdateCurrentClip({ social_metadata: updated });
                          }
                        }}
                        className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-lg p-2.5 text-xs text-white resize-none"
                      />
                    </div>

                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">Upload Privacy</label>
                      <select
                        value={activeClip?.social_metadata?.youtube.privacy || 'private'}
                        onChange={(e) => {
                          if (activeClip?.social_metadata) {
                            const updated = { ...activeClip.social_metadata };
                            updated.youtube.privacy = e.target.value;
                            handleUpdateCurrentClip({ social_metadata: updated });
                          }
                        }}
                        className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-lg px-3 py-2 text-xs text-white"
                      >
                        <option value="private">Private (Recommended Review)</option>
                        <option value="unlisted">Unlisted</option>
                        <option value="public">Public (Immediate Live)</option>
                      </select>
                    </div>
                  </div>

                  <div className="pt-6">
                    <button
                      onClick={() => handlePublishPlatform('youtube')}
                      disabled={publishingPlatform === 'youtube'}
                      className="w-full bg-red-600 hover:bg-red-500 text-white font-bold py-2.5 rounded-xl text-xs flex items-center justify-center gap-2 transition-colors disabled:opacity-50"
                    >
                      <Youtube className="h-4 w-4" />
                      <span>{publishingPlatform === 'youtube' ? 'Publishing...' : 'Publish to Shorts'}</span>
                    </button>
                    {publishUrls['youtube'] && (
                      <a
                        href={publishUrls['youtube']}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-2 text-[11px] text-red-400 flex items-center justify-center gap-1 underline"
                      >
                        <span>View Live Short</span>
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>
                </div>

                {/* 2. Instagram Reels Card */}
                <div className="bg-[#141821] rounded-2xl border border-[#1F2430] p-6 flex flex-col justify-between shadow-xl">
                  <div className="space-y-4">
                    <div className="flex items-center justify-between pb-3 border-b border-[#1F2430]">
                      <div className="flex items-center gap-2.5 text-pink-400">
                        <Instagram className="h-5 w-5" />
                        <h3 className="text-sm font-bold text-white">Instagram Reels</h3>
                      </div>
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-pink-500/15 border border-pink-500/30 text-pink-300 font-mono">
                        Container API
                      </span>
                    </div>

                    <div>
                      <div className="flex justify-between text-[11px] text-slate-400 mb-1">
                        <span>Reels Caption</span>
                        <span>{activeClip?.social_metadata?.instagram.caption.length || 0}/2200</span>
                      </div>
                      <textarea
                        rows={5}
                        value={activeClip?.social_metadata?.instagram.caption || ''}
                        onChange={(e) => {
                          if (activeClip?.social_metadata) {
                            const updated = { ...activeClip.social_metadata };
                            updated.instagram.caption = e.target.value;
                            handleUpdateCurrentClip({ social_metadata: updated });
                          }
                        }}
                        className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-lg p-2.5 text-xs text-white resize-none"
                      />
                    </div>

                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">Trending Hashtags</label>
                      <div className="p-2.5 bg-[#0B0D12] rounded-lg border border-[#1F2430] flex flex-wrap gap-1 max-h-24 overflow-y-auto">
                        {(activeClip?.social_metadata?.instagram.hashtags || []).map((tag, i) => (
                          <span key={i} className="text-[10px] bg-pink-500/10 text-pink-300 px-1.5 py-0.5 rounded">
                            {tag}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="pt-6">
                    <button
                      onClick={() => handlePublishPlatform('instagram')}
                      disabled={publishingPlatform === 'instagram'}
                      className="w-full bg-gradient-to-r from-pink-600 via-purple-600 to-indigo-600 hover:opacity-95 text-white font-bold py-2.5 rounded-xl text-xs flex items-center justify-center gap-2 transition-all disabled:opacity-50"
                    >
                      <Instagram className="h-4 w-4" />
                      <span>{publishingPlatform === 'instagram' ? 'Publishing...' : 'Publish Reel'}</span>
                    </button>
                    {publishUrls['instagram'] && (
                      <a
                        href={publishUrls['instagram']}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-2 text-[11px] text-pink-400 flex items-center justify-center gap-1 underline"
                      >
                        <span>View Live Reel</span>
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>
                </div>

                {/* 3. Facebook Reels Card */}
                <div className="bg-[#141821] rounded-2xl border border-[#1F2430] p-6 flex flex-col justify-between shadow-xl">
                  <div className="space-y-4">
                    <div className="flex items-center justify-between pb-3 border-b border-[#1F2430]">
                      <div className="flex items-center gap-2.5 text-blue-400">
                        <Facebook className="h-5 w-5" />
                        <h3 className="text-sm font-bold text-white">Facebook Reels</h3>
                      </div>
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/15 border border-blue-500/30 text-blue-300 font-mono">
                        Direct Binary
                      </span>
                    </div>

                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">Post Caption & Tags</label>
                      <textarea
                        rows={7}
                        value={activeClip?.social_metadata?.facebook.caption || ''}
                        onChange={(e) => {
                          if (activeClip?.social_metadata) {
                            const updated = { ...activeClip.social_metadata };
                            updated.facebook.caption = e.target.value;
                            handleUpdateCurrentClip({ social_metadata: updated });
                          }
                        }}
                        className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-lg p-2.5 text-xs text-white resize-none"
                      />
                    </div>

                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">Reels Tags</label>
                      <div className="p-2.5 bg-[#0B0D12] rounded-lg border border-[#1F2430] flex flex-wrap gap-1 max-h-20 overflow-y-auto">
                        {(activeClip?.social_metadata?.facebook.hashtags || []).map((tag, i) => (
                          <span key={i} className="text-[10px] bg-blue-500/10 text-blue-300 px-1.5 py-0.5 rounded">
                            {tag}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="pt-6">
                    <button
                      onClick={() => handlePublishPlatform('facebook')}
                      disabled={publishingPlatform === 'facebook'}
                      className="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-2.5 rounded-xl text-xs flex items-center justify-center gap-2 transition-colors disabled:opacity-50"
                    >
                      <Facebook className="h-4 w-4" />
                      <span>{publishingPlatform === 'facebook' ? 'Publishing...' : 'Publish to FB'}</span>
                    </button>
                    {publishUrls['facebook'] && (
                      <a
                        href={publishUrls['facebook']}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-2 text-[11px] text-blue-400 flex items-center justify-center gap-1 underline"
                      >
                        <span>View Live Reel</span>
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* VIEW 4: HARDWARE & API SETTINGS */}
          {activeTab === 'settings' && (
            <div className="max-w-3xl mx-auto space-y-6">
              <div className="bg-[#141821] border border-[#1F2430] rounded-2xl p-6 shadow-xl space-y-6">
                <div className="flex items-center justify-between border-b border-[#1F2430] pb-4">
                  <div className="flex items-center gap-2.5">
                    <SettingsIcon className="h-5 w-5 text-indigo-400" />
                    <div>
                      <h2 className="text-base font-bold text-white">Hardware & API Credentials</h2>
                      <p className="text-xs text-slate-400">Configure AI Brain keys and social publishing credentials.</p>
                    </div>
                  </div>
                  <button
                    onClick={handleSaveSettings}
                    className="flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs transition-colors"
                  >
                    <Save className="h-4 w-4" />
                    <span>{settingsSaved ? '✓ Saved!' : 'Save Settings'}</span>
                  </button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                  {/* Google ADC Status Banner */}
                  {isAdc && (
                    <div className="col-span-2 p-3.5 bg-emerald-500/10 border border-emerald-500/30 rounded-xl text-xs text-emerald-300 flex items-center justify-between">
                      <div className="flex items-center gap-2.5">
                        <Check className="h-4 w-4 text-emerald-400 shrink-0" />
                        <div>
                          <p className="font-bold text-white">Google Cloud ADC Connected (Same as new-oms-native)</p>
                          <p className="text-[11px] text-emerald-400/90 font-mono">Quota Project: {adcProject} • No manual API key required!</p>
                        </div>
                      </div>
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-mono">
                        AUTHENTICATED
                      </span>
                    </div>
                  )}

                  {/* Google GenAI Key */}
                  <div className="col-span-2">
                    <label className="block text-slate-300 font-semibold mb-1">
                      GEMINI_API_KEY (Google GenAI)
                    </label>
                    <input
                      type="password"
                      value={geminiApiKey}
                      onChange={(e) => setGeminiApiKey(e.target.value)}
                      placeholder="AIzaSy... (Enables Gemini 3.8 Flash Vision, TTS, & Overlays)"
                      className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-4 py-2.5 text-white"
                    />
                  </div>

                  {/* AI Brain Models */}
                  <div>
                    <label className="block text-slate-400 mb-1">Director Model</label>
                    <input
                      type="text"
                      value={directorModel}
                      onChange={(e) => setDirectorModel(e.target.value)}
                      className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-3 py-2 text-white font-mono text-xs"
                    />
                  </div>

                  <div>
                    <label className="block text-slate-400 mb-1">TTS Voice Model</label>
                    <input
                      type="text"
                      value={ttsModel}
                      onChange={(e) => setTtsModel(e.target.value)}
                      className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-3 py-2 text-white font-mono text-xs"
                    />
                  </div>

                  {/* Meta Page & IG */}
                  <div>
                    <label className="block text-slate-400 mb-1">Meta Page ID (Facebook Reels)</label>
                    <input
                      type="text"
                      value={metaPageId}
                      onChange={(e) => setMetaPageId(e.target.value)}
                      placeholder="e.g. 10482910492"
                      className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-3 py-2 text-white"
                    />
                  </div>

                  <div>
                    <label className="block text-slate-400 mb-1">Instagram Business Account ID</label>
                    <input
                      type="text"
                      value={igAccountId}
                      onChange={(e) => setIgAccountId(e.target.value)}
                      placeholder="e.g. 1784140000000"
                      className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-3 py-2 text-white"
                    />
                  </div>

                  <div className="col-span-2">
                    <label className="block text-slate-400 mb-1">Meta Long-Lived Access Token</label>
                    <input
                      type="password"
                      value={metaAccessToken}
                      onChange={(e) => setMetaAccessToken(e.target.value)}
                      placeholder="EAABwz..."
                      className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-3 py-2 text-white"
                    />
                  </div>

                  <div className="col-span-2">
                    <label className="block text-slate-400 mb-1">Public Tunnel URL (for Instagram Container Webhook)</label>
                    <input
                      type="text"
                      value={publicTunnelUrl}
                      onChange={(e) => setPublicTunnelUrl(e.target.value)}
                      placeholder="https://gta-studio.trycloudflare.com (Optional)"
                      className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl px-3 py-2 text-white"
                    />
                  </div>
                </div>

                {/* Live Hardware Engine Diagnostics */}
                <div className="bg-[#0B0D12] rounded-xl border border-[#1F2430] p-4 text-xs">
                  <div className="flex items-center gap-2 text-emerald-400 font-semibold mb-2">
                    <Cpu className="h-4 w-4" />
                    <span>Active Hardware Encoder Status</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-slate-400 font-mono text-[11px]">
                    <p>Host Device: <span className="text-white">{hardware?.device_name}</span></p>
                    <p>OS / Arch: <span className="text-white">{hardware?.os} ({hardware?.architecture})</span></p>
                    <p>FFmpeg Codec: <span className="text-emerald-400">{hardware?.ffmpeg_codec}</span></p>
                    <p>Whisper Engine: <span className="text-indigo-400">{hardware?.whisper_backend}</span></p>
                  </div>
                </div>
              </div>

              {/* Complete Reset & Storage Clean Card */}
              <div className="bg-[#141821] border border-rose-500/30 rounded-2xl p-6 shadow-xl space-y-4">
                <div className="flex items-center gap-2.5 text-rose-400">
                  <Trash2 className="h-5 w-5" />
                  <div>
                    <h2 className="text-base font-bold text-white">Complete Workspace Reset & Disk Cleanup</h2>
                    <p className="text-xs text-slate-400">Permanently delete all downloaded YouTube videos, clips, and generated assets.</p>
                  </div>
                </div>

                <div className="bg-[#0B0D12] rounded-xl border border-[#1F2430] p-4 text-xs space-y-2 text-slate-300">
                  <p className="font-semibold text-rose-300">This action will permanently delete:</p>
                  <ul className="list-disc list-inside space-y-1 text-slate-400 text-[11px]">
                    <li><strong>Downloaded Raw Videos</strong>: All raw YouTube VODs & gameplay in <code className="text-amber-300">workspace/downloads/</code></li>
                    <li><strong>Rendered Shorts Clips</strong>: All final 1080x1920 video clips in <code className="text-amber-300">workspace/renders/</code></li>
                    <li><strong>AI Assets</strong>: All generated voiceovers (.wav), topic banners, and badge overlays in <code className="text-amber-300">workspace/assets/</code></li>
                    <li><strong>Proxies & Temp Files</strong>: All 480p proxies and segment cuts in <code className="text-amber-300">workspace/proxies/</code> and <code className="text-amber-300">workspace/temp/</code></li>
                    <li><strong>Jobs History</strong>: Clears the entire jobs database in <code className="text-amber-300">workspace/jobs_db.json</code></li>
                  </ul>
                </div>

                <button
                  onClick={() => handleStopAndReset(false)}
                  disabled={isResetting}
                  className="w-full py-3.5 px-4 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs flex items-center justify-center gap-2 transition-all shadow-lg shadow-rose-950/40 disabled:opacity-50"
                >
                  <Trash2 className="h-4 w-4" />
                  <span>{isResetting ? 'Deleting All Data & Wiping Workspace...' : '🗑️ Complete Factory Reset: Delete All Downloaded Videos & Clips'}</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
