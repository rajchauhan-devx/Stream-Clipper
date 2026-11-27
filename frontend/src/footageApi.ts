export type Role = 'commentary' | 'comparison' | 'highlight' | 'support';
type ClipChoice = { id: string; role: Exclude<Role, 'support'>; why: string };
type Source = { id: string; title: string; duration?: number; asset?: string; preview_url?: string | null; windows?: number;
  needs_cut_review?: boolean; clip_choices?: ClipChoice[]; cursor: number; coverage: number; scan_complete: boolean; active: boolean;
  status_message?: string | null; error: string };
type Moment = { id: string; source: string; role: Role; title: string; start: number; end: number; reason: string;
  tags: string[]; record: string; dismissed: number; uses: {title: string; url: string}[] };
export type Index = { sources: Source[]; moments: Moment[] };
export type LibrarySetup = { id: string; question: string; observation: string; record: string; start: number; end: number;
  media: { duration: number; asset: string; preview_url: string; windows: number }; sourceId: string };
export type LibraryView = { role?: Role; source?: string; project?: { job: string; clip: string; title: string; labels: string[] } };

export async function libraryRequest<T>(url: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch('/api/library' + url, { method, headers: { 'Content-Type':'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'The library request failed. Try again.');
  return data;
}

