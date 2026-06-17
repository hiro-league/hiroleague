import type { WorkspacePreferences } from '$lib/api/preferences';
import { modalityKeys } from '$lib/features/preferences/shared/preferences-constants';

export function cloneWorkspacePreferences(prefs: WorkspacePreferences): WorkspacePreferences {
  return JSON.parse(JSON.stringify(prefs)) as WorkspacePreferences;
}

/** Build the patch payload sent to `patchPreferences` — only changed paths. */
export function editsForSave(
  baseline: WorkspacePreferences,
  draft: WorkspacePreferences
): Record<string, unknown> {
  const edits: Record<string, unknown> = {};
  const add = (path: string, before: unknown, after: unknown) => {
    if (JSON.stringify(before) !== JSON.stringify(after)) edits[path] = after;
  };
  add('llm.default_chat', baseline.llm.default_chat, draft.llm.default_chat || null);
  add('llm.default_stt', baseline.llm.default_stt, draft.llm.default_stt || null);
  add('llm.default_tts', baseline.llm.default_tts, draft.llm.default_tts || null);
  add(
    'llm.default_tuning_profile',
    baseline.llm.default_tuning_profile,
    draft.llm.default_tuning_profile
  );
  // Memory rides the shared Graphiti engine now (mem0 → Graphiti), so `enabled` is a real
  // toggle — no longer derived from the legacy mem0 model fields (which forced it off in the
  // UI and blocked enabling Graphiti memory).
  add('memory.enabled', baseline.memory.enabled, draft.memory.enabled);
  add(
    'memory.default_tuning_profile',
    baseline.memory.default_tuning_profile,
    draft.memory.default_tuning_profile
  );
  // A1: user's name (Graphiti speaker anchor). Must be listed here or Save silently drops it —
  // editsForSave only sends paths it enumerates, so a new field is otherwise lost on save.
  add('memory.user_name', baseline.memory.user_name, draft.memory.user_name);
  for (const key of modalityKeys) {
    add(`media.input.${key}`, baseline.media.input[key], draft.media.input[key]);
    add(`media.output.${key}`, baseline.media.output[key], draft.media.output[key]);
  }
  add('memory.search.enabled', baseline.memory.search.enabled, draft.memory.search.enabled);
  add('memory.extraction.enabled', baseline.memory.extraction.enabled, draft.memory.extraction.enabled);
  add('memory.search.top_k', baseline.memory.search.top_k, draft.memory.search.top_k);
  add(
    'knowledge.default_embedding_model',
    baseline.knowledge.default_embedding_model,
    draft.knowledge.default_embedding_model || null
  );
  add('knowledge.retrieval.top_k', baseline.knowledge.retrieval.top_k, draft.knowledge.retrieval.top_k);
  add('knowledge.retrieval.min_score', baseline.knowledge.retrieval.min_score, draft.knowledge.retrieval.min_score);
  add('knowledge.retrieval.hybrid', baseline.knowledge.retrieval.hybrid, draft.knowledge.retrieval.hybrid);
  add(
    'knowledge.retrieval.sparse_model',
    baseline.knowledge.retrieval.sparse_model,
    draft.knowledge.retrieval.sparse_model
  );
  add(
    'knowledge.retrieval.prefetch_limit',
    baseline.knowledge.retrieval.prefetch_limit,
    draft.knowledge.retrieval.prefetch_limit
  );
  add(
    'knowledge.retrieval.reranker.enabled',
    baseline.knowledge.retrieval.reranker.enabled,
    draft.knowledge.retrieval.reranker.enabled
  );
  add(
    'knowledge.retrieval.reranker.model_id',
    baseline.knowledge.retrieval.reranker.model_id,
    draft.knowledge.retrieval.reranker.model_id || null
  );
  add(
    'knowledge.retrieval.reranker.top_n',
    baseline.knowledge.retrieval.reranker.top_n,
    draft.knowledge.retrieval.reranker.top_n
  );
  add(
    'knowledge.retrieval.reranker.device',
    baseline.knowledge.retrieval.reranker.device,
    draft.knowledge.retrieval.reranker.device
  );
  add(
    'knowledge.retrieval.reranker.batch_size',
    baseline.knowledge.retrieval.reranker.batch_size,
    draft.knowledge.retrieval.reranker.batch_size
  );
  add(
    'knowledge.default_tuning_profile',
    baseline.knowledge.default_tuning_profile,
    draft.knowledge.default_tuning_profile
  );
  add('knowledge.answering.model', baseline.knowledge.answering.model, draft.knowledge.answering.model || null);
  add('knowledge.answering.prompt', baseline.knowledge.answering.prompt, draft.knowledge.answering.prompt);
  add('knowledge.answering.cite_sources', baseline.knowledge.answering.cite_sources, draft.knowledge.answering.cite_sources);
  add(
    'knowledge.answering.language_policy',
    baseline.knowledge.answering.language_policy,
    draft.knowledge.answering.language_policy
  );
  add('knowledge.chunking.chunk_size', baseline.knowledge.chunking.chunk_size, draft.knowledge.chunking.chunk_size);
  add(
    'knowledge.chunking.chunk_overlap',
    baseline.knowledge.chunking.chunk_overlap,
    draft.knowledge.chunking.chunk_overlap
  );
  add(
    'knowledge.chunking.embed_structural_context',
    baseline.knowledge.chunking.embed_structural_context,
    draft.knowledge.chunking.embed_structural_context
  );
  add(
    'knowledge.chunking.markdown.respect_headings',
    baseline.knowledge.chunking.markdown.respect_headings,
    draft.knowledge.chunking.markdown.respect_headings
  );
  add('knowledge.rewrite.prompt', baseline.knowledge.rewrite.prompt, draft.knowledge.rewrite.prompt);
  add('knowledge.rewrite.default_on', baseline.knowledge.rewrite.default_on, draft.knowledge.rewrite.default_on);
  // Knowledge Graph (Graphiti) prefs were missing here, so backend/model/etc. edits were
  // silently dropped from the save payload (UI showed "saved" but the value snapped back).
  add('graph.backend', baseline.graph.backend, draft.graph.backend);
  add(
    'graph.extraction_model',
    baseline.graph.extraction_model,
    draft.graph.extraction_model || null
  );
  add(
    'graph.extraction_tuning_profile',
    baseline.graph.extraction_tuning_profile,
    draft.graph.extraction_tuning_profile
  );
  add(
    'graph.small_model',
    baseline.graph.small_model,
    draft.graph.small_model || null
  );
  add(
    'graph.small_tuning_profile',
    baseline.graph.small_tuning_profile,
    draft.graph.small_tuning_profile
  );
  add(
    'graph.embedder_model',
    baseline.graph.embedder_model,
    draft.graph.embedder_model || null
  );
  add(
    'graph.temporal_default',
    baseline.graph.temporal_default,
    draft.graph.temporal_default
  );
  add('graph.k_hop', baseline.graph.k_hop, draft.graph.k_hop);
  add(
    'graph.search_recipe',
    baseline.graph.search_recipe,
    draft.graph.search_recipe
  );
  // Orthogonal to search_recipe: which legs (edges / +nodes / +nodes+episodes) participate
  // in recall. Backend rejects mmr+episodes via a cross-field validator; the UI greys the
  // illegal combo to make that visible.
  add(
    'graph.search_scope',
    baseline.graph.search_scope,
    draft.graph.search_scope
  );
  add(
    'graph.entity_ontology',
    baseline.graph.entity_ontology,
    draft.graph.entity_ontology
  );
  add(
    'graph.custom_extraction_instructions',
    baseline.graph.custom_extraction_instructions,
    draft.graph.custom_extraction_instructions
  );
  add(
    'graph.sim_min_score',
    baseline.graph.sim_min_score,
    draft.graph.sim_min_score
  );
  add(
    'graph.query_timeout_s',
    baseline.graph.query_timeout_s,
    draft.graph.query_timeout_s
  );
  add(
    'graph.observability',
    baseline.graph.observability,
    draft.graph.observability
  );
  add(
    'graph.reranker.model_id',
    baseline.graph.reranker.model_id,
    draft.graph.reranker.model_id || null
  );
  add(
    'graph.reranker.min_relevance',
    baseline.graph.reranker.min_relevance,
    draft.graph.reranker.min_relevance
  );
  add(
    'graph.reranker.device',
    baseline.graph.reranker.device,
    draft.graph.reranker.device || null
  );
  // Mem-eval answer-prompt library — sent as ONE path (whole dict), like tuning_profiles below;
  // the schema-driven PATCH accepts a whole-object write here.
  add('graph.eval.answer_prompts', baseline.graph.eval.answer_prompts, draft.graph.eval.answer_prompts);
  add(
    'graph.eval.judge_prompt',
    baseline.graph.eval.judge_prompt,
    draft.graph.eval.judge_prompt
  );
  // Separated eval answer + judge models / tuning profiles (null model → fall back to the
  // answering model). Each enumerated so a UI edit actually persists.
  add(
    'graph.eval.answer_model',
    baseline.graph.eval.answer_model,
    draft.graph.eval.answer_model || null
  );
  add(
    'graph.eval.answer_tuning_profile',
    baseline.graph.eval.answer_tuning_profile,
    draft.graph.eval.answer_tuning_profile
  );
  add(
    'graph.eval.judge_model',
    baseline.graph.eval.judge_model,
    draft.graph.eval.judge_model || null
  );
  add(
    'graph.eval.judge_tuning_profile',
    baseline.graph.eval.judge_tuning_profile,
    draft.graph.eval.judge_tuning_profile
  );
  add(
    'graph.eval.show_event_time',
    baseline.graph.eval.show_event_time,
    draft.graph.eval.show_event_time
  );
  add(
    'graph.eval.show_expired_at',
    baseline.graph.eval.show_expired_at,
    draft.graph.eval.show_expired_at
  );
  add(
    'graph.eval.show_superseded',
    baseline.graph.eval.show_superseded,
    draft.graph.eval.show_superseded
  );
  add(
    'graph.view.large_type_threshold',
    baseline.graph.view.large_type_threshold,
    draft.graph.view.large_type_threshold
  );
  add('chat.instructions', baseline.chat.instructions, draft.chat.instructions);
  add('chat.max_messages', baseline.chat.max_messages, draft.chat.max_messages);
  add('chat.cite_sources', baseline.chat.cite_sources, draft.chat.cite_sources);
  add('chat.tools_enabled', baseline.chat.tools_enabled, draft.chat.tools_enabled);
  add('tuning_profiles', baseline.tuning_profiles, draft.tuning_profiles);
  return edits;
}
