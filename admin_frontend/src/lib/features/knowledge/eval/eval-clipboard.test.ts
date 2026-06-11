import { describe, expect, it } from 'vitest';
import { formatEvalRowForAI, safeRunId } from './eval-clipboard';
import type { EvalRow } from '$lib/features/knowledge/state/knowledge-eval.svelte';

/** A realistic memory-eval row: single recall leg, judge fail, recalled facts of each kind. */
function memoryRow(): EvalRow {
  return {
    index: 2,
    total: 12,
    id: 'q_direct_01',
    category: 'direct',
    subcategory: 'spouse',
    difficulty: 'medium',
    question: "What is the name of Adam's wife?",
    requires_graph: false,
    track: 'memory',
    delta: '0',
    gold: 'Nora.',
    cost_usd: 0.0042,
    is_negative_control: false,
    answered_at: '2026-06-11T16:35:00Z',
    legs: {
      recall: {
        mode: 'recall',
        mark: '✗',
        elapsed_ms: 1240,
        answer_preview: "I don't have that information.",
        answer: "I don't have that information about Adam's wife.",
        run_id: 'memory_eval_q-adam_year-memeval-abc123-q_direct_01',
        reason: 'No fact about a spouse was recalled.',
        cost_usd: 0.0042,
        recalled: [
          { kind: 'fact', memory: 'Adam works at Brightloom (as of 2024-01-15)', fact: 'Adam works at Brightloom', name: 'WORKS_AT', valid_at: '2024-01-15', score: 0.871 },
          { kind: 'entity', memory: 'backend engineer at Brightloom', name: 'Adam', summary: 'backend engineer at Brightloom', entity_type: 'Person', score: 0.812 },
          { kind: 'episode', memory: 'Adam started a new job at Brightloom today as a backend engineer.', valid_at: '2024-01-15', score: 0.744 }
        ]
      }
    }
  };
}

describe('formatEvalRowForAI — memory track', () => {
  const brief = formatEvalRowForAI({
    row: memoryRow(),
    legColumns: ['recall'],
    track: 'memory',
    engine: 'graphiti · recipe=rrf · hops=1 · answer=claude-opus-4-8',
    corpus: 'adam_year',
    logDir: 'D:\\workspaces\\demo\\logs'
  });

  it('renders the full brief (printed for review)', () => {
    // eslint-disable-next-line no-console
    console.log('\n===== MEMORY BRIEF =====\n' + brief + '\n========================\n');
    expect(brief).toBeTruthy();
  });

  it('inlines the data the ledger does not persist', () => {
    expect(brief).toContain('Ideal: Nora.');
    expect(brief).toContain("answer: I don't have that information about Adam's wife.");
    expect(brief).toContain('judge: No fact about a spouse was recalled.');
    expect(brief).toContain('## Recall — ✗');
  });

  it('lists recalled facts of each kind', () => {
    expect(brief).toContain('recalled facts (3):');
    expect(brief).toContain('[fact] Adam works at Brightloom');
    expect(brief).toContain('[entity] Adam — backend engineer at Brightloom');
    expect(brief).toContain('[episode] Adam started a new job');
  });

  it('points at the per-leg retrieval trace + ingest dir with absolute Windows paths', () => {
    expect(brief).toContain(
      'D:\\workspaces\\demo\\logs\\retrieval_trace\\memory_eval_q-adam_year-memeval-abc123-q_direct_01.jsonl'
    );
    expect(brief).toContain('grep run_id=memory_eval_q-adam_year-memeval-abc123-q_direct_01');
    expect(brief).toContain('remember/ingest  D:\\workspaces\\demo\\logs\\ingest_trace');
  });

  it('ends with a fill-in line for the user question', () => {
    expect(brief.trimEnd().endsWith('My question:')).toBe(true);
  });
});

describe('formatEvalRowForAI — knowledge track', () => {
  function knowledgeRow(): EvalRow {
    return {
      index: 0,
      total: 5,
      id: 'q1',
      category: 'multi_hop',
      subcategory: '',
      difficulty: 'hard',
      question: 'Did the team ship the auth fix?',
      requires_graph: true,
      track: 'knowledge',
      delta: '+1',
      gold: 'Shipped in v2.3 on Feb 14.',
      cost_usd: 0.01,
      is_negative_control: false,
    answered_at: '2026-06-11T16:35:00Z',
      legs: {
        flat: { mode: 'flat', mark: '✗', elapsed_ms: 900, answer_preview: '', answer: 'No info.', run_id: 'knowledge_answer-r1-q1-flat', reason: 'missed it', cost_usd: 0.004 },
        graphiti: { mode: 'graphiti', mark: '✓', elapsed_ms: 1500, answer_preview: '', answer: 'Yes, v2.3.', run_id: 'knowledge_answer-r1-q1-graphiti', reason: 'grounded', cost_usd: 0.006 }
      }
    };
  }

  const brief = formatEvalRowForAI({
    row: knowledgeRow(),
    legColumns: ['flat', 'graphiti'],
    track: 'knowledge',
    engine: 'graphiti · recipe=hybrid · hops=2',
    corpus: 'support_threads',
    logDir: '/srv/ws/logs'
  });

  it('renders both legs + only the graph leg gets a retrieval pointer (flat has no graph search)', () => {
    // eslint-disable-next-line no-console
    console.log('\n===== KNOWLEDGE BRIEF =====\n' + brief + '\n===========================\n');
    expect(brief).toContain('## Flat — ✗');
    expect(brief).toContain('## Graphiti — ✓');
    // POSIX separator from a POSIX base; graphiti has a trace, flat only a cost grep.
    expect(brief).toContain('Graphiti retrieval  /srv/ws/logs/retrieval_trace/knowledge_answer-r1-q1-graphiti.jsonl');
    expect(brief).not.toContain('Flat retrieval  ');
    expect(brief).toContain('grep run_id=knowledge_answer-r1-q1-flat');
    // No memory-only ingest pointer on the knowledge track.
    expect(brief).not.toContain('remember/ingest');
  });
});

describe('safeRunId', () => {
  it('mirrors the backend sanitizer (alnum + -_. kept, else _)', () => {
    expect(safeRunId('memory_eval_q-a.b-1')).toBe('memory_eval_q-a.b-1');
    expect(safeRunId('weird/id:with spaces')).toBe('weird_id_with_spaces');
    expect(safeRunId('')).toBe('run');
  });
});
