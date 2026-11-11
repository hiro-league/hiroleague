// The Logs page: lines from the files in DATA_DIR/logs (backend logs_api.py), and the LLM requests tab (backend
// llm/requests_api.py). Types are written out from the backends' answers, which every app's generated file shares.
import { api, apiUrl } from '$kit/api/client';

export type Level = 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';
/** The app's own name ("homehiro") or "crash". */
export type Source = string;
export type Span = '1h' | '24h' | '7d';
export type View = 'problems' | 'all';

/** id: its file and line; detail: the traceback, or the rest of the message */
export type LogLine = { id: string; at: string; level: Level; logger: string; source: Source; message: string; detail: string | null };
/** more: there were more than the backend sends (the oldest are left out) */
export type LogLines = { lines: LogLine[]; more: boolean; unreadable: string[] };
export type LogSummary = { errors: number; warnings: number; newest: LogLine | null; hours: { errors: number; warnings: number }[] };
export type LogFile = { name: string; what: string; size: number; limit: number; kept: number; keep: number };

export const getLogs = (span: Span, view: View, source: Source | 'all', signal?: AbortSignal) =>
	api<LogLines>(`logs?span=${span}&view=${view}&source=${source}`, { signal });

export const getLogSummary = (signal?: AbortSignal) => api<LogSummary>('logs/summary', { signal });

export const getLogFiles = (signal?: AbortSignal) => api<LogFile[]>('logs/files', { signal });

/** Where a log file downloads from (the browser saves it). */
export const logFileUrl = (name: string) => apiUrl(`logs/files/${encodeURIComponent(name)}`);

export type LlmRequestRow = {
	id: string;
	at: string;
	source: string;
	task: string;
	camera: string | null;
	status: string;
	error: string | null;
	model: string | null;
	profile: string | null;
	pictures: number;
	pictures_kept: boolean;
	reply: string | null; // its start
	ms: number;
	cost: number | null;
	warning: string | null;
};
/** more: older ones match too; disk: bytes the pictures take; cameras: for the filter */
export type LlmRequests = { requests: LlmRequestRow[]; more: boolean; keep_days: number; picture_days: number; disk: number; cameras: string[] };
/** A part of the words, with where it came from and the page to change it on. */
export type LlmPart = { label: string; link: string | null; text: string };
export type LlmPicture = { label: string; width: number; height: number; size: number };
/** One model asked (or a profile passed over: outcome "passed over"). */
export type LlmTry = { profile: string | null; provider: string | null; model: string | null; ok: boolean; outcome: string; ms: number };
export type LlmRequest = {
	id: string;
	at: string;
	source: string;
	task: string;
	link: string | null;
	camera: string | null;
	status: string;
	error: string | null;
	provider: string | null;
	model: string | null;
	profile: string | null;
	detail: string | null;
	thinking: string | null;
	prompt: string;
	parts: LlmPart[];
	answer_schema: Record<string, unknown>;
	reply: string | null;
	outcome: string | null;
	tries: LlmTry[];
	pictures: LlmPicture[];
	pictures_kept: boolean;
	ms: number;
	tokens_in: number;
	tokens_out: number;
	cost: number | null;
	warning: string | null;
};

export const getLlmRequests = (f: { source: string; camera: string; problems: boolean; q: string }, signal?: AbortSignal) => {
	const q = new URLSearchParams();
	if (f.source !== 'all') q.set('source', f.source);
	if (f.camera !== 'all') q.set('camera', f.camera);
	if (f.problems) q.set('problems', 'true');
	if (f.q.trim()) q.set('q', f.q.trim());
	return api<LlmRequests>(`logs/llm${q.size ? `?${q}` : ''}`, { signal });
};

export const getLlmRequest = (id: string, signal?: AbortSignal) => api<LlmRequest>(`logs/llm/${encodeURIComponent(id)}`, { signal });

/** A picture sent with a request, while it's kept. */
export const llmPictureUrl = (id: string, n: number) => apiUrl(`logs/llm/${encodeURIComponent(id)}/pictures/${n}`);
