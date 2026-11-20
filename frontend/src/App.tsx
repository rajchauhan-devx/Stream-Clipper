import { useState, useEffect, useRef } from 'react';
import {
  Zap,
  FolderPlus,
  Sliders,
  Share2,
  Settings as SettingsIcon,
  Cpu,
  Bot,
  SlidersHorizontal,
  CheckCircle2,
  Clock,
  Sparkles,
  ShieldCheck,
  Video,
  Languages,
  PlayCircle,
  TrendingUp,
  Volume2,
  RotateCw,
  Eye,
  Download,
  Check,
  ExternalLink,
  Youtube,
  Instagram,
  Facebook,
  Save,
  Square,
  Trash2,
  Terminal,
  ChevronDown,
  ChevronUp,
  Activity,
  Scissors,
  AlertCircle
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

interface Clip {
  clip_id: string;
  start_time: number;
  end_time: number;
  duration: number;
  virality_score: number;
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
  const [activeTab, setActiveTab] = useState<'new_project' | 'studio' | 'upload' | 'settings'>('new_project');
  const [operatingMode, setOperatingMode] = useState<'auto_pilot' | 'manual_studio'>('auto_pilot');
  const [hardware, setHardware] = useState<HardwareStatus | null>(null);

  // Form states
  const [urlOrFile, setUrlOrFile] = useState('');
  const [language, setLanguage] = useState('hinglish');
  const [clipLength, setClipLength] = useState('30s-55s');
  const [clipCount, setClipCount] = useState(3);
  const [copyrightGuard, setCopyrightGuard] = useState(true);
  const [stripStreamerVoice, setStripStreamerVoice] = useState(false);
  const [voiceoverPacing, setVoiceoverPacing] = useState<'hook_only' | 'full_commentary'>('hook_only');
  const [enableCalloutOverlay, setEnableCalloutOverlay] = useState(false);
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
  const [isRegeneratingVoice, setIsRegeneratingVoice] = useState(false);
  const [isRenderingClip, setIsRenderingClip] = useState(false);
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
  }, []);

  const handleLaunch = async () => {
    if (!urlOrFile) {
      alert('Please enter a YouTube link or file path to raw gameplay.');
      return;
    }
    setIsLaunching(true);
    setPipelineError(null);
    setProgressPct(5);
    setProgressMsg('Registering job pipeline...');
    setPipelineStep('ingesting');
    const initialTime = new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    setActivityLogs([{
      timestamp: initialTime,
      message: '🚀 Initializing job pipeline on local M4 engine...'
    }]);

    try {
      const res = await fetch('/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url_or_path: urlOrFile,
          mode: operatingMode,
          target_language: language,
          clip_length_range: clipLength,
          clip_count: clipCount,
          copyright_guard: copyrightGuard,
          strip_streamer_voice: stripStreamerVoice,
          voiceover_pacing: voiceoverPacing,
          enable_callout_overlay: enableCalloutOverlay,
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
                if (operatingMode === 'manual_studio') {
                  setActiveTab('studio');
                }
              }
            }
          } else if (msg.event === 'clip_rendered') {
            setIsRenderingClip(false);
            setClips((prev) =>
              prev.map((c) =>
                c.clip_id === msg.clip_id
                  ? { ...c, preview_url: msg.preview_url, status: 'rendered' }
                  : c
              )
            );
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
        '🛑 Are you sure you want to STOP the pipeline?\n\nThis will immediately cancel video processing and permanently DELETE all downloaded raw videos, proxies, and temporary files from disk.'
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
      setProgressMsg('Pipeline stopped. All downloads wiped.');
      setPipelineError(null);
      setPipelineStep('idle');
      setIsLaunching(false);
      setClips([]);
      setActivityLogs((prev) => [
        ...prev,
        {
          timestamp: new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          message: `🛑 Pipeline stopped by user. Deleted all downloads and freed ${data.freed_mb || 0} MB disk space.`,
        },
      ]);

      setResetBanner(
        `✅ Pipeline halted! Deleted all downloads and freed ${data.freed_mb || 0} MB disk space.`
      );
      setTimeout(() => setResetBanner(null), 8000);
    } catch (err) {
      console.error('Reset error:', err);
      alert('Error resetting pipeline.');
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

  const handleRegenerateVoice = async () => {
    if (!activeJobId || clips.length === 0) return;
    const currentClip = clips[selectedClipIndex];
    setIsRegeneratingVoice(true);
    try {
      const res = await fetch(`/api/jobs/${activeJobId}/clips/${currentClip.clip_id}/regenerate-voice`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data.voice_path) {
        handleUpdateCurrentClip({ voice_path: data.voice_path });
        alert(`New voiceover synthesized successfully for ${currentClip.clip_id}!`);
      }
    } catch (e) {
      console.error(e);
      alert('Failed to regenerate voice.');
    } finally {
      setIsRegeneratingVoice(false);
    }
  };

  const handleRenderClip = async () => {
    if (!activeJobId || !activeClip) return;
    setIsRenderingClip(true);
    try {
      await fetch(`/api/jobs/${activeJobId}/clips/${activeClip.clip_id}/render`, {
        method: 'POST',
      });
    } catch (e) {
      console.error(e);
      alert('Failed to trigger clip render.');
      setIsRenderingClip(false);
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
      a.href = activeClip.preview_url;
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
              <span>1. New Project</span>
            </button>

            <button
              onClick={() => setActiveTab('studio')}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === 'studio'
                  ? 'bg-indigo-600/15 text-indigo-400 border border-indigo-500/30'
                  : 'text-slate-400 hover:text-white hover:bg-[#141821]'
              }`}
            >
              <Sliders className="h-4 w-4" />
              <span>2. AI Studio</span>
              {clips.length > 0 && (
                <span className="ml-auto text-[10px] font-bold px-1.5 py-0.5 rounded bg-indigo-600 text-white">
                  {clips.length}
                </span>
              )}
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
              <span>3. Upload Hub</span>
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
              <span>4. Settings</span>
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
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Operating Mode:
            </span>
            <div className="flex bg-[#141821] p-1 rounded-xl border border-[#1F2430]">
              <button
                onClick={() => setOperatingMode('auto_pilot')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  operatingMode === 'auto_pilot'
                    ? 'bg-gradient-to-r from-indigo-600 to-indigo-500 text-white shadow-md shadow-indigo-600/30'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <Bot className="h-3.5 w-3.5" />
                <span>🤖 Auto-Pilot</span>
              </button>
              <button
                onClick={() => setOperatingMode('manual_studio')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  operatingMode === 'manual_studio'
                    ? 'bg-gradient-to-r from-emerald-600 to-emerald-500 text-white shadow-md shadow-emerald-600/30'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <SlidersHorizontal className="h-3.5 w-3.5" />
                <span>🎛️ Manual Studio</span>
              </button>
            </div>
          </div>

          <div className="flex items-center gap-3 text-xs">
            {(activeJobId || pipelineStep !== 'idle' || isLaunching) && (
              <button
                onClick={() => handleStopAndReset(false)}
                disabled={isResetting}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-500/20 border border-rose-500/40 text-rose-300 hover:bg-rose-500 hover:text-white transition-all font-semibold shadow-md shadow-rose-950/30 disabled:opacity-50"
                title="Immediately stop pipeline and delete all downloaded video files"
              >
                <Square className="h-3 w-3 fill-current text-rose-400" />
                <span>{isResetting ? 'Wiping...' : '🛑 Stop & Reset'}</span>
              </button>
            )}

            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#141821] border border-[#1F2430] text-slate-300">
              <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
              <span>{isAdc ? `🟢 Google Cloud ADC (${adcProject})` : `${directorModel} Ready`}</span>
            </div>
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
                        <Volume2 className="h-4 w-4 text-indigo-400" />
                        <span className="text-xs font-semibold">Mute Streamer</span>
                      </div>
                      <p className="text-[10px] text-slate-500 leading-tight">Keep OFF for walkthroughs to keep in-game character speech</p>
                    </div>
                    <div className="flex items-center justify-between mt-2">
                      <span className="text-[11px] text-slate-400">Strip Mic Speech</span>
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
                <div className="flex items-center justify-between p-3.5 bg-[#0B0D12] rounded-xl border border-[#1F2430] mt-4">
                  <div className="flex items-center gap-2.5">
                    <Sparkles className="h-4 w-4 text-amber-400" />
                    <div>
                      <span className="text-xs font-bold text-white">Voiceover Pacing (AI Hook Strategy)</span>
                      <p className="text-[10px] text-slate-400">Gemini decides an attention-grabbing hook in the first 3–6s, then lets raw gameplay sound take over.</p>
                    </div>
                  </div>
                  <div className="flex bg-[#141821] p-1 rounded-lg border border-[#1F2430]">
                    <button
                      onClick={() => setVoiceoverPacing('hook_only')}
                      className={`px-3 py-1 rounded text-xs font-semibold transition-all ${
                        voiceoverPacing === 'hook_only'
                          ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      ⚡ 3–6s Viral Hook Only
                    </button>
                    <button
                      onClick={() => setVoiceoverPacing('full_commentary')}
                      className={`px-3 py-1 rounded text-xs font-semibold transition-all ${
                        voiceoverPacing === 'full_commentary'
                          ? 'bg-indigo-600/30 text-indigo-300 border border-indigo-500/40'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      🎙️ Full Clip Commentary
                    </button>
                  </div>
                </div>

                {/* Visual Graphics Options */}
                <div className="flex items-center justify-between p-3.5 bg-[#0B0D12] rounded-xl border border-[#1F2430] mt-3">
                  <div className="flex items-center gap-2.5">
                    <Sparkles className="h-4 w-4 text-purple-400" />
                    <div>
                      <span className="text-xs font-bold text-white">Top Graphic Callout Badges</span>
                      <p className="text-[10px] text-slate-400">Burn in artificial callout boxes/stickers across the top (Default OFF for 100% clean video with subtitles only).</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-semibold text-slate-400">{enableCalloutOverlay ? 'Show Stickers' : 'Clean (No Badges)'}</span>
                    <button
                      onClick={() => setEnableCalloutOverlay(!enableCalloutOverlay)}
                      className={`w-11 h-6 flex items-center rounded-full p-1 transition-colors ${
                        enableCalloutOverlay ? 'bg-purple-600' : 'bg-slate-700'
                      }`}
                    >
                      <div
                        className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${
                          enableCalloutOverlay ? 'translate-x-5' : 'translate-x-0'
                        }`}
                      />
                    </button>
                  </div>
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
                    onClick={handleLaunch}
                    disabled={isLaunching || isResetting}
                    className="flex-1 w-full bg-gradient-to-r from-indigo-600 via-indigo-500 to-emerald-500 hover:opacity-95 text-white font-bold py-3.5 px-6 rounded-xl shadow-lg shadow-indigo-600/20 flex items-center justify-center gap-2 transition-all disabled:opacity-50"
                  >
                    <PlayCircle className="h-5 w-5" />
                    <span>{isLaunching ? 'INITIALIZING PIPELINE...' : '🚀 LAUNCH PIPELINE'}</span>
                  </button>

                  {(activeJobId || pipelineStep !== 'idle' || isLaunching || clips.length > 0) && (
                    <button
                      onClick={() => handleStopAndReset(false)}
                      disabled={isResetting}
                      className="w-full sm:w-auto px-5 py-3.5 bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 hover:text-white border border-rose-500/40 rounded-xl font-bold flex items-center justify-center gap-2 transition-all shadow-lg shadow-rose-950/40 disabled:opacity-50"
                      title="Abort processing and delete all downloaded video files, proxies, and temporary files"
                    >
                      <Square className="h-4 w-4 fill-current text-rose-400" />
                      <span>{isResetting ? 'STOPPING & WIPING...' : '🛑 STOP & RESET'}</span>
                    </button>
                  )}
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
                      <span className="text-xs font-bold text-white uppercase tracking-tight">
                        Clip #{idx + 1} ({clip.duration}s)
                      </span>
                      <div className="flex items-center gap-1 bg-emerald-500/15 border border-emerald-500/30 px-2 py-0.5 rounded-full">
                        <TrendingUp className="h-3 w-3 text-emerald-400" />
                        <span className="text-[10px] font-bold text-emerald-400 font-mono">
                          {clip.virality_score}/100
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
                          {isRenderingClip ? '⏳ Rendering 60fps Short...' : 'Click "Render This Short" to view'}
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

                  {/* Active Hook Sticker Overlay Preview */}
                  {activeClip && !activeClip.preview_url && (
                    <div className="absolute top-16 inset-x-4 pointer-events-none text-center">
                      <div className="inline-block bg-[#131821]/90 border-2 border-indigo-500 rounded-xl px-4 py-2 shadow-2xl">
                        <p className="text-xs font-black text-white tracking-wide uppercase">
                          {activeClip.hook_text}
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Right Panel: Script Editor, Voice & Crop Controls */}
              {activeClip && (
                <div className="w-96 shrink-0 bg-[#141821] rounded-2xl border border-[#1F2430] p-5 flex flex-col gap-4 overflow-y-auto">
                  <div className="flex items-center justify-between pb-2 border-b border-[#1F2430]">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                      Clip Refinement ({activeClip.clip_id})
                    </h3>
                    <span className="text-[10px] text-emerald-400 font-mono">
                      {activeClip.duration}s
                    </span>
                  </div>

                  {/* Commentary Script Box */}
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                      Commentary Script (Gemini Director)
                    </label>
                    <textarea
                      rows={4}
                      value={activeClip.commentary_script}
                      onChange={(e) => handleUpdateCurrentClip({ commentary_script: e.target.value })}
                      className="w-full bg-[#0B0D12] border border-[#1F2430] rounded-xl p-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 resize-none font-sans leading-relaxed"
                    />
                    <div className="flex gap-2 mt-2">
                      <select
                        value={activeClip.tts_voice || 'Puck'}
                        onChange={(e) => handleUpdateCurrentClip({ tts_voice: e.target.value })}
                        className="w-1/2 bg-[#0B0D12] border border-[#1F2430] rounded-lg px-2 py-1.5 text-xs text-white"
                      >
                        <option value="Puck">Voice: Puck (Energetic)</option>
                        <option value="Fenrir">Voice: Fenrir (Deep Hype)</option>
                        <option value="Zephyr">Voice: Zephyr (Fast)</option>
                        <option value="Aoede">Voice: Aoede (Dramatic)</option>
                        <option value="Kore">Voice: Kore (Chill)</option>
                      </select>
                      <button
                        onClick={handleRegenerateVoice}
                        disabled={isRegeneratingVoice}
                        className="w-1/2 flex items-center justify-center gap-1.5 py-1.5 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/40 text-indigo-300 text-xs font-semibold transition-all disabled:opacity-50"
                      >
                        <RotateCw className={`h-3 w-3 ${isRegeneratingVoice ? 'animate-spin' : ''}`} />
                        <span>{isRegeneratingVoice ? 'Generating...' : 'Re-Voice'}</span>
                      </button>
                    </div>
                  </div>

                  {/* Crop Mode Switcher */}
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                      9:16 Crop Mode
                    </label>
                    <div className="grid grid-cols-3 gap-2">
                      {(['action_track', 'facecam_split', 'center_zoom'] as const).map((mode) => (
                        <button
                          key={mode}
                          onClick={() => handleUpdateCurrentClip({ crop_mode: mode })}
                          className={`p-2 rounded-lg border text-[11px] font-medium text-center transition-colors ${
                            activeClip.crop_mode === mode
                              ? 'bg-indigo-600/20 border-indigo-500 text-indigo-300 font-bold'
                              : 'bg-[#0B0D12] border-[#1F2430] text-slate-400 hover:text-white'
                          }`}
                        >
                          {mode === 'action_track' && 'Action Pan'}
                          {mode === 'facecam_split' && 'Face Split'}
                          {mode === 'center_zoom' && 'Center Blur'}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Caption Style Presets */}
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                      Caption Style Preset
                    </label>
                    <div className="grid grid-cols-3 gap-2">
                      <button
                        onClick={() => handleUpdateCurrentClip({ caption_style: 'hormozi_yellow' })}
                        className={`p-2 rounded-lg border text-[11px] font-medium text-center transition-colors ${
                          activeClip.caption_style === 'hormozi_yellow'
                            ? 'bg-amber-500/20 border-amber-500 text-amber-300 font-bold'
                            : 'bg-[#0B0D12] border-[#1F2430] text-slate-400'
                        }`}
                      >
                        Hormozi Yellow
                      </button>
                      <button
                        onClick={() => handleUpdateCurrentClip({ caption_style: 'neon_cyan' })}
                        className={`p-2 rounded-lg border text-[11px] font-medium text-center transition-colors ${
                          activeClip.caption_style === 'neon_cyan'
                            ? 'bg-cyan-500/20 border-cyan-500 text-cyan-300 font-bold'
                            : 'bg-[#0B0D12] border-[#1F2430] text-slate-400'
                        }`}
                      >
                        Neon Cyan
                      </button>
                      <button
                        onClick={() => handleUpdateCurrentClip({ caption_style: 'clean_white' })}
                        className={`p-2 rounded-lg border text-[11px] font-medium text-center transition-colors ${
                          activeClip.caption_style === 'clean_white'
                            ? 'bg-white/20 border-white text-white font-bold'
                            : 'bg-[#0B0D12] border-[#1F2430] text-slate-400'
                        }`}
                      >
                        Clean White
                      </button>
                    </div>
                  </div>

                  {/* Callout Overlay Graphic Preview */}
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                      Generated Callout Overlay
                    </label>
                    <div className="p-3 bg-[#0B0D12] rounded-xl border border-[#1F2430] text-center">
                      <div className="inline-block bg-[#131821] border border-indigo-500 rounded-lg px-3 py-1.5 text-xs font-bold text-white uppercase">
                        {activeClip.hook_text}
                      </div>
                      <p className="text-[10px] text-slate-500 mt-2 font-mono">
                        Prompt: {activeClip.overlay_prompt}
                      </p>
                    </div>
                  </div>

                  {/* Single Clip Render Action Button */}
                  <div className="pt-2">
                    <button
                      onClick={handleRenderClip}
                      disabled={isRenderingClip}
                      className="w-full bg-gradient-to-r from-emerald-600 to-indigo-600 hover:opacity-95 text-white font-bold py-3 px-4 rounded-xl shadow-lg shadow-emerald-600/20 flex items-center justify-center gap-2 text-xs transition-all disabled:opacity-50"
                    >
                      <Video className={`h-4 w-4 ${isRenderingClip ? 'animate-pulse' : ''}`} />
                      <span>{isRenderingClip ? 'Hardware Rendering Short...' : '🚀 Render This Short (1080x1920 60fps)'}</span>
                    </button>
                    {activeClip.preview_url && (
                      <p className="text-[10px] text-emerald-400 text-center mt-2 font-mono">
                        ✓ Rendered & Ready in Upload Hub
                      </p>
                    )}
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
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
