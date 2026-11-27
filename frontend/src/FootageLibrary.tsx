import { useEffect, useRef, useState } from 'react';
import { Archive, Check, Play, Search, X } from 'lucide-react';
import { Clip } from './ComparisonBoard';

import { libraryRequest as api, type Index, type LibraryView, type LibrarySetup, type Role, type SpeechLine } from './footageApi';
type Moment = Index['moments'][number];
export type { LibraryView, LibrarySetup } from './footageApi';
const roles: Role[] = ['commentary','comparison','highlight','support'];
const names: Record<Role,string> = {commentary:'Commentary',comparison:'Comparison',highlight:'Highlight pool',support:'Supporting footage'};
const button = 'rounded-lg border border-slate-700 bg-[#181e29] px-3 py-2 text-xs font-semibold text-slate-200 hover:border-slate-400 disabled:opacity-40';
const primary = 'rounded-lg bg-indigo-500 px-4 py-2 text-sm font-bold text-white hover:bg-indigo-400 disabled:opacity-40';
const field = 'rounded-lg border border-slate-700 bg-[#0d1119] px-3 py-2 text-sm text-slate-100 min-w-0';
const clock = (n: number) => Math.floor(n / 60) + ':' + String(Math.floor(n % 60)).padStart(2,'0');

function Transcript({source}: {source:string}) {
  const [lines,setLines] = useState<SpeechLine[] | null>(null);
  const [error,setError] = useState('');
  useEffect(()=>{
    let active=true;
    api<{lines:SpeechLine[]}>('/sources/'+source+'/transcript').then(result=>{
      if(active) setLines(result.lines);
    }).catch((e:Error)=>{if(active) setError(e.message);});
    return ()=>{active=false;};
  },[source]);
  return <div className="max-h-72 overflow-auto space-y-2 text-sm">
    {error || (lines===null?'Loading transcript…':!lines.length?'No intelligible dialogue was detected.':null)}
    {lines?.map((line,i)=><p key={i}><span className="text-indigo-300">{clock(line.start)} · {
      line.speaker==='game'?'Game dialogue':line.speaker==='streamer'?'Streamer':'Uncertain speaker'}</span> {line.text}</p>)}
  </div>;
}

export default function FootageLibrary({ view, onCompare, onJob, onStoryJob, onRoute, onClose, initialVoice, initialMask }: {
  view: LibraryView; onCompare: (setup: LibrarySetup) => void; onJob: (job: any) => void; onClose?: () => void;
  initialVoice?: string; initialMask?: boolean;
  onRoute?: (view: LibraryView) => void;
  onStoryJob?: (jobId: string) => void;
}) {
  const [index,setIndex] = useState<Index>({sources:[],moments:[]});
  const [source,setSource] = useState(() => {
    if (onClose) return view.source || '';
    const linked = new URLSearchParams(window.location.search).get('source');
    if (linked) return linked;
    try { return sessionStorage.getItem('master-selected-source') || ''; } catch { return ''; }
  });
  useEffect(() => {
    if (!onClose) {
      try { sessionStorage.setItem('master-selected-source', source); } catch { /* optional */ }
    }
  }, [source, onClose]);
  const [role,setRole] = useState<Role | ''>(view.role || '');
  const [address,setAddress] = useState('');
  const [query,setQuery] = useState('');
  const [unused,setUnused] = useState(false);
  const [showDismissed,setShowDismissed] = useState(false);
  const [otherFindsOpen,setOtherFindsOpen] = useState(false);
  const [preview,setPreview] = useState('');
  const [transcript,setTranscript] = useState('');
  const [edit,setEdit] = useState('');
  const [ids,setIds] = useState<string[]>(view.storyIds ?? (view.momentId ? [view.momentId] : []));
  const [kind,setKind] = useState<'highlight'|'commentary'>(view.role === 'highlight' ? 'highlight' : 'commentary');
  const [title,setTitle] = useState(view.storyTitle?.slice(0,100) || '');
  const [position,setPosition] = useState(view.project?.labels.length ?? 0);
  const [voice,setVoice] = useState(initialVoice ?? 'Charon');
  const [hideCamera,setHideCamera] = useState(initialMask ?? true);
  const [busy,setBusy] = useState('');
  const [error,setError] = useState('');
  const [pollError,setPollError] = useState('');
  const refresh = () => api<Index>('').then(setIndex);
  useEffect(() => {
    let mounted = true;
    let timer: number;
    async function poll() {
      try {
        const data = await api<Index>('');
        if (mounted) {
          setIndex(data);
          setPollError('');
          if (!onClose) setSource(current => current==='all' || data.sources.some(s=>s.id===current) ? current : data.sources[0]?.id || '');
        }
      } catch (e) { if (mounted) setPollError((e as Error).message); }
      if (mounted) timer = window.setTimeout(poll, 2200);
    }
    void poll();
    return () => { mounted = false; clearTimeout(timer); };
  }, []);
  async function run(message: string, action: () => Promise<void>) {
    setError(''); setBusy(message);
    try { await action(); } catch (e) { setError((e as Error).message); } finally { setBusy(''); }
  }
  async function scan(url: string) {
    await run('Opening source…', async () => {
      const result = await api<{id:string}>('/scan','POST',{url});
      setSource(result.id); setRole(view.role || ''); setQuery(''); setUnused(false); setShowDismissed(false); await refresh();
    });
  }
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  async function prepareLineup() {
    const {job_id} = await api<{job_id:string}>('/projects?background=true','POST',{
      ids,kind,title,tts_voice:voice,enable_watermark_masker:hideCamera,
      story_source:view.storyIds?.some(id=>ids.includes(id)) ? view.source : undefined
    });
    while (mounted.current) {
      let response: Response | undefined;
      try { response = await fetch('/api/jobs/'+job_id); } catch { /* keep the same job on reconnect */ }
      if (!mounted.current) return;
      if (response?.ok) {
        const job = await response.json();
        if (job.status==='completed') { onJob(job); return; }
        if (job.status==='failed' || job.status==='cancelled') throw new Error(job.error || job.step);
        setBusy(job.step);
      } else if (response?.status===404) {
        throw new Error('This preparation is no longer available. Retry the lineup.');
      } else {
        setBusy('Reconnecting to commentary preparation…');
      }
      await new Promise(resolve=>window.setTimeout(resolve, 1200));
    }
  }
  const lineup = ids.map(id => index.moments.find(m => m.id === id)).filter((m):m is Moment => !!m && !m.dismissed);
  const allSources = !source || source==='all';
  const fromSource = index.moments.filter(m => (allSources || m.source===source) && !!m.dismissed===showDismissed);
  const selectedSource = index.sources.find(s=>s.id===source) ?? (index.sources.length===1 ? index.sources[0] : undefined);
  const showSuggestions = !onClose && !!selectedSource?.scan_complete && !selectedSource.needs_cut_review
    && !selectedSource.active && !showDismissed && !role && !query.trim() && !unused;
  const main = selectedSource?.main_clip;
  const lead = main && fromSource.find(m=>m.id===main.id && !m.dismissed && m.role===main.role);
  const mainIds = new Set(main?.scenes?.map(s=>s.id) ?? (lead ? [lead.id] : []));
  const canCollapseFinds = showSuggestions && !!lead;
  const inDestination = (m: Moment) => !view.role || view.project || m.role===view.role ||
    (view.role==='commentary' && m.role==='support');
  const filtered = fromSource.filter(m => inDestination(m) && (!role || m.role===role) && (!unused || !m.uses.length) &&
    [m.title,m.reason,...m.tags,index.sources.find(s=>s.id===m.source)?.title].join(' ').toLowerCase().includes(query.toLowerCase()));
  if (view.project) {
    const project = view.project;
    const keywords = new Set((project.title + ' ' + (project.labels[Math.max(0,position-1)] || ''))
      .toLowerCase().match(/[a-z0-9]{3,}/g)?.filter(w => !['the','and','with','from','gta','how','this','that'].includes(w)));
    const relevance = (m: Moment) => (m.title + ' ' + m.tags.join(' ')).toLowerCase()
      .split(/[^a-z0-9]+/).reduce((score,word)=>score+Number(keywords.has(word)),0);
    filtered.sort((a,b)=>relevance(b)-relevance(a));
  }
  const visibleSources = index.sources.filter(s => !allSources ? s.id===source :
    (!onClose && index.sources.length===1) || s.active || s.error || !s.preview_url || s.needs_cut_review || !s.scan_complete);
  function toggle(m: Moment) {
    const group = m.role === 'highlight' ? 'highlight' : 'commentary';
    if (ids.includes(m.id)) { setIds(ids.filter(id=>id!==m.id)); return; }
    if (ids.length && kind!==group) { setError('Finish or clear the current lineup before starting another format.'); return; }
    if (group==='highlight' && ids.length===5) { setError('A ranked Short has up to five slots.'); return; }
    setError(''); setKind(group); setIds([...ids,m.id]);
  }
  function reorder(i: number, direction: number) {
    const next=[...ids], j=i+direction;
    [next[i],next[j]]=[next[j],next[i]]; setIds(next);
  }
  async function change(m: Moment, patch: {role?: Role; dismissed?: boolean}) {
    await run('Saving change…',async()=>{
      await api('/moments/'+m.id,'PATCH',patch); setIds(ids.filter(id=>id!==m.id)); setEdit(''); await refresh();
    });
  }
  function openComparison(m: Moment) {
    const src = index.sources.find(s=>s.id===m.source);
    if (!src?.asset || !src.preview_url || !src.duration || !src.windows) return;
    onCompare({id:m.id, question:m.title, record:m.record || m.reason, observation:m.reason,
      media:{asset:src.asset,preview_url:src.preview_url,duration:src.duration,windows:src.windows},
      sourceId:src.id,start:m.start,end:m.end});
  }
  function route(m: Moment, useStory=false) {
    if (m.role==='comparison') openComparison(useStory && main ? {...m,title:main.title || m.title,reason:main.why,record:main.record || m.record} : m);
    else onRoute?.({role:m.role==='support'?'commentary':m.role, source:m.source, momentId:m.id,
      storyIds:useStory ? main?.scenes?.map(s=>s.id) : undefined, storyTitle:useStory ? main?.title : undefined});
  }
  const destination = (m: Moment) => m.role==='highlight' ? 'Highlight' : m.role==='comparison' ? 'Comparison' : 'Explainer (commentary)';
  const overlay = !!onClose;
  return <section className="mx-auto max-w-6xl space-y-5">
    <div className="flex items-start justify-between gap-3"><div>
      <h2 className="text-2xl font-bold text-white">{overlay ? (view.project?'Find supporting footage':view.role==='highlight'?'Highlight · saved footage':view.role==='commentary'?'Explainer · saved footage':'Use saved footage') : 'Master Screen'}</h2>
      <p className="mt-1 text-sm text-slate-400">{overlay ? 'Choose from your local footage library.' : 'Find one main clip and send source footage to the editor that fits it.'}</p>
    </div>{onClose && <button aria-label="Close library" onClick={onClose} className={button}><X size={17}/></button>}</div>
    {!overlay && <form className="flex flex-wrap gap-3 items-end rounded-2xl border border-[#303749] bg-[#161b26] p-5"
      onSubmit={e=>{e.preventDefault();void scan(address);}}>
      <label className="flex-1 min-w-48 text-xs font-semibold text-slate-300">YouTube video link
        <input type="url" required className={field+' block w-full mt-2'} value={address} onChange={e=>setAddress(e.target.value)} placeholder="Paste a gameplay video link" /></label>
      <button className={primary} disabled={!!busy || !address.trim()}>Scan video</button>
    </form>}
    <div className="flex flex-wrap gap-3 items-center">
      <select aria-label="Source video" className={field+' max-w-full'} value={source} onChange={e=>setSource(e.target.value)}>
        <option value={onClose ? '' : 'all'}>All sources ({index.sources.length})</option>{index.sources.map(s=><option key={s.id} value={s.id}>{s.title}</option>)}</select>
      <label className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={unused} onChange={e=>setUnused(e.target.checked)}/> Unused only</label>
      {!overlay && <label className="flex items-center gap-2 text-sm text-slate-400"><input type="checkbox" checked={showDismissed} onChange={e=>setShowDismissed(e.target.checked)}/> Dismissed</label>}
    </div>
    {visibleSources.map(s=><div key={s.id} className="space-y-2 border-l-2 border-indigo-500 pl-4 text-sm text-slate-300">
      <strong className="text-white">{s.title}</strong>
      <div role="status">
        {s.active ? s.status_message || (s.duration ? 'Scanning footage…' : 'Preparing source…')
          : s.needs_cut_review ? 'Footage review pending' : !s.scan_complete ? 'Scan paused'
          : !s.preview_url ? 'Preview unavailable' : s.error ? 'Scan needs attention' : 'Scan complete'}
        {!!s.duration && <span className="text-slate-400"> · {clock(s.coverage)} / {clock(s.duration)} scanned</span>}
      </div>
      {(s.active || !!s.duration) && <progress aria-label={s.duration ? 'Scan coverage' : 'Preparing source'}
        className="block w-full h-1 accent-indigo-400" value={s.duration ? s.coverage : undefined} max={s.duration || 1}/>}
      {!overlay && !s.scan_complete && <p className="text-slate-400">Clip picks appear after the scanner compares the whole video.</p>}
      {s.error && <p className="text-rose-300">{s.error}</p>}
      {!s.active && (!s.scan_complete || s.needs_cut_review || !s.preview_url || s.error) && <button className={button} disabled={!!busy} onClick={()=>void scan('https://youtu.be/'+s.id)}>
        {s.needs_cut_review ? 'Review footage' : !s.preview_url && s.scan_complete ? 'Retry preview' : 'Resume scan'}
      </button>}
      {!overlay && !s.active && !!s.transcript_sections && <button className={button} onClick={()=>setTranscript(transcript===s.id?'':s.id)}>{transcript===s.id?'Hide':'View'} source transcript</button>}
      {transcript===s.id && <Transcript key={s.id} source={s.id}/>}
      {!overlay && !s.active && !s.error && s.scan_complete && s.needs_story_scan && <button className={button} disabled={!!busy} onClick={()=>void scan('https://youtu.be/'+s.id)}>Analyze full story and dialogue</button>}
      {onStoryJob && overlay && view.role==='commentary' && s.scan_complete && <button className={primary} disabled={!!busy} onClick={()=>void run('Starting full-story analysis…', async()=>{
        const job = await api<{job_id: string}>('/sources/'+s.id+'/story','POST');
        onStoryJob(job.job_id);
      })}>Explain the main story</button>}
    </div>)}
    {showSuggestions && selectedSource && (
      lead && main ? <article aria-label="Main clip" className="rounded-2xl border border-indigo-400/50 bg-[#191e30] p-5 space-y-3">
        <h3 className="font-semibold text-indigo-200">Main clip · {destination(lead)}</h3>
        <h4 className="text-xl font-bold text-white">{main.title || lead.title}</h4>
        {!main.scenes && <p className="font-mono text-sm text-slate-400">{clock(lead.start)}–{clock(lead.end)}</p>}
        <p className="text-sm text-slate-300">{main.why}</p>
        <button className={primary} disabled={!selectedSource.preview_url && lead.role==='comparison'} onClick={()=>route(lead,true)}>Open in {destination(lead)}</button>
        {(main.scenes ?? [{id:lead.id,start:lead.start,end:lead.end,purpose:'',original_line:''}]).map(scene=>
          <div key={scene.id} className="space-y-1 border-t border-slate-700 pt-2">
            <button className={button} disabled={!selectedSource.preview_url} onClick={()=>setPreview(preview===scene.id?'':scene.id)}>
              {preview===scene.id?'Close preview':'Preview source'} · {clock(scene.start)}–{clock(scene.end)}</button>
            {scene.purpose && <p className="text-sm text-slate-300">{scene.purpose}</p>}
            {scene.original_line && <p className="text-sm text-slate-400">Original audio · “{scene.original_line}”</p>}
            {preview===scene.id && selectedSource.asset && selectedSource.preview_url && selectedSource.duration && selectedSource.windows &&
              <Clip label={scene.purpose || lead.title} media={{asset:selectedSource.asset,preview_url:selectedSource.preview_url,duration:selectedSource.duration,windows:selectedSource.windows}} cut={scene}/>}
          </div>)}
      </article> : selectedSource.active ? null : selectedSource.clip_choices ?
        <p className="text-sm text-slate-300">No clip qualified as the main pick.</p> :
        <button className={button} disabled={!!busy} onClick={()=>void scan('https://youtu.be/'+selectedSource.id)}>Review clip recommendations</button>
    )}
    {busy && <p role="status" className="text-sm text-indigo-200">{busy}</p>}
    {(error || pollError) && <p role="alert" className="text-sm text-rose-300">{error || pollError}</p>}
    {canCollapseFinds && <button className={button} aria-expanded={otherFindsOpen}
      onClick={()=>setOtherFindsOpen(open=>!open)}>{otherFindsOpen ? 'Hide' : 'Show'} other finds ({fromSource.filter(m=>!mainIds.has(m.id)).length})</button>}
    <div className="flex flex-wrap gap-2" aria-label="Footage categories">
      {(['',...roles] as const).filter(r => !view.role || r===view.role || (view.role==='commentary' && r==='support')).map(r=>
        <button key={r} aria-pressed={role===r} className={button+(role===r?' !border-indigo-400 !text-indigo-200':'')}
          onClick={()=>setRole(r)}>{r ? names[r]:'All finds'} · {fromSource.filter(m=>inDestination(m) && (!r||m.role===r)).length}</button>)}
    </div>
    {(!canCollapseFinds || otherFindsOpen) && <>
    <label className="flex items-center gap-2 text-slate-400"><Search size={16}/><input aria-label="Search footage" className={field+' flex-1'} value={query}
      onChange={e=>setQuery(e.target.value)} placeholder="Find a topic, action, source or tag"/></label>
    {view.project && <label className="flex flex-wrap gap-2 items-center text-sm text-slate-300">Insert shot
      <select className={field} value={position} onChange={e=>setPosition(Number(e.target.value))}><option value={0}>Before the first scene</option>
        {view.project.labels.map((s,i)=><option key={i} value={i+1}>After scene {i+1} · {s}</option>)}</select></label>}
    {overlay && !!lineup.length && <div className="rounded-xl bg-[#171e2b] border border-indigo-500/40 p-4 space-y-3">
      <h3 className="text-sm font-bold text-white">{kind==='highlight'?'Highlight lineup · favourite first':'Commentary lineup · playback order'}</h3>
      <input className={field+' w-full'} aria-label="Project title" placeholder="Video title (optional)" value={title} maxLength={100} onChange={e=>setTitle(e.target.value)}/>
      {lineup.map((m,i)=><div key={m.id} className="flex gap-2 items-center text-sm text-slate-200">
        <span className="mr-auto">{i+1}. {m.title} · {clock(m.start)}–{clock(m.end)}
          {view.storyIds && main?.scenes?.find(scene=>scene.id===m.id)?.original_line &&
            <small className="block text-slate-400">Original audio · {main.scenes.find(scene=>scene.id===m.id)?.original_line}</small>}
        </span>
        <button className={button} aria-label={'Move up '+m.title} disabled={i===0 || !!busy} onClick={()=>reorder(i,-1)}>↑</button>
        <button className={button} aria-label={'Move down '+m.title} disabled={i===ids.length-1 || !!busy} onClick={()=>reorder(i,1)}>↓</button>
        <button className={button} aria-label={'Remove '+m.title} disabled={!!busy} onClick={()=>toggle(m)}>×</button></div>)}
      <div className="flex flex-wrap items-center gap-4 text-sm text-slate-300">
        {kind==='commentary' && <label>Narrator voice <select value={voice} className={field} onChange={e=>setVoice(e.target.value)}>
          {['Charon','Aoede','Kore','Fenrir','Puck'].map(name=><option key={name}>{name}</option>)}
        </select></label>}
        <label><input type="checkbox" checked={hideCamera} onChange={e=>setHideCamera(e.target.checked)}/> Hide facecam and logos</label>
      </div>
      <button className={primary} disabled={!!busy || (kind==='highlight'?lineup.length<2:!lineup.some(m=>m.role==='commentary'))}
        onClick={()=>void run('Queuing selected footage…', prepareLineup)}>
        {busy || (kind==='highlight'?'Prepare ranked Short':'Prepare commentary from selected clips')}</button>
      <button className={button+' ml-2'} disabled={!!busy} onClick={()=>{setIds([]);setTitle('');}}>Clear lineup</button>
    </div>}
    {!filtered.length && <div className="rounded-xl border border-dashed border-slate-700 p-8 text-center text-sm text-slate-400">
      <Archive className="mx-auto mb-2" size={22}/>{index.sources.length?'No matching moments yet.':'Your saved moments will appear here after a scan.'}</div>}
    <div className="grid gap-4 lg:grid-cols-2">{filtered.filter(m=>!canCollapseFinds || !mainIds.has(m.id)).map(m=>{
      const src=index.sources.find(s=>s.id===m.source);
      if (!src) return null;
      const media=src.duration && src.asset && src.preview_url && src.windows
        ? {duration:src.duration,asset:src.asset,preview_url:src.preview_url,windows:src.windows} : null;
      return <article key={m.id} className="rounded-xl border border-[#2b3241] bg-[#151a24] p-4 space-y-3">
        <div className="flex justify-between items-center text-xs"><span className="text-indigo-300">{names[m.role]}</span><span className="font-mono text-slate-400">{clock(m.start)}–{clock(m.end)}</span></div>
        <h3 className="text-base font-bold text-white">{m.title}</h3><p className="text-sm text-slate-300">{m.reason}</p>
        <p className="text-xs text-slate-400">{src.title}{m.tags.length>0?' · '+m.tags.join(' · '):''}</p>
        <div className="text-xs text-slate-400">{m.uses.length ? <>Used in {m.uses.map((u,i)=><a key={u.url} href={u.url} target="_blank" rel="noreferrer" className="text-indigo-300 underline">{(i?', ':'')+u.title}</a>)}</> : 'Unused'}</div>
        {preview===m.id && media && <Clip label={m.title} media={media} cut={{start:m.start,end:m.end}}/>}
        <div className="flex flex-wrap gap-2">
          <button className={button} disabled={!media} onClick={()=>setPreview(preview===m.id?'':m.id)}><Play size={12} className="inline mr-1"/>{preview===m.id?'Close preview':'Preview'}</button>
          {m.dismissed ? <button className={button} disabled={!!busy} onClick={()=>void change(m,{dismissed:false})}>Restore</button> :
            !overlay ? <button className={button} disabled={!!busy || (m.role==='comparison' && !media)} onClick={()=>route(m)}>Open in {destination(m)}</button> :
            view.project ? <button className={button} disabled={!!busy} onClick={()=>void run('Verifying supporting shot…',async()=>{
              onJob(await api('/projects/'+view.project!.job+'/'+view.project!.clip+'/support','POST',{moment_id:m.id,after:position}));})}>Insert in commentary</button> :
            m.role==='comparison' ? <button className={button} disabled={!!busy || !media} onClick={()=>openComparison(m)}>Open in Comparison</button> :
            <button className={button} disabled={!!busy} onClick={()=>toggle(m)}>{ids.includes(m.id)?<><Check size={12} className="inline"/> Selected</>:
              m.role==='highlight'?'Add to ranking':'Add to commentary'}</button>}
          {!overlay && !m.dismissed && <button className={button} onClick={()=>setEdit(edit===m.id?'':m.id)}>Organize</button>}
        </div>
        {edit===m.id && <div className="flex gap-2"><select className={field} aria-label="Move moment to" value={m.role}
          onChange={e=>void change(m,{role:e.target.value as Role})}>{roles.map(r=><option key={r} value={r}>{names[r]}</option>)}</select>
          <button disabled={!!busy} className={button} onClick={()=>void change(m,{dismissed:true})}>Dismiss</button></div>}
      </article>;
    })}</div>
    </>}
  </section>;
}
