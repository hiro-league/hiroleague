/**
 * "Copy for AI" — formats one eval result row into a self-introducing Markdown brief
 * for pasting into an AI agent (e.g. Claude Code) running in this repo.
 *
 * The split is deliberate (see docs/eval-recall-tables-split-design.md discussion):
 *  - INLINE the data the ledger does NOT persist — question, ideal/gold, the FULL model
 *    answer (graph.log only keeps a 280-char preview), the judge mark + reason, and (memory)
 *    the recalled facts. This is the decision-grade data an agent reasons from immediately.
 *  - POINT at the on-disk ledger sidecars for the heavy, fully-persisted depth — the per-leg
 *    retrieval pipeline (retrieval_trace/<run_id>.jsonl), node cost/timeline (graph.log), and
 *    (memory) the remember/ingest trace (ingest_trace/). The agent opens exactly one file
 *    instead of grepping the repo.
 *
 * Pure + framework-free so it stays unit-testable (mirrors logs/shared/logs-ui.ts).
 */
import type { EvalRow, EvalTrack } from '$lib/features/eval/state/eval-model.svelte';
import type { RecalledFact } from '$lib/features/knowledge/shared/knowledge-events';

/** Human label for a leg in the brief (flat/graphiti = knowledge, recall = memory). */
const LEG_LABEL: Record<string, string> = { flat: 'Flat', graphiti: 'Graphiti', recall: 'Recall' };

/** Graph legs whose recall went through the traced fact search → have a retrieval_trace sidecar.
 *  The flat (Qdrant hybrid) leg does no graph search, so it has cost in graph.log but no trace. */
const TRACEABLE_LEGS = new Set(['recall', 'graphiti']);

/** Mirror of the backend's ``_safe_run_id`` (retrieval_trace.py) so the sidecar filename we
 *  point at matches what the writer produced: keep alnum + ``-_.``; everything else → ``_``;
 *  cap at 120; fall back to "run". A mismatch here would point the agent at a missing file. */
export function safeRunId(runId: string): string {
  const cleaned = [...String(runId)]
    .map((ch) => (/[a-zA-Z0-9]/.test(ch) || ch === '-' || ch === '_' || ch === '.' ? ch : '_'))
    .join('');
  return cleaned.slice(0, 120) || 'run';
}

/** Join path segments with the separator the base dir uses (Windows ``\`` vs POSIX ``/``), so
 *  pasted absolute paths are valid on the workspace's OS. Falls back to ``/`` for relative bases. */
function joinPath(base: string, ...parts: string[]): string {
  const sep = base.includes('\\') && !base.includes('/') ? '\\' : '/';
  const trimmed = base.replace(/[\\/]+$/, '');
  return [trimmed, ...parts].join(sep);
}

/** One-line, paste-friendly form of a recalled item: ``[kind] text  (when)  score``. Text is
 *  collapsed to a single line and capped — the full item lives in the retrieval_trace file. */
function recalledLine(r: RecalledFact): string {
  const kind = r.kind ?? 'fact';
  let text =
    kind === 'entity'
      ? [r.name, r.summary || r.memory].filter(Boolean).join(' — ')
      : r.fact || r.memory || '';
  text = text.replace(/\s+/g, ' ').trim();
  if (text.length > 200) text = `${text.slice(0, 199)}…`;
  const when = kind === 'fact' ? r.valid_at : kind === 'episode' ? r.valid_at : '';
  const score = typeof r.score === 'number' ? `score ${r.score.toFixed(3)}` : '';
  const meta = [when ? `(${when})` : '', score].filter(Boolean).join('  ');
  return `  [${kind}] ${text}${meta ? `  ${meta}` : ''}`;
}

export type EvalAIBriefInput = {
  row: EvalRow;
  /** Legs the run used, in column order (memory = ['recall']). */
  legColumns: string[];
  track: EvalTrack;
  /** Compact engine line, e.g. "graphiti · recipe=rrf · hops=1 · answer=claude-opus-4-8". */
  engine: string;
  /** Corpus id (drives the eval group scope) — the agent's stable handle on the dataset. */
  corpus: string;
  /** Absolute workspace logs/ dir; '' falls back to a "logs/" relative pointer. */
  logDir: string;
};

/** Build the clipboard brief for one eval row. */
export function formatEvalRowForAI(input: EvalAIBriefInput): string {
  const { row, legColumns, track, engine, corpus, logDir } = input;
  const isMemory = track === 'memory';
  const legName = (m: string) => LEG_LABEL[m] ?? m.charAt(0).toUpperCase() + m.slice(1);

  // Preamble — states the contract so the agent reasons inline and reads files for depth.
  const preamble = isMemory
    ? 'You are investigating one memory-eval result. The answer, judge verdict, and recalled ' +
      'facts are inline. The full retrieval pipeline and the remember/ingest trace are in ledger ' +
      'files on disk — read them directly (paths below); don’t search for them.'
    : 'You are investigating one knowledge-eval result. The answers and judge verdicts are inline. ' +
      'The full retrieval pipeline and node-level cost/timeline are in ledger files on disk — read ' +
      'them directly (paths below); don’t search for them.';

  const lines: string[] = [preamble, ''];

  // Header.
  const meta = [row.category, row.difficulty].filter(Boolean).join(' · ');
  const trackLabel = isMemory ? 'Mem-eval' : 'Knowledge-eval';
  lines.push(`# ${trackLabel} Q "${row.question}"${meta ? `  (${meta})` : ''}`);
  const ctx = [`track: ${track}`, engine ? `engine: ${engine}` : '', corpus ? `corpus: ${corpus}` : '']
    .filter(Boolean)
    .join(' · ');
  if (ctx) lines.push(ctx);
  if (row.requires_graph) lines.push('requires_graph: true');
  lines.push(`Ideal: ${row.gold || '(none given)'}`);
  lines.push('');

  // Per-leg answer + judge + (memory) recalled facts.
  for (const mode of legColumns) {
    const leg = row.legs[mode];
    if (!leg) continue;
    const mark = leg.mark || '(unjudged)';
    const cost = typeof leg.cost_usd === 'number' && leg.cost_usd > 0 ? ` · $${leg.cost_usd.toFixed(4)}` : '';
    lines.push(`## ${legName(mode)} — ${mark}  (${leg.elapsed_ms}ms${cost})`);
    lines.push(`answer: ${leg.answer?.trim() || '(no answer)'}`);
    if (leg.reason) lines.push(`judge: ${leg.reason}`);
    const recalled = leg.recalled ?? [];
    if (recalled.length > 0) {
      lines.push(`recalled facts (${recalled.length}):`);
      for (const r of recalled) lines.push(recalledLine(r));
    }
    lines.push('');
  }

  // Ledger-file pointers — the heavy, fully-persisted depth, keyed by each leg's run_id.
  const base = logDir || 'logs';
  const traceDir = joinPath(base, 'retrieval_trace');
  const graphLog = joinPath(base, 'graph.log');
  const ptr: string[] = ['Ledger files (full fidelity):'];
  for (const mode of legColumns) {
    const leg = row.legs[mode];
    const runId = leg?.run_id;
    if (!runId) continue;
    if (TRACEABLE_LEGS.has(mode)) {
      ptr.push(`  ${legName(mode)} retrieval  ${joinPath(traceDir, `${safeRunId(runId)}.jsonl`)}`);
    }
    ptr.push(`  ${legName(mode)} cost       grep run_id=${runId} in ${graphLog}`);
  }
  if (isMemory) {
    // The remember/ingest trace answers "was the fact ever extracted?" — a retrieval miss vs an
    // ingestion miss. Pointed at the directory (the ingest run_id is per-rebuild and volatile);
    // the most recent .jsonl is the latest remember.
    ptr.push(`  remember/ingest  ${joinPath(base, 'ingest_trace')}   (dir; most recent .jsonl = latest rebuild)`);
  }
  if (!logDir) ptr.push('  (paths are relative to the workspace root)');
  lines.push(...ptr);

  // Fill-in line for the user's specific ask.
  lines.push('', '---', 'My question: ');

  return lines.join('\n');
}
