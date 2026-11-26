import { libraryRequest, type Index, type LibrarySetup } from './footageApi';
import { useEffect, useRef, useState } from 'react';

type Game = 'gta5' | 'gta4';
type Range = { start: number; end: number };
type Media = { asset: string; duration: number; preview_url: string; windows: number };
type Topic = Range & { media?: Media; libraryId?: string; id: string; question: string; observation: string; record: string };
type Card = {
  selected: boolean; six: Range; older?: Range; recording?: Media; filename?: string;
  note?: string; rendered?: string;
};
type Board = {
  url: string; game: Game; source?: Media; cursor: number; topics: Topic[]; cards: Record<string, Card>;
};
export const comparisonDraftKey = 'comparison-recording-board-v1';
const emptyBoard: Board = { url: '', game: 'gta5', cursor: 0, topics: [], cards: {} };
const shell = 'rounded-2xl border border-[#29303e] bg-[#141821] p-5 space-y-4';
const field = 'rounded-lg bg-[#0b0e15] border border-[#354050] px-3 py-2 text-sm text-white';
const primary = 'rounded-lg bg-lime-300 px-4 py-2 text-sm font-bold text-slate-950 hover:bg-lime-200 disabled:opacity-40';
const secondary = 'rounded-lg border border-slate-600 px-3 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800 disabled:opacity-40';
const time = (n: number) => `${Math.floor(n / 60)}:${Math.floor(n % 60).toString().padStart(2, '0')}`;
const valid = (cut: Range, duration: number) =>
  Number.isFinite(cut.start) && Number.isFinite(cut.end) && cut.start >= 0 && cut.end <= duration &&
  cut.end - cut.start >= 5 && cut.end - cut.start <= 60;

function restore(): Board {
  try {
    const draft = JSON.parse(localStorage.getItem(comparisonDraftKey) || 'null');
    if (draft && Array.isArray(draft.topics) && draft.cards) return draft;
  } catch { /* A fresh workspace can start without browser storage. */ }
  return emptyBoard;
}

async function request<T>(route: string, payload: unknown): Promise<T> {
  const form = payload instanceof FormData;
  const res = await fetch('/api/comparison/' + route, {
    method: 'POST', headers: form ? undefined : { 'Content-Type': 'application/json' },
    body: form ? payload : JSON.stringify(payload),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : `Unable to complete the request (${res.status}).`);
  return data as T;
}

export function Clip({ media, cut, label, onEdit, disabled }: {
  media: Media; cut: Range; label: string; onEdit?: (v: Range) => void; disabled?: boolean;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [fullSource, setFullSource] = useState(false);
  useEffect(() => {
    const el = video.current;
    if (!fullSource && el && el.readyState >= 1 && Number.isFinite(cut.start)) {
      el.pause();
      el.currentTime = Math.max(0, cut.start);
    }
  }, [media.asset, cut.start, cut.end, fullSource]);
  return <div className="min-w-0 space-y-2">
    <span className="text-xs font-bold text-slate-300">{label}</span>
    <video ref={video} key={media.asset} src={fullSource ? media.preview_url : media.preview_url + '#t=' + Math.max(0, cut.start || 0)}
      controls playsInline preload="metadata" aria-label={label} className="aspect-video w-full bg-black rounded-lg"
      onPlay={e => { const v = e.currentTarget; if (!fullSource && (v.currentTime >= cut.end - 0.08 || v.currentTime < cut.start)) v.currentTime = cut.start; }}
      onTimeUpdate={e => { const v = e.currentTarget; if (!fullSource && !v.paused && v.currentTime >= cut.end) v.pause(); }} />
    {onEdit && <div className="flex gap-3">{(['start', 'end'] as const).map(key =>
      <label key={key} className="text-xs text-slate-400">{key === 'start' ? 'Start' : 'End'} (s)
        <input type="number" min={0} max={media.duration} step="0.01" disabled={disabled}
          className={field + ' ml-1 w-24'} value={Number.isFinite(cut[key]) ? cut[key] : ''}
          onChange={e => onEdit({ ...cut, [key]: e.target.valueAsNumber })} /></label>)}</div>}
    {onEdit && <div className="flex flex-wrap gap-3 text-xs text-lime-200">
      <button type="button" disabled={disabled} onClick={() => setFullSource(v => !v)}>{fullSource ? 'Preview cut' : 'Browse full footage'}</button>
      {fullSource && (['start','end'] as const).map(key => <button key={key} disabled={disabled}
        onClick={() => onEdit({ ...cut, [key]: Math.min(media.duration, Number((video.current?.currentTime ?? 0).toFixed(2))) })}>
        Set {key} here</button>)}
    </div>}
    {onEdit && !valid(cut, media.duration) && <p className="text-xs text-amber-300">Choose 5–60 seconds within {time(media.duration)} of footage.</p>}
  </div>;
}

type Result = { preview_url: string; comp_id: string };
export default function ComparisonBoard({ visible, onRender, saved, onConsumed, onLibrary }: { saved: LibrarySetup | null; onConsumed: () => void; onLibrary: () => void; visible: boolean; onRender: (result: Result) => void }) {
  const [board, setBoard] = useState<Board>(restore);
  const [url, setUrl] = useState(board.url);
  const [game, setGame] = useState<Game>(board.game);
  const [format, setFormat] = useState('shorts_split');
  const [voice, setVoice] = useState('Charon');
  const [scanning, setScanning] = useState('');
  const [scanError, setScanError] = useState('');
  const [preview, setPreview] = useState('');
  const [busy, setBusy] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const gameName = board.game === 'gta5' ? 'GTA V' : 'GTA IV';
  useEffect(() => {
    try { localStorage.setItem(comparisonDraftKey, JSON.stringify(board)); } catch { /* Remain usable in memory. */ }
  }, [board]);

  useEffect(() => {
    if (!saved) return;
    setBoard(b => {
      const topic = {...saved, libraryId:saved.id};
      const existing = b.cards[topic.id];
      return {...b, source:b.source || saved.media, topics:[...b.topics.filter(t=>t.id!==topic.id),topic],
        cards:{...b.cards,[topic.id]:{...existing,six:existing?.six ?? {start:topic.start,end:topic.end},selected:true}}};
    });
    onConsumed();
  }, [saved, onConsumed]);

  function updateCard(id: string, patch: Partial<Card>) {
    setBoard(b => ({ ...b, cards: { ...b.cards, [id]: { ...b.cards[id], ...patch } } }));
  }
  async function scan() {
    setScanError('');
    const sameBoard = board.url === url.trim() && board.game === game;
    if (!sameBoard && Object.values(board.cards).some(c => c.selected) &&
        !window.confirm('Replace the current topic cards with a new scan? Your exported videos stay in the gallery.')) return;
    try {
      setScanning('Opening the saved scan…');
      const { id } = await libraryRequest<{ id: string }>('/scan', 'POST', { url: url.trim() });
      if (!sameBoard) {
        setPreview(''); setErrors({});
        setBoard({ ...emptyBoard, url: url.trim(), game });
      }
      while (true) {
        const index = await libraryRequest<Index>('');
        const source = index.sources.find(s => s.id === id);
        if (!source) throw new Error('Source no longer exists in the library.');
        if (!source.needs_cut_review && source.asset && source.preview_url && source.duration && source.windows) {
          const media = { asset: source.asset, preview_url: source.preview_url, duration: source.duration, windows: source.windows };
          const topics = index.moments.filter(m => m.source === id && m.role === 'comparison' && !m.dismissed)
            .map(m => ({ id: m.id, libraryId: m.id, start: m.start, end: m.end, media,
              question: m.title, observation: m.reason, record: m.record || m.reason }));
          setBoard(b => ({ ...b, source: media, cursor: source.cursor,
            topics: [...b.topics.filter(t => b.cards[t.id]?.selected && !topics.some(m => m.id === t.id)), ...topics] }));
        }
        if (source.cursor === source.windows && !source.needs_cut_review) break;
        if (source.error) throw new Error(source.error);
        if (!source.active) throw new Error('Scan paused. Resume to continue from the last saved section.');
        setScanning(source.needs_cut_review ? 'Reviewing saved cuts against the footage…' : source.windows ? 'Examining section ' + (source.cursor + 1) + ' of ' + source.windows + '…' : 'Preparing the source video…');
        await new Promise(resolve => setTimeout(resolve, 2200));
      }
    } catch (e) { setScanError((e as Error).message); }
    finally { setScanning(''); }
  }

  async function work(id: string, status: string, action: () => Promise<void>) {
    setBusy(p => ({ ...p, [id]: status })); setErrors(p => ({ ...p, [id]: '' }));
    try { await action(); } catch (e) { setErrors(p => ({ ...p, [id]: (e as Error).message })); }
    finally { setBusy(p => ({ ...p, [id]: '' })); }
  }

  async function match(t: Topic, media: Media) {
    const { match } = await request<{ match: (Range & { reason: string }) | null }>('match', {
      topic: t.question, base_game: board.game, gta6: { asset: (t.media || board.source!).asset, ...board.cards[t.id].six }, recording: media.asset,
    });
    updateCard(t.id, match ? { older: { start: match.start, end: match.end }, note: match.reason, rendered: undefined }
      : { note: 'No matching attempt found. Review the recording and set the cut manually, or upload another attempt.' });
  }

  function upload(t: Topic, file: File) {
    void work(t.id, 'Uploading recording…', async () => {
      const form = new FormData(); form.append('file', file);
      const saved = await request<{ asset: string }>('upload-recording', form);
      const media = await request<Media>('recording', saved);
      updateCard(t.id, { recording: media, filename: file.name, older: { start: 0, end: Math.min(15, media.duration) }, note: '', rendered: undefined });
      setBusy(p => ({ ...p, [t.id]: 'Finding the matching attempt…' }));
      await match(t, media);
    });
  }

  function render(t: Topic, card: Card) {
    void work(t.id, 'Reviewing both cuts, writing commentary and rendering…', async () => {
      const result = await request<Result>('render-pair', {
        library_id:t.libraryId, topic: t.question, base_game: board.game, format, tts_voice: voice,
        gta6: { asset: (t.media || board.source!).asset, ...card.six }, older: { asset: card.recording!.asset, ...card.older },
      });
      updateCard(t.id, { rendered: result.preview_url }); onRender(result);
    });
  }
  if (!visible) return null;
  const selected = board.topics.filter(t => board.cards[t.id]?.selected);
  const canResume = board.source && board.cursor < board.source.windows && url.trim() === board.url && game === board.game;
  return <section className="max-w-7xl mx-auto space-y-5 mb-6">
    <div className={shell}>
      <div className="flex items-center justify-between gap-2"><h2 className="text-xl font-bold text-white">GTA Comparison Studio</h2><button className={secondary} onClick={onLibrary}>Saved setups</button></div>
      <p className="text-sm text-slate-400">Scan GTA VI footage, pick moments to recreate, and pair each one with your recording.</p>
      <form className="flex flex-wrap gap-3 items-end" onSubmit={e => { e.preventDefault(); void scan(); }}>
        <label className="flex-1 min-w-48 text-xs text-slate-300">GTA VI YouTube link
          <input required type="url" value={url} disabled={!!scanning} onChange={e => setUrl(e.target.value)}
            placeholder="https://youtu.be/…" className={field + ' block w-full mt-1'} /></label>
        <label className="text-xs text-slate-300">Game to record
          <select className={field + ' block mt-1'} disabled={!!scanning} value={game} onChange={e => setGame(e.target.value as Game)}>
            <option value="gta5">GTA V</option><option value="gta4">GTA IV</option></select></label>
        <button className={primary} disabled={!url.trim() || !!scanning || Object.values(busy).some(Boolean)}>{canResume ? 'Resume scan' : 'Scan video'}</button>
      </form>
      {scanning && <p role="status" className="text-sm text-lime-200">{scanning}</p>}
      {scanError && <p role="alert" className="text-sm text-rose-300">{scanError}</p>}
    </div>
    {board.source && <div className={shell}>
      <h3 className="font-semibold text-white">Comparison topics <span className="text-slate-400">({board.topics.length})</span></h3>
      {!board.topics.length && <p className="text-sm text-slate-400">{board.cursor === board.source.windows ? 'No reproducible actions found in this video.' : 'Suggestions appear as each section finishes.'}</p>}
      {board.topics.map(t => <div key={t.id} className="border-t border-slate-700/60 pt-3 space-y-2">
        <div className="flex justify-between items-start gap-3">
          <label className="flex items-start gap-3 text-sm text-white cursor-pointer">
            <input type="checkbox" className="mt-1 accent-lime-300" checked={!!board.cards[t.id]?.selected} disabled={!!busy[t.id]}
              onChange={e => updateCard(t.id, { six: board.cards[t.id]?.six ?? { start: t.start, end: t.end }, selected: e.target.checked })} />
            <span><strong>{t.question}</strong><span className="block text-slate-400 mt-1">{t.observation}</span></span></label>
          <button className={secondary + ' whitespace-nowrap'} onClick={() => setPreview(preview === t.id ? '' : t.id)}>
            {preview === t.id ? 'Close' : 'Preview'} · {time(t.start)}–{time(t.end)}</button>
        </div>
        {preview === t.id && <div className="max-w-lg"><Clip media={t.media || board.source!} cut={t} label="GTA VI moment" /></div>}
      </div>)}
    </div>}
    {!!selected.length && <div className="flex flex-wrap items-center gap-4">
      <h3 className="font-bold text-white mr-auto">Selected comparisons ({selected.length})</h3>
      <select aria-label="Export format" className={field} value={format} onChange={e => setFormat(e.target.value)}>
        <option value="shorts_split">9:16 Short</option><option value="long_side_by_side">16:9 Landscape</option></select>
      <select aria-label="Narrator" className={field} value={voice} onChange={e => setVoice(e.target.value)}>
        {['Charon','Aoede','Kore','Fenrir','Puck'].map(v => <option key={v}>{v}</option>)}</select>
    </div>}
    {selected.map(t => {
      const c = board.cards[t.id], locked = !!busy[t.id], sixValid = valid(c.six, (t.media || board.source!).duration);
      const edit = (patch: Partial<Card>) => { updateCard(t.id, { ...patch, note: '', rendered: undefined }); setErrors(p => ({ ...p, [t.id]: '' })); };
      return <article key={t.id} className={shell}>
        <h4 className="text-lg font-bold text-white">{t.question}</h4>
        <p className="text-sm text-slate-300"><strong className="text-lime-200">What to record in {gameName}</strong><br />{t.record}</p>
        <div className="grid md:grid-cols-2 gap-5">
          <Clip media={t.media || board.source!} cut={c.six} label="GTA VI reference" disabled={locked} onEdit={six => edit({ six })} />
          <div className="space-y-3">
            {c.recording && c.older && <Clip media={c.recording} cut={c.older} label={gameName + ' · ' + c.filename} disabled={locked} onEdit={older => edit({ older })} />}
            <label className={secondary + ' inline-block cursor-pointer focus-within:ring-2 focus-within:ring-lime-300'}>
              {c.recording ? 'Replace' : 'Upload'} {gameName} recording
              <input type="file" accept="video/*,.mkv" className="sr-only" disabled={locked || !sixValid}
                onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) upload(t, f); }} /></label>
            {c.recording && <button className={secondary + ' ml-2'} disabled={locked || !sixValid} onClick={() => void work(t.id, 'Finding the matching attempt…', () => match(t, c.recording!))}>Find match again</button>}
          </div>
        </div>
        {c.note && <p className="text-sm text-slate-300">{c.note}</p>}
        {errors[t.id] && <p role="alert" className="text-sm text-rose-300">{errors[t.id]}</p>}
        {locked && <p role="status" className="text-sm text-lime-200">{busy[t.id]}</p>}
        {c.recording && <button className={primary} disabled={locked || !sixValid || !c.older || !valid(c.older, c.recording.duration)}
          onClick={() => render(t, c)}>Approve cuts &amp; render</button>}
        {c.rendered && <video aria-label={'Finished comparison: ' + t.question} className="max-h-96 max-w-full rounded-lg" src={c.rendered} controls playsInline preload="metadata" />}
      </article>;
    })}
  </section>;
}
