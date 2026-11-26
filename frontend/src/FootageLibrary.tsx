import { useEffect, useState } from 'react';
import { Archive, Check, Play, Search, X } from 'lucide-react';
import { Clip } from './ComparisonBoard';

import { libraryRequest as api, type Index, type LibraryView, type LibrarySetup, type Role } from './footageApi';
type Moment = Index['moments'][number];
export type { LibraryView, LibrarySetup } from './footageApi';
const roles: Role[] = ['commentary','comparison','highlight','support'];
const names: Record<Role,string> = {commentary:'Commentary',comparison:'Comparison',highlight:'Highlight pool',support:'Supporting footage'};
const button = 'rounded-lg border border-slate-700 bg-[#181e29] px-3 py-2 text-xs font-semibold text-slate-200 hover:border-slate-400 disabled:opacity-40';
const primary = 'rounded-lg bg-indigo-500 px-4 py-2 text-sm font-bold text-white hover:bg-indigo-400 disabled:opacity-40';
const field = 'rounded-lg border border-slate-700 bg-[#0d1119] px-3 py-2 text-sm text-slate-100 min-w-0';
const clock = (n: number) => Math.floor(n / 60) + ':' + String(Math.floor(n % 60)).padStart(2,'0');

export default function FootageLibrary({ view, onCompare, onJob, onClose }: {
  view: LibraryView; onCompare: (setup: LibrarySetup) => void; onJob: (job: any) => void; onClose?: () => void;
}) {
  const [index,setIndex] = useState<Index>({sources:[],moments:[]});
  const [source,setSource] = useState(() => {
    if (onClose) return view.source || '';
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
  const [preview,setPreview] = useState('');
  const [edit,setEdit] = useState('');
  const [ids,setIds] = useState<string[]>([]);
  const [kind,setKind] = useState<'highlight'|'commentary'>(view.role === 'highlight' ? 'highlight' : 'commentary');
  const [title,setTitle] = useState('');
  const [position,setPosition] = useState(view.project?.labels.length ?? 0);
  const [busy,setBusy] = useState('');
  const [error,setError] = useState('');
  const refresh = () => api<Index>('').then(setIndex);
  useEffect(() => {
    let mounted = true;
    let timer: number;
    async function poll() {
      try {
        const data = await api<Index>('');
        if (mounted) {
          setIndex(data);
          if (!onClose) setSource(current => data.sources.some(s=>s.id===current) ? current : '');
        }
      } catch (e) { if (mounted) setError((e as Error).message); }
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
  const lineup = ids.map(id => index.moments.find(m => m.id === id)).filter((m):m is Moment => !!m && !m.dismissed);
  const fromSource = index.moments.filter(m => (!source || m.source===source) && !!m.dismissed===showDismissed);
  const selectedSource = index.sources.find(s=>s.id===source);
  const showSuggestions = !onClose && !!selectedSource && !showDismissed && !role && !query.trim() && !unused;
  const choices = (selectedSource?.clip_choices || []).flatMap(choice => {
    const cut = fromSource.find(m => m.id===choice.id && m.role===choice.role && !m.dismissed);
    return cut ? [{cut, why:choice.why}] : [];
  });
  const lead = showSuggestions && selectedSource.cursor===selectedSource.windows ? choices[0] : undefined;
  const filtered = fromSource.filter(m=>m.id!==lead?.cut.id).filter(m => (!role || m.role===role) && (!unused || !m.uses.length) &&
    [m.title,m.reason,...m.tags,index.sources.find(s=>s.id===m.source)?.title].join(' ').toLowerCase().includes(query.toLowerCase()));
  if (view.project) {
    const project = view.project;
    const keywords = new Set((project.title + ' ' + (project.labels[Math.max(0,position-1)] || ''))
      .toLowerCase().match(/[a-z0-9]{3,}/g)?.filter(w => !['the','and','with','from','gta','how','this','that'].includes(w)));
    const relevance = (m: Moment) => (m.title + ' ' + m.tags.join(' ')).toLowerCase()
      .split(/[^a-z0-9]+/).reduce((score,word)=>score+Number(keywords.has(word)),0);
    filtered.sort((a,b)=>relevance(b)-relevance(a));
  }
  const visibleSources = index.sources.filter(s => source ? s.id===source : s.active || s.error || s.needs_cut_review || s.cursor < (s.windows ?? 1));
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
  function useMain(m: Moment) {
    if (m.role==='comparison') return openComparison(m);
    if (m.role==='commentary') {
      void run('Verifying the commentary footage…',async()=>onJob(await api('/projects','POST',{
        kind:'commentary',ids:[m.id],title:m.title.slice(0,100)})));
    } else {
      if (ids.length && kind!=='highlight') { setError('Finish or clear the commentary lineup first.'); return; }
      if (!ids.includes(m.id) && ids.length>=5) { setError('Remove one moment from the current ranking first.'); return; }
      setIds([m.id,...ids.filter(id=>id!==m.id)]); setKind('highlight'); setRole('highlight'); setSource(''); setError('');
    }
  }
  const overlay = !!onClose;
  return <section className="mx-auto max-w-6xl space-y-5">
    <div className="flex items-start justify-between gap-3"><div>
      <h2 className="text-2xl font-bold text-white">{overlay ? (view.project?'Find supporting footage':'Use saved footage') : 'Master Screen'}</h2>
      <p className="mt-1 text-sm text-slate-400">{overlay ? 'Choose from your local footage library.' : 'Scan a gameplay video once and save its moments for future edits.'}</p>
    </div>{onClose && <button aria-label="Close library" onClick={onClose} className={button}><X size={17}/></button>}</div>
    {!overlay && <form className="flex flex-wrap gap-3 items-end rounded-2xl border border-[#303749] bg-[#161b26] p-5"
      onSubmit={e=>{e.preventDefault();void scan(address);}}>
      <label className="flex-1 min-w-48 text-xs font-semibold text-slate-300">YouTube video link
        <input type="url" required className={field+' block w-full mt-2'} value={address} onChange={e=>setAddress(e.target.value)} placeholder="Paste a gameplay video link" /></label>
      <button className={primary} disabled={!!busy || !address.trim()}>Scan video</button>
    </form>}
    <div className="flex flex-wrap gap-3 items-center">
      <select aria-label="Source video" className={field+' max-w-full'} value={source} onChange={e=>setSource(e.target.value)}>
        <option value="">All sources ({index.sources.length})</option>{index.sources.map(s=><option key={s.id} value={s.id}>{s.title}</option>)}</select>
      <label className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={unused} onChange={e=>setUnused(e.target.checked)}/> Unused only</label>
      {!overlay && <label className="flex items-center gap-2 text-sm text-slate-400"><input type="checkbox" checked={showDismissed} onChange={e=>setShowDismissed(e.target.checked)}/> Dismissed</label>}
    </div>
    {visibleSources.map(s=><div key={s.id} className="space-y-2 border-l-2 border-indigo-500 pl-4 text-sm text-slate-300">
      <strong className="text-white">{s.title}</strong>
      <div>{s.duration ? clock(s.coverage)+' / '+clock(s.duration)+' scanned' : 'Preparing source'} {s.needs_cut_review?' · Footage review pending':s.cursor===s.windows?' · Complete':s.active?' · Scanning': ' · Paused'}</div>
      {s.duration && <progress aria-label="Scan coverage" className="block w-full h-1 accent-indigo-400" value={s.coverage} max={s.duration}/>}
      {s.error && <p className="text-rose-300">{s.error}</p>}
      {!s.active && (s.cursor!==s.windows || s.needs_cut_review) && <button className={button} disabled={!!busy} onClick={()=>void scan('https://youtu.be/'+s.id)}>{s.needs_cut_review?'Review footage':'Resume scan'}</button>}
    </div>)}
    {showSuggestions && selectedSource && selectedSource.cursor===selectedSource.windows && !selectedSource.needs_cut_review && <>
      {lead ? <article aria-label="Main clip recommendation" className="rounded-2xl border border-indigo-400/50 bg-[#191e30] p-5 space-y-3">
        <div className="flex flex-wrap justify-between gap-2 text-sm">
          <h3 className="font-semibold text-indigo-200">Recommended main clip · {lead.cut.role==='highlight'?'Highlight':names[lead.cut.role]}</h3>
          <span className="font-mono text-slate-300">{clock(lead.cut.start)}–{clock(lead.cut.end)}</span>
        </div>
        <h4 className="text-xl font-bold text-white">{lead.cut.title}</h4>
        <p className="text-sm text-slate-300">{lead.why}</p>
        <div className="flex flex-wrap gap-2">
          <button className={primary} disabled={!!busy} onClick={()=>useMain(lead.cut)}>
            {lead.cut.role==='commentary'?'Start commentary':lead.cut.role==='comparison'?'Open in Comparison':'Start a highlight ranking'}</button>
          <button className={button} onClick={()=>setPreview(preview===lead.cut.id?'':lead.cut.id)}>{preview===lead.cut.id?'Close preview':'Preview clip'}</button>
        </div>
        {preview===lead.cut.id && selectedSource.asset && selectedSource.preview_url && selectedSource.duration && selectedSource.windows &&
          <Clip label={lead.cut.title} media={{asset:selectedSource.asset,preview_url:selectedSource.preview_url,duration:selectedSource.duration,windows:selectedSource.windows}} cut={lead.cut}/>}
      </article> : selectedSource.active ? <p role="status" className="text-sm text-indigo-200">Choosing the best tab for the main clip…</p>
        : selectedSource.clip_choices ? <p className="text-sm text-slate-300">No clip stood out to lead a video.</p>
        : <button className={button} disabled={!!busy} onClick={()=>void scan('https://youtu.be/'+selectedSource.id)}>
          {selectedSource.error?'Retry clip recommendation':'Recommend a main clip'}</button>}
    </>}
    <div className="flex flex-wrap gap-2" aria-label="Footage categories">
      {(['',...roles] as const).filter(r => !view.role || r===view.role || (view.role==='commentary' && r==='support')).map(r=>
        <button key={r} aria-pressed={role===r} className={button+(role===r?' !border-indigo-400 !text-indigo-200':'')}
          onClick={()=>setRole(r)}>{r ? names[r]:'All finds'} · {fromSource.filter(m=>!r||m.role===r).length}</button>)}
    </div>
    <label className="flex items-center gap-2 text-slate-400"><Search size={16}/><input aria-label="Search footage" className={field+' flex-1'} value={query}
      onChange={e=>setQuery(e.target.value)} placeholder="Find a topic, action, source or tag"/></label>
    {view.project && <label className="flex flex-wrap gap-2 items-center text-sm text-slate-300">Insert shot
      <select className={field} value={position} onChange={e=>setPosition(Number(e.target.value))}><option value={0}>Before the first scene</option>
        {view.project.labels.map((s,i)=><option key={i} value={i+1}>After scene {i+1} · {s}</option>)}</select></label>}
    {!!lineup.length && <div className="rounded-xl bg-[#171e2b] border border-indigo-500/40 p-4 space-y-3">
      <h3 className="text-sm font-bold text-white">{kind==='highlight'?'Highlight lineup · favourite first':'Commentary lineup · playback order'}</h3>
      <input className={field+' w-full'} aria-label="Project title" placeholder="Video title (optional)" value={title} maxLength={100} onChange={e=>setTitle(e.target.value)}/>
      {lineup.map((m,i)=><div key={m.id} className="flex gap-2 items-center text-sm text-slate-200">
        <span className="mr-auto">{i+1}. {m.title}</span>
        <button className={button} aria-label={'Move up '+m.title} disabled={i===0 || !!busy} onClick={()=>reorder(i,-1)}>↑</button>
        <button className={button} aria-label={'Move down '+m.title} disabled={i===ids.length-1 || !!busy} onClick={()=>reorder(i,1)}>↓</button>
        <button className={button} aria-label={'Remove '+m.title} disabled={!!busy} onClick={()=>toggle(m)}>×</button></div>)}
      <button className={primary} disabled={!!busy || (kind==='highlight'?lineup.length<2:!lineup.some(m=>m.role==='commentary'))}
        onClick={()=>void run('Verifying selected footage…',async()=>{onJob(await api('/projects','POST',{ids,kind,title}));})}>
        {kind==='highlight'?'Prepare ranked Short':'Prepare commentary'}</button>
      <button className={button+' ml-2'} disabled={!!busy} onClick={()=>{setIds([]);setTitle('');}}>Clear lineup</button>
    </div>}
    {busy && <p role="status" className="text-sm text-indigo-200">{busy}</p>}
    {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
    {lead && filtered.length>0 && <h3 className="font-semibold text-white">Also saved from this link</h3>}
    {!lead && !filtered.length && <div className="rounded-xl border border-dashed border-slate-700 p-8 text-center text-sm text-slate-400">
      <Archive className="mx-auto mb-2" size={22}/>{index.sources.length?'No matching moments yet.':'Your saved moments will appear here after a scan.'}</div>}
    <div className="grid gap-4 lg:grid-cols-2">{filtered.map(m=>{
      const src=index.sources.find(s=>s.id===m.source);
      if (!src?.duration || !src.asset || !src.preview_url || !src.windows) return null;
      const media={duration:src.duration,asset:src.asset,preview_url:src.preview_url,windows:src.windows};
      return <article key={m.id} className="rounded-xl border border-[#2b3241] bg-[#151a24] p-4 space-y-3">
        <div className="flex justify-between items-center text-xs"><span className="text-indigo-300">{names[m.role]}</span><span className="font-mono text-slate-400">{clock(m.start)}–{clock(m.end)}</span></div>
        <h3 className="text-base font-bold text-white">{m.title}</h3><p className="text-sm text-slate-300">{m.reason}</p>
        {showSuggestions && choices.slice(1).some(c=>c.cut.id===m.id) && <p className="text-sm text-indigo-200">
          Also recommended · {choices.find(c=>c.cut.id===m.id)?.why}</p>}
        <p className="text-xs text-slate-400">{src.title}{m.tags.length>0?' · '+m.tags.join(' · '):''}</p>
        <div className="text-xs text-slate-400">{m.uses.length ? <>Used in {m.uses.map((u,i)=><a key={u.url} href={u.url} target="_blank" rel="noreferrer" className="text-indigo-300 underline">{(i?', ':'')+u.title}</a>)}</> : 'Unused'}</div>
        {preview===m.id && <Clip label={m.title} media={media} cut={{start:m.start,end:m.end}}/>}
        <div className="flex flex-wrap gap-2">
          <button className={button} onClick={()=>setPreview(preview===m.id?'':m.id)}><Play size={12} className="inline mr-1"/>{preview===m.id?'Close preview':'Preview'}</button>
          {m.dismissed ? <button className={button} disabled={!!busy} onClick={()=>void change(m,{dismissed:false})}>Restore</button> :
            view.project ? <button className={button} disabled={!!busy} onClick={()=>void run('Verifying supporting shot…',async()=>{
              onJob(await api('/projects/'+view.project!.job+'/'+view.project!.clip+'/support','POST',{moment_id:m.id,after:position}));})}>Insert in commentary</button> :
            m.role==='comparison' ? <button className={button} disabled={!!busy} onClick={()=>openComparison(m)}>Open in Comparison</button> :
            <button className={button} disabled={!!busy} onClick={()=>toggle(m)}>{ids.includes(m.id)?<><Check size={12} className="inline"/> Selected</>:
              m.role==='highlight'?'Add to ranking':'Add to commentary'}</button>}
          {!overlay && !m.dismissed && <button className={button} onClick={()=>setEdit(edit===m.id?'':m.id)}>Organize</button>}
        </div>
        {edit===m.id && <div className="flex gap-2"><select className={field} aria-label="Move moment to" value={m.role}
          onChange={e=>void change(m,{role:e.target.value as Role})}>{roles.map(r=><option key={r} value={r}>{names[r]}</option>)}</select>
          <button disabled={!!busy} className={button} onClick={()=>void change(m,{dismissed:true})}>Dismiss</button></div>}
      </article>;
    })}</div>
  </section>;
}
