import type { KnowledgeJobData, KnowledgeJobRecord } from '$lib/api/knowledge';

/** Merge or insert a job row into the recent-jobs list (newest first, capped at 10). */
export function upsertRecentJobRecord(
  recentJobs: KnowledgeJobRecord[],
  nextJob: KnowledgeJobData
): KnowledgeJobRecord[] {
  const existing = recentJobs.find((item) => item.id === nextJob.job_id);
  const record: KnowledgeJobRecord = {
    id: nextJob.job_id,
    created_at: existing?.created_at ?? new Date().toISOString(),
    finished_at: nextJob.status === 'running' ? null : (existing?.finished_at ?? new Date().toISOString()),
    status: nextJob.status,
    totals: nextJob.totals,
    errors: nextJob.errors,
    params: existing?.params ?? {}
  };
  return [record, ...recentJobs.filter((item) => item.id !== nextJob.job_id)].slice(0, 10);
}

export function knowledgeJobStatusFromEventType(eventType: string): KnowledgeJobData['status'] {
  if (eventType === 'knowledge.job.failed') return 'failed';
  if (eventType === 'knowledge.job.completed') return 'completed';
  return 'running';
}

export function knowledgeJobFromEvent(event: MessageEvent): KnowledgeJobData | null {
  const data = JSON.parse(event.data) as {
    job_id?: string;
    totals?: Record<string, number>;
    errors?: Record<string, string>;
    in_flight?: string[];
  };
  if (!data.job_id) return null;
  return {
    job_id: data.job_id,
    status: knowledgeJobStatusFromEventType(event.type),
    totals: data.totals ?? {},
    errors: data.errors ?? {},
    in_flight: data.in_flight ?? []
  };
}
