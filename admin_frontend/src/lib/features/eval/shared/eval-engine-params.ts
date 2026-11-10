/**
 * Pure derivation of the read-only "engine params" strip shown on the Execute tab — the
 * preference values that actually drive an eval run, per track. These were inline `$derived.by`
 * closures in EvalPanel.svelte that read the component's `prefs` + `cfg`; extracted here as
 * side-effect-free functions so they're unit-testable and the panel/panes stay thin.
 *
 * The shared Graphiti graph engine (graph.*) governs memory recall AND the knowledge graphiti
 * leg, so those knobs are listed for both tracks; the flat (Qdrant hybrid) retrieval knobs
 * (knowledge.retrieval.*) are listed only for the knowledge track. Reranker chips appear only
 * when actually engaged (cross-encoder recipe / flat reranker enabled).
 */
import type { WorkspacePreferences } from '$lib/api/preferences';
import type { EvalTrackConfig } from '$lib/features/eval/shared/eval-tracks';
import { resolveJobProfile, type HiroJobId } from '$lib/catalog/hiro-jobs';

export type Param = { label: string; value: string };

/** Model line (id + the AI profile's tuning), tagged by which Settings column it belongs to:
 *  ingestion models build the graph (extraction/small/embedder); the answer model drives recall. */
export type ModelLine = {
  label: string;
  model: string;
  tuning: string;
  group: 'ingest' | 'recall';
};

const TEMPORAL_LENS_LABEL: Record<'current' | 'all', string> = {
  current: 'current only',
  all: 'include historical'
};

const dash = (v: string | null | undefined): string => (v && String(v).trim() ? String(v) : '—');
const onOff = (b: boolean): string => (b ? 'on' : 'off');

/** One job's AI profile, compact (Phase 7b step 5; was its tuning profile): "Hiro's chat · temp 0.2 ·
 *  max 1600 · think low", "· from Eval: answer" when the job borrows another job's profile. Empty
 *  when no profile applies (or the id names a missing profile). */
export function profileChips(prefs: WorkspacePreferences, job: HiroJobId): string {
  const resolved = resolveJobProfile(prefs, job);
  const p = resolved?.profile;
  if (!resolved || !p) return '';
  const bits = [p.label];
  if (p.temperature != null) bits.push(`temp ${p.temperature}`);
  if (p.max_tokens != null) bits.push(`max ${p.max_tokens}`);
  if (p.thinking) bits.push(`think ${p.thinking}`);
  if (resolved.from.id !== job) bits.push(`from ${resolved.from.label}`);
  return bits.join(' · ');
}

/** The model a job runs with (its AI profile's, or the profile of the job it falls back to). */
function jobModel(prefs: WorkspacePreferences, job: HiroJobId): string {
  return dash(resolveJobProfile(prefs, job)?.profile?.model);
}

const line = (
  prefs: WorkspacePreferences,
  label: string,
  job: HiroJobId,
  group: ModelLine['group']
): ModelLine => ({ label, model: jobModel(prefs, job), tuning: profileChips(prefs, job), group });

/** Model lines for the Settings columns. Memory adds the Small model; knowledge answers with the
 *  production answering pipeline (so its Answer line shows that job). The judge model grades both.
 *  Each line is one of Hiro's jobs and its AI profile (Phase 7b step 5), resolved on `prefs` the way
 *  the server does (its own field, else the job it falls back to). */
export function modelLines(prefs: WorkspacePreferences, cfg: EvalTrackConfig): ModelLine[] {
  const out: ModelLine[] = [line(prefs, 'Extraction', 'graph_extraction', 'ingest')];
  if (cfg.track === 'memory') out.push(line(prefs, 'Small', 'graph_small', 'ingest'));
  out.push({ label: 'Embedder', model: dash(prefs.graph.embedder_model), tuning: '', group: 'ingest' });
  // Memory recall is fully agentic (runner_memory._recall_via_agent → run_retrieval), so surface the
  // RETRIEVAL AGENT's profile FIRST — before the answer/judge. Unset, it borrows the eval answer job's
  // (then Hiro's chat). Memory-only: the knowledge track answers with the production pipeline.
  if (cfg.track === 'memory') out.push(line(prefs, 'Retrieval', 'eval_retrieval', 'recall'));
  out.push(line(prefs, 'Answer', cfg.track === 'memory' ? 'eval_answer' : 'knowledge', 'recall'));
  out.push(line(prefs, 'Judge', 'eval_judge', 'recall'));
  return out;
}

/** The active retrieval-agent system prompt's label — provenance for the agentic recall leg.
 *  Resolves `active_retrieval_agent_prompt_id` against the prompt library, falling back to the
 *  locked default profile, then 'Default'. */
function retrievalAgentPromptLabel(prefs: WorkspacePreferences): string {
  const ev = prefs.graph.eval;
  const id = (ev.active_retrieval_agent_prompt_id || '').trim() || 'default';
  const lib = ev.retrieval_agent_prompts ?? {};
  return lib[id]?.label ?? lib['default']?.label ?? 'Default';
}

/** The active answer-prompt profile's label — the run's answer-prompt provenance, for the settings
 *  strip. Resolves the persisted `active_answer_prompt_id` against the answer-prompt library
 *  (mirrors retrievalAgentPromptLabel); falls back to the locked default profile, then 'Default'. */
function answerPromptLabel(prefs: WorkspacePreferences): string {
  const ev = prefs.graph.eval;
  const id = (ev.active_answer_prompt_id || '').trim() || 'default';
  const lib = ev.answer_prompts ?? {};
  return lib[id]?.label ?? lib['default']?.label ?? 'Default';
}

/** Non-model ingestion knobs. Extraction ontology (open vs typed) governs what the graph build
 *  extracts, so it applies to BOTH tracks; knowledge chunking knobs are knowledge-only. */
export function ingestKnobs(prefs: WorkspacePreferences, cfg: EvalTrackConfig): Param[] {
  const g = prefs.graph;
  const out: Param[] = [
    { label: 'Extraction ontology', value: g.entity_ontology === 'typed' ? 'typed' : 'open' }
  ];
  if (cfg.track !== 'memory') {
    const c = prefs.knowledge.chunking;
    out.push(
      { label: 'Chunk size', value: String(c.chunk_size) },
      { label: 'Chunk overlap', value: String(c.chunk_overlap) },
      { label: 'Structural ctx', value: onOff(c.embed_structural_context) }
    );
  }
  return out;
}

/** Retrieval + answering knobs at question time. Memory shows recall top-k + the answer-prompt
 *  provenance; knowledge shows the flat (Qdrant hybrid) retrieval knobs + flat reranker. */
export function recallKnobs(prefs: WorkspacePreferences, cfg: EvalTrackConfig): Param[] {
  const g = prefs.graph;
  const out: Param[] = [
    { label: 'Temporal lens', value: TEMPORAL_LENS_LABEL[g.temporal_default] ?? g.temporal_default },
    { label: 'Hops', value: String(g.k_hop) },
    { label: 'Recipe', value: g.search_recipe },
    { label: 'Scope', value: g.search_scope },
    { label: 'Sim floor', value: String(g.sim_min_score) }
  ];
  if (g.search_recipe === 'cross_encoder') {
    out.push({ label: 'Graph reranker', value: dash(g.reranker.model_id) });
    out.push({ label: 'Rerank floor', value: String(g.reranker.min_relevance) });
  }
  if (cfg.track === 'memory') {
    // Memory recall is fully agentic: show the retrieval AGENT's loop caps + active system prompt
    // BEFORE the answer-step knob. (The old `memory.search.top_k` recall-depth pref was removed — the
    // agent's search tool draws its per-query result count from `retrieval_agent.limit_default`
    // (search_tool._run_one), surfaced as the Search limit below.)
    const ra = g.eval.retrieval_agent;
    out.push({ label: 'Agent turns', value: String(ra.max_agent_turns) });
    out.push({ label: 'Parallel', value: String(ra.max_parallel_searches) });
    out.push({ label: 'Search limit', value: String(ra.limit_default) });
    out.push({ label: 'Retrieval prompt', value: retrievalAgentPromptLabel(prefs) });
    out.push({ label: 'Answer prompt', value: answerPromptLabel(prefs) });
  } else {
    const r = prefs.knowledge.retrieval;
    out.push({ label: 'Retrieval top-k', value: String(r.top_k) });
    out.push({ label: 'Flat min score', value: String(r.min_score) });
    out.push({ label: 'Hybrid', value: onOff(r.hybrid) });
    out.push({ label: 'Prefetch', value: String(r.prefetch_limit) });
    if (r.reranker.enabled) {
      out.push({ label: 'Flat reranker', value: dash(r.reranker.model_id) });
      out.push({ label: 'Rerank top-n', value: String(r.reranker.top_n) });
    }
  }
  out.push({ label: 'Observability', value: g.observability });
  return out;
}

/** Compact engine line for the "Copy for AI" brief — the few knobs that actually shape recall. */
export function aiEngineLine(prefs: WorkspacePreferences | null): string {
  if (!prefs) return '';
  const g = prefs.graph;
  const answer = prefs.knowledge.answering.model_resolved ?? '';
  return `${g.backend} · recipe=${g.search_recipe} · hops=${g.k_hop}${answer ? ` · answer=${answer}` : ''}`;
}
