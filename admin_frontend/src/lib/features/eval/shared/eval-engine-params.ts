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

export type Param = { label: string; value: string };

/** Model line (id + tuning-profile params), tagged by which Settings column it belongs to:
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

/** One model's tuning-profile params, compact (e.g. "temp 0.2 · max 1600 · think low"). Empty
 *  string when the model has no tuning profile (embedders) or the profile id isn't found. */
export function tuningChips(prefs: WorkspacePreferences, profileId: string | undefined): string {
  const p = profileId ? prefs.tuning_profiles?.[profileId] : undefined;
  if (!p) return '';
  const bits = [`temp ${p.temperature}`, `max ${p.max_tokens}`];
  if (p.thinking) bits.push(`think ${p.thinking}`);
  return bits.join(' · ');
}

/** Model lines for the Settings columns. Memory adds the Small model; knowledge answers with the
 *  production answering pipeline (so its Answer line shows that). The judge model grades both. */
export function modelLines(prefs: WorkspacePreferences, cfg: EvalTrackConfig): ModelLine[] {
  const g = prefs.graph;
  const a = prefs.knowledge.answering;
  const out: ModelLine[] = [
    {
      label: 'Extraction',
      model: dash(g.extraction_model),
      tuning: tuningChips(prefs, g.extraction_tuning_profile),
      group: 'ingest'
    }
  ];
  if (cfg.track === 'memory')
    out.push({
      label: 'Small',
      model: dash(g.small_model),
      tuning: tuningChips(prefs, g.small_tuning_profile),
      group: 'ingest'
    });
  out.push({ label: 'Embedder', model: dash(g.embedder_model), tuning: '', group: 'ingest' });
  // Answer + judge use SEPARATE eval models/tuning (graph.eval.answer_* / judge_*), each falling
  // back to the knowledge answering model when unset.
  const answering = a.model_resolved ?? a.model;
  const ev = g.eval;
  // Memory recall is fully agentic (runner_memory._recall_via_agent → run_retrieval), so surface the
  // RETRIEVAL AGENT's model FIRST — before the answer/judge models. Its model falls back to the eval
  // answer model, then the knowledge answering model (resolve_eval_retrieval_llm). Memory-only: the
  // knowledge track answers with the production pipeline and has no retrieval agent.
  if (cfg.track === 'memory')
    out.push({
      label: 'Retrieval',
      model: dash(ev.retrieval_model || ev.answer_model || answering),
      tuning: tuningChips(prefs, ev.retrieval_tuning_profile),
      group: 'recall'
    });
  out.push({
    label: 'Answer',
    model: dash(cfg.track === 'memory' ? ev.answer_model || answering : answering),
    tuning: tuningChips(
      prefs,
      cfg.track === 'memory' ? ev.answer_tuning_profile : prefs.knowledge.default_tuning_profile
    ),
    group: 'recall'
  });
  out.push({
    label: 'Judge',
    model: dash(ev.judge_model || answering),
    tuning: tuningChips(prefs, ev.judge_tuning_profile),
    group: 'recall'
  });
  return out;
}

/** Answer-prompt picker options (memory track). The locked "default" profile is exposed as value
 *  '' so an unset run maps to it; the others by id. Authored in Preferences → Graph Engine. */
export function answerPromptOptions(
  prefs: WorkspacePreferences | null
): { id: string; label: string }[] {
  const lib = prefs?.graph.eval.answer_prompts ?? {};
  const def = lib['default'];
  const out = [{ id: '', label: def ? def.label : 'Default' }];
  for (const [id, p] of Object.entries(lib)) {
    if (id === 'default') continue;
    out.push({ id, label: p.label });
  }
  return out;
}

/** The active retrieval-agent system prompt's label — provenance for the agentic recall leg (mirrors
 *  answerPromptLabelFor). Resolves `active_retrieval_agent_prompt_id` against the prompt library,
 *  falling back to the locked default profile, then 'Default'. */
function retrievalAgentPromptLabel(prefs: WorkspacePreferences): string {
  const ev = prefs.graph.eval;
  const id = (ev.active_retrieval_agent_prompt_id || '').trim() || 'default';
  const lib = ev.retrieval_agent_prompts ?? {};
  return lib[id]?.label ?? lib['default']?.label ?? 'Default';
}

/** The selected profile's label — the run's answer-prompt provenance, for the settings strip. */
export function answerPromptLabelFor(
  options: { id: string; label: string }[],
  answerPromptId: string
): string {
  return options.find((o) => o.id === answerPromptId)?.label ?? options[0]?.label ?? 'Default';
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
export function recallKnobs(
  prefs: WorkspacePreferences,
  cfg: EvalTrackConfig,
  answerPromptLabel: string
): Param[] {
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
    // BEFORE the answer-step knob. The old `memory.search.top_k` is dead on this path — the agent's
    // search tool draws its per-query limit from `retrieval_agent.limit_default` (search_tool._run_one),
    // so it's replaced by the agent's Search limit here.
    const ra = g.eval.retrieval_agent;
    out.push({ label: 'Agent turns', value: String(ra.max_agent_turns) });
    out.push({ label: 'Parallel', value: String(ra.max_parallel_searches) });
    out.push({ label: 'Search limit', value: String(ra.limit_default) });
    out.push({ label: 'Retrieval prompt', value: retrievalAgentPromptLabel(prefs) });
    out.push({ label: 'Answer prompt', value: answerPromptLabel });
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
  const answer = prefs.knowledge.answering.model_resolved ?? prefs.knowledge.answering.model ?? '';
  return `${g.backend} · recipe=${g.search_recipe} · hops=${g.k_hop}${answer ? ` · answer=${answer}` : ''}`;
}
