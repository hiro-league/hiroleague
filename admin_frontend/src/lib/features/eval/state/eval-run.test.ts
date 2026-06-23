import { describe, it, expect, vi, beforeEach } from 'vitest';

// Capture the SSE handler set + stub the network boundary. `vi.hoisted` so the mock factories can
// reach these (mock factories are hoisted above imports).
const h = vi.hoisted(() => ({
  handlers: null as Record<string, (p: unknown) => void> | null,
  teardown: vi.fn(),
  cancel: vi.fn(async () => ({ data: { cancelled: true, run_id: 'r1' } })),
  state: { data: null as unknown }
}));

vi.mock('$lib/features/eval/shared/eval-events', () => ({
  connectEvalEvents: (handlers: Record<string, (p: unknown) => void>) => {
    h.handlers = handlers;
    return h.teardown;
  }
}));

vi.mock('$lib/api/eval', () => ({
  cancelKnowledgeEval: (...args: unknown[]) => h.cancel(...(args as [])),
  getKnowledgeEvalState: async () => h.state
}));

import { createEvalRunController, type EvalRunCtx } from './eval-run.svelte';
import type { EvalTrack } from '../shared/eval-row';

function setup(initialModes: string[] = ['flat', 'graphiti']) {
  let track: EvalTrack = 'memory';
  const onTerminal = vi.fn();
  const afterHydrate = vi.fn();
  const setError = vi.fn();
  const ctx: EvalRunCtx = {
    setError,
    getTrack: () => track,
    setTrackFromServer: (t) => {
      track = t;
    },
    onTerminal,
    afterHydrate
  };
  const run = createEvalRunController(ctx, { initialModes });
  return { run, onTerminal, afterHydrate, setError, getTrack: () => track };
}

const q = (index: number, id: string) => ({
  index,
  total: 3,
  id,
  category: 'cat',
  question: '?',
  requires_graph: false
});

beforeEach(() => {
  h.handlers = null;
  h.state.data = null;
  vi.clearAllMocks();
});

describe('createEvalRunController — defaults & subscription', () => {
  it('starts idle with the injected leg columns', () => {
    const { run } = setup(['recall']);
    expect(run.status).toBe('idle');
    expect(run.runModes).toEqual(['recall']);
    expect(run.rows).toEqual([]);
  });

  it('ensureSubscribed wires exactly one EventSource', () => {
    const { run } = setup();
    run.ensureSubscribed();
    run.ensureSubscribed();
    expect(h.handlers).not.toBeNull();
  });
});

describe('beginStarting / setRunId / markFailed', () => {
  it('fresh-slates, locks the columns, flips to starting, and subscribes', () => {
    const { run } = setup();
    run.beginStarting(['recall']);
    expect(run.status).toBe('starting');
    expect(run.runModes).toEqual(['recall']);
    expect(run.runId).toBeNull();
    expect(h.handlers).not.toBeNull();
  });

  it('setRunId + markFailed update the run', () => {
    const { run } = setup();
    run.beginStarting(['recall']);
    run.setRunId('r1');
    expect(run.runId).toBe('r1');
    run.markFailed('boom');
    expect(run.status).toBe('failed');
    expect(run.failureMessage).toBe('boom');
  });
});

describe('SSE handlers — run_id gating + transitions', () => {
  it('ignores events for a different run', () => {
    const { run } = setup();
    run.beginStarting(['recall']);
    run.setRunId('r1');
    h.handlers!.onStarted({ run_id: 'OTHER', total_questions: 9 });
    expect(run.status).toBe('starting');
    expect(run.totalQuestions).toBe(0);
  });

  it('started → running, then question rows upsert by index', () => {
    const { run } = setup();
    run.beginStarting(['recall']);
    run.setRunId('r1');
    h.handlers!.onStarted({ run_id: 'r1', total_questions: 3, modes: ['recall'] });
    expect(run.status).toBe('running');
    expect(run.totalQuestions).toBe(3);

    h.handlers!.onQuestion({ run_id: 'r1', ...q(2, 'q2') });
    h.handlers!.onQuestion({ run_id: 'r1', ...q(1, 'q1') });
    expect(run.rows.map((r) => r.id)).toEqual(['q2', 'q1']);
    // Re-deliver index 2 → replace in place, not append.
    h.handlers!.onQuestion({ run_id: 'r1', ...q(2, 'q2-updated') });
    expect(run.rows.map((r) => r.id)).toEqual(['q2-updated', 'q1']);
  });

  it('terminal events set status + notify the model', () => {
    for (const [kind, fire] of [
      ['completed', (hh: typeof h.handlers) => hh!.onCompleted({ run_id: 'r1' })],
      ['failed', (hh: typeof h.handlers) => hh!.onFailed({ run_id: 'r1', error: 'x' })],
      ['cancelled', (hh: typeof h.handlers) => hh!.onCancelled({ run_id: 'r1' })]
    ] as const) {
      const { run, onTerminal } = setup();
      run.beginStarting(['recall']);
      run.setRunId('r1');
      fire(h.handlers);
      expect(run.status).toBe(kind);
      expect(onTerminal).toHaveBeenCalledWith(kind);
    }
  });
});

describe('applySnapshot', () => {
  it('sorts rows, derives leg columns from the summary, and marks completed', () => {
    const { run } = setup();
    const rows = [q(2, 'b'), q(1, 'a')].map((p) => ({
      ...p,
      subcategory: '',
      difficulty: '',
      track: 'memory' as EvalTrack,
      legs: {},
      delta: '0',
      gold: '',
      cost_usd: 0,
      is_negative_control: false,
      answered_at: '',
      evidence_recall: null,
      rubric: []
    }));
    run.applySnapshot(rows, { modes: ['recall'] } as never);
    expect(run.rows.map((r) => r.id)).toEqual(['a', 'b']);
    expect(run.runModes).toEqual(['recall']);
    expect(run.status).toBe('completed');
  });

  it('an empty snapshot falls back to idle and the recall column', () => {
    const { run } = setup();
    run.applySnapshot([], null);
    expect(run.status).toBe('idle');
    expect(run.runModes).toEqual(['recall']);
  });
});

describe('hydrateFromServer', () => {
  it('no server run while idle → resets', async () => {
    const { run, afterHydrate } = setup();
    h.state.data = null;
    await run.hydrateFromServer();
    expect(run.status).toBe('idle');
    expect(afterHydrate).not.toHaveBeenCalled();
  });

  it('adopts a live run track and replays its rows, then signals afterHydrate', async () => {
    const { run, afterHydrate, getTrack } = setup();
    h.state.data = {
      run_id: 'r9',
      status: 'running',
      track: 'knowledge',
      total_questions: 2,
      modes: ['flat'],
      setup_events: [],
      rows: [{ run_id: 'r9', ...q(1, 'a') }],
      summary: null,
      failure_message: null,
      cancel_requested: false
    };
    await run.hydrateFromServer();
    expect(run.status).toBe('running');
    expect(run.runId).toBe('r9');
    expect(getTrack()).toBe('knowledge'); // adopted mid-run
    expect(run.runModes).toEqual(['flat']);
    expect(run.rows.map((r) => r.id)).toEqual(['a']);
    expect(afterHydrate).toHaveBeenCalled();
  });
});

describe('cancel + teardown', () => {
  it('cancel calls the API for a live run and arms the cancelling flag', async () => {
    const { run } = setup();
    run.beginStarting(['recall']);
    run.setRunId('r1');
    h.handlers!.onStarted({ run_id: 'r1', total_questions: 1 });
    await run.cancel();
    expect(h.cancel).toHaveBeenCalledWith('r1');
    expect(run.cancelling).toBe(true);
  });

  it('cancel is a no-op when not running', async () => {
    const { run } = setup();
    await run.cancel();
    expect(h.cancel).not.toHaveBeenCalled();
  });

  it('teardown closes the EventSource once', () => {
    const { run } = setup();
    run.ensureSubscribed();
    run.teardown();
    run.teardown();
    expect(h.teardown).toHaveBeenCalledTimes(1);
  });
});

describe('ingestRunId', () => {
  it('prefers the summary id, else the latest setup-event id', () => {
    const { run } = setup();
    run.beginStarting(['recall']);
    run.setRunId('r1');
    expect(run.ingestRunId).toBeNull();
    h.handlers!.onSetupProgress({ run_id: 'r1', phase: 'remember', ingest_run_id: 'ingest-7' });
    expect(run.ingestRunId).toBe('ingest-7');
    h.handlers!.onCompleted({ run_id: 'r1', ingest_run_id: 'summary-9' });
    expect(run.ingestRunId).toBe('summary-9');
  });
});
