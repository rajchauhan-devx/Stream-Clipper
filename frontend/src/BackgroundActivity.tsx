import { useEffect, useState } from 'react';

type Activity = {id: string; title: string; step: string; percent?: number};

export default function BackgroundActivity({onFinished}: {onFinished: () => void}) {
  const [tasks, setTasks] = useState<Activity[]>([]);
  const [disconnected, setDisconnected] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let timer: number;
    let previousIds: string[] = [];
    async function refresh() {
      try {
        const response = await fetch('/api/activity', {signal:controller.signal});
        if (!response.ok) throw new Error();
        const active: Activity[] = await response.json();
        if (!controller.signal.aborted) {
          const ids = active.map(task => task.id);
          if (previousIds.some(id => !ids.includes(id))) onFinished();
          previousIds = ids;
          setTasks(active);
          setDisconnected(false);
        }
      } catch {
        if (!controller.signal.aborted) setDisconnected(true);
      } finally {
        if (!controller.signal.aborted) timer = window.setTimeout(refresh, 1500);
      }
    }
    void refresh();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [onFinished]);
  if (!tasks.length && !disconnected) return null;
  return <aside aria-label="Background activity" className="sticky top-0 z-10 mx-auto mb-4 max-w-6xl space-y-2 rounded-lg border border-indigo-500/50 bg-[#151b2b] p-3 text-sm text-slate-200">
    {disconnected && <p role="status">Reconnecting to background activity…</p>}
    {tasks.map(task=><div key={task.id}>
      <p className="font-semibold">{task.title}</p>
      <p role="status">{task.step}</p>
      <progress aria-label={task.title} max={100} value={task.percent} className="mt-1 h-1.5 w-full accent-indigo-400"/>
    </div>)}
  </aside>;
}
