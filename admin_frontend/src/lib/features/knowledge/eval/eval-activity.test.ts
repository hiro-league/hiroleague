import { describe, expect, it } from 'vitest';
import { activityHeaderLine } from './eval-activity';
import type { EvalRow } from '$lib/features/knowledge/state/knowledge-eval.svelte';
import type { EvalSetupProgressPayload } from '$lib/features/knowledge/shared/knowledge-events';

function memoryRow(index: number, question: string, mark = ''): EvalRow {
  return {
    index,
    total: 5,
    id: `q${index}`,
    category: 'recall',
    subcategory: '',
    difficulty: '',
    question,
    requires_graph: false,
    track: 'memory',
    legs: { recall: { mode: 'recall', mark, elapsed_ms: 1, answer_preview: '', answer: 'a', run_id: null, recalled: [{ memory: 'x' }] } },
    delta: '0',
    gold: 'g',
    cost_usd: 0,
    is_negative_control: false,
    answered_at: '',
    evidence_recall: null
  };
}

const base = { totalQuestions: 5, summaryGate: null, summaryElapsedMs: null, failureMessage: null };

describe('activityHeaderLine — live current line', () => {
  it('shows the current episode during ingestion (no question rows yet)', () => {
    const ep: EvalSetupProgressPayload = { phase: 'remember', index: 11, total: 20, episode_no: 11, snippet: 'hello' };
    const line = activityHeaderLine({ ...base, status: 'running', rows: [], setupEvents: [ep] });
    expect(line).toContain('ingested episode 11');
  });

  it('shows the latest question during the question phase', () => {
    const rows = [memoryRow(0, 'first?', '✓'), memoryRow(1, 'second question?', '✗')];
    const line = activityHeaderLine({ ...base, status: 'running', rows, setupEvents: [] });
    expect(line).toContain('second question?');
    expect(line).toContain('2/5'); // Q index display
  });

  it('falls back to preparing when nothing has happened yet', () => {
    expect(activityHeaderLine({ ...base, status: 'starting', rows: [], setupEvents: [] })).toBe('preparing…');
  });

  it('shows the terminal verdict when completed', () => {
    const line = activityHeaderLine({ ...base, status: 'completed', rows: [], setupEvents: [], summaryGate: 'proceed', summaryElapsedMs: 1200 });
    expect(line).toBe('✅ PROCEED · 1200ms');
  });

  it('shows the failure when failed', () => {
    const line = activityHeaderLine({ ...base, status: 'failed', rows: [], setupEvents: [], failureMessage: 'boom' });
    expect(line).toBe('❌ failed: boom');
  });
});
