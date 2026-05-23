import { base } from '$app/paths';
import type { KnowledgeJobData } from '$lib/api/knowledge';
import { PREF_KEYS } from '$lib/preferences/keys';
import { knowledgeJobFromEvent } from './knowledge-jobs';

const KNOWLEDGE_JOB_EVENT_TYPES = [
  'knowledge.job.started',
  'knowledge.job.progress',
  'knowledge.job.completed',
  'knowledge.job.failed'
] as const;

/** Subscribe to knowledge ingest job SSE updates; returns teardown. */
export function connectKnowledgeJobEvents(onJob: (job: KnowledgeJobData) => void): () => void {
  const selectedWorkspace =
    typeof localStorage === 'undefined' ? null : localStorage.getItem(PREF_KEYS.selectedWorkspace);
  const queryParam = selectedWorkspace ? `?workspace=${encodeURIComponent(selectedWorkspace)}` : '';
  const source = new EventSource(`${base}/api/knowledge/events${queryParam}`);

  const handler = (event: MessageEvent) => {
    const job = knowledgeJobFromEvent(event);
    if (job) onJob(job);
  };

  for (const type of KNOWLEDGE_JOB_EVENT_TYPES) {
    source.addEventListener(type, handler);
  }
  return () => source.close();
}
