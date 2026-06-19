/**
 * Pure builder for the Eval activity feed lines.
 *
 * Turns the structured run state (setup activity trail + per-question rows +
 * terminal status) into human-readable lines: "episode 3/35 → Qdrant · …",
 * "graph extraction 12/35…", "Q 2/5 [✗→✓ Δ+3] …".
 *
 * Kept side-effect-free (no runes) so it can drive both the live terminal AND
 * the collapsed Activity header's "current line", and stay unit-testable.
 */
import type { EvalSetupProgressPayload } from '$lib/features/knowledge/shared/knowledge-events';
import type { EvalRow, EvalStatus } from '$lib/features/eval/state/eval-model.svelte';

export type ActivityTone = 'muted' | 'info' | 'success' | 'warn' | 'error';
export type ActivityLine = { text: string; tone: ActivityTone };

export type ActivityLinesInput = {
  setupEvents: EvalSetupProgressPayload[];
  rows: EvalRow[];
  status: EvalStatus;
  totalQuestions: number;
  summaryGate?: 'proceed' | 'pivot' | 'n/a' | null;
  summaryElapsedMs?: number | null;
  failureMessage?: string | null;
};

function setupLine(e: EvalSetupProgressPayload): ActivityLine {
  if (e.index && e.total) {
    // Per-episode progress.
    if (e.phase === 'build_graph' || e.phase === 'graph_build') {
      return { tone: 'info', text: `  graph extraction ${e.index}/${e.total}…` };
    }
    if (e.phase === 'remember') {
      const snip = e.snippet ? ` — ${e.snippet}` : '';
      // Show the ABSOLUTE 1-based episode number (e.g. "episode 11"), with the window position
      // as a quiet hint — never a bare window-relative counter that misreads a mid-corpus batch.
      const no = e.episode_no ?? e.index;
      return { tone: 'muted', text: `  ingested episode ${no} (${e.index}/${e.total})${snip}` };
    }
    const head = `  episode ${e.index}/${e.total} → Qdrant`;
    const title = e.title ? ` · ${e.title}` : '';
    const snippet = e.snippet ? ` — ${e.snippet}` : '';
    return { tone: 'muted', text: `${head}${title}${snippet}` };
  }
  // Phase-start lines.
  if (e.phase === 'ingest_synthetic')
    return {
      tone: 'info',
      text: `▶ ingesting synthetic corpus${e.file_count ? ` (${e.file_count} files)` : ''}…`
    };
  if (e.phase === 'remember') {
    // Header carries the ABSOLUTE episode range this batch covers (e.g. "episodes 11–30"), so
    // the user sees exactly which turns are being ingested — not just how many.
    const range = e.from && e.to ? ` ${e.from}–${e.to}` : '';
    const count = e.episode_count ? ` (${e.episode_count} episodes)` : '';
    return { tone: 'info', text: `▶ ingesting episodes${range}${count}…` };
  }
  if (e.phase === 'build_graph' || e.phase === 'graph_build')
    return {
      tone: 'info',
      text: `▶ building knowledge graph${e.episode_count ? ` (${e.episode_count} episodes)` : ''}…`
    };
  if (e.phase === 'remember_done') {
    // Ingest phase finished — report the folded graph-build cost (streamed before any question).
    const c = e.ingest_cost_usd ?? 0;
    const cost = c > 0 ? ` · ingest ≈ $${c < 0.01 ? c.toFixed(4) : c.toFixed(2)}` : '';
    return {
      tone: 'success',
      text: `✓ ingested${e.episode_count ? ` ${e.episode_count} episodes` : ''}${cost}`
    };
  }
  return { tone: 'info', text: `▶ ${e.phase}…` };
}

function questionLines(r: EvalRow): ActivityLine[] {
  // Memory track: single recall leg — show the mark (if judged) / recall count + the answer.
  if (r.track === 'memory') {
    const leg = r.legs.recall;
    const recalled = leg?.recalled ?? [];
    const tag = leg?.mark ? leg.mark : `recalled ${recalled.length}`;
    const head: ActivityLine = {
      tone: leg?.mark === '✗' ? 'warn' : recalled.length > 0 ? 'muted' : 'warn',
      text: `Q ${r.index + 1}/${r.total} [${tag}] ${r.question}`
    };
    const out = [head];
    const top = leg?.answer || recalled[0];
    if (top) out.push({ tone: 'muted', text: `    ↳ ${top}` });
    return out;
  }
  // Compact per-leg marks, e.g. "flat:✗ graphiti:✓"; only the run's legs.
  const modes = Object.keys(r.legs);
  const marks = modes.map((m) => `${m}:${r.legs[m].mark}`).join(' ');
  const delta = r.delta && r.delta !== '0' ? ` Δ${r.delta}` : '';
  const won = r.delta.startsWith('+');
  const lost = r.delta.startsWith('-');
  const head: ActivityLine = {
    tone: won ? 'success' : lost ? 'warn' : 'muted',
    text: `Q ${r.index + 1}/${r.total} [${marks}${delta}] ${r.question}`
  };
  // Prefer the graph leg's preview (graphiti), else flat, else any leg.
  const ans =
    r.legs.graphiti?.answer_preview ||
    r.legs.flat?.answer_preview ||
    (modes.length ? r.legs[modes[0]].answer_preview : '');
  const lines = [head];
  if (ans) lines.push({ tone: 'muted', text: `    ↳ ${ans}` });
  return lines;
}

/** The single line shown in the COLLAPSED Activity header — the live "current" item, not the
 *  rolled-up counter. While in-flight it's the most recent processed line: the last question once
 *  any have completed, else the latest ingestion/setup line (so the ingest phase shows the current
 *  episode), else "preparing…". Terminal runs show the outcome (verdict / cancelled / failed). */
export function activityHeaderLine(input: ActivityLinesInput): string {
  const {
    setupEvents,
    rows,
    status,
    summaryGate = null,
    summaryElapsedMs = null,
    failureMessage = null
  } = input;
  if (status === 'completed' && summaryGate) {
    const ms = summaryElapsedMs ? ` · ${summaryElapsedMs}ms` : '';
    if (summaryGate === 'proceed') return `✅ PROCEED${ms}`;
    if (summaryGate === 'pivot') return `❌ PIVOT${ms}`;
    return `ℹ️ done${ms}`;
  }
  if (status === 'cancelled') return '🛑 run cancelled';
  if (status === 'failed') return `❌ failed${failureMessage ? `: ${failureMessage}` : ''}`;
  // In-flight: the live current item.
  if (rows.length > 0) {
    const last = [...rows].sort((a, b) => a.index - b.index)[rows.length - 1];
    return questionLines(last)[0].text.trim();
  }
  if (setupEvents.length > 0) return setupLine(setupEvents[setupEvents.length - 1]).text.trim();
  return status === 'starting' ? 'preparing…' : '';
}

export function buildActivityLines(input: ActivityLinesInput): ActivityLine[] {
  const {
    setupEvents,
    rows,
    status,
    totalQuestions,
    summaryGate = null,
    summaryElapsedMs = null,
    failureMessage = null
  } = input;
  const out: ActivityLine[] = [];
  for (const e of setupEvents) out.push(setupLine(e));
  for (const r of [...rows].sort((a, b) => a.index - b.index)) out.push(...questionLines(r));
  if (status === 'running' && rows.length < totalQuestions) {
    out.push({
      tone: 'info',
      text: `… ${rows.length}/${totalQuestions} questions done — running…`
    });
  } else if (status === 'starting') {
    out.push({ tone: 'info', text: '… preparing…' });
  } else if (status === 'completed' && summaryGate) {
    const ms = summaryElapsedMs ? ` · ${summaryElapsedMs}ms` : '';
    if (summaryGate === 'proceed') out.push({ tone: 'success', text: `✅ PROCEED${ms}` });
    else if (summaryGate === 'pivot') out.push({ tone: 'warn', text: `❌ PIVOT${ms}` });
    else out.push({ tone: 'info', text: `ℹ️ done${ms}` });
  } else if (status === 'cancelled') {
    out.push({ tone: 'warn', text: '🛑 run cancelled' });
  } else if (status === 'failed') {
    out.push({ tone: 'error', text: `❌ failed${failureMessage ? `: ${failureMessage}` : ''}` });
  }
  return out;
}
