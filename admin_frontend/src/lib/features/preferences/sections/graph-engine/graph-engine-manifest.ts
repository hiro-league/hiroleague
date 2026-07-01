/**
 * Declarative manifest for the Memory (graph-engine) tab — the Tier-2.1 prototype.
 *
 * This DATA replaces the six hand-written `Graph*Card.svelte` components: `PrefManifestCard` /
 * `PrefFieldRenderer` turn it into the same widgets, including the two cards that used to need bespoke
 * components — the reranker (body wrapped in a `gated` field spec: banner + disabled fieldset while
 * `search_recipe !== 'cross_encoder'`) and the retrieval-agent caps (card-level `validate`: the
 * `limit_min ≤ limit_default ≤ limit_max` cross-field check, registered via `ctrl.setSectionError`).
 *
 * The tab's search/arrow-nav order is DERIVED from this manifest (`GRAPH_ENGINE_FIELD_ORDER`, spread
 * into `PREFERENCE_FIELD_ORDER`), so render order and search order can't drift — adding or reordering
 * a field here updates both at once. A test asserts the manifest covers exactly the editable schema
 * paths the tab owns.
 */
import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
import {
  GRAPH_OBSERVABILITY_LABELS,
  GRAPH_SEARCH_RECIPE_LABELS,
  GRAPH_SEARCH_SCOPE_LABELS,
  GRAPH_TEMPORAL_DEFAULT_LABELS
} from '$lib/features/preferences/shared/preferences-enum-labels';
import type { WorkspacePreferences } from '$lib/api/preferences';
import type { PrefSelectOption } from '$lib/features/preferences/shared/preferences-field-options';
import { validateRetrievalAgentLimits } from '$lib/features/preferences/sections/graph-engine/retrieval-agent-limits';
import {
  manifestFieldPaths,
  type PrefTabManifest
} from '$lib/features/preferences/widgets/manifest/manifest-types';

// Static enum labels for the ontology select (validated against the schema enum by PrefSelectField).
const ONTOLOGY_OPTIONS: Record<string, string> = {
  open: 'Open (no predefined types)',
  typed: 'Typed (Person / Place / Organization / Event / Object)'
};

const EXTRACTION_INSTRUCTIONS_PLACEHOLDER =
  'e.g. Capture first-person preferences, goals, habits, and activities as facts even when only the speaker is named; treat the activity, topic, or object as the second entity.';

// Both episodes-inclusive scopes mount the BM25-only episodes leg (no MMR reranker) — mirror the
// backend's KNOWLEDGE_GRAPH_EPISODE_SCOPES gate so the UI disables MMR for either.
function episodesInScope(draft: WorkspacePreferences): boolean {
  return (
    draft.graph.search_scope === 'edges_and_episodes' ||
    draft.graph.search_scope === 'edges_nodes_episodes'
  );
}

/** Search-recipe options, with MMR disabled when the scope includes episodes (cross-field rule). */
export function graphSearchRecipeOptions(draft: WorkspacePreferences): PrefSelectOption[] {
  const mmrDisabled = episodesInScope(draft);
  return [
    { value: 'rrf', label: GRAPH_SEARCH_RECIPE_LABELS.rrf },
    {
      value: 'mmr',
      label: `${GRAPH_SEARCH_RECIPE_LABELS.mmr}${mmrDisabled ? ' (n/a with episodes)' : ''}`,
      disabled: mmrDisabled,
      title: mmrDisabled
        ? 'MMR is not supported when scope includes episodes (episodes are BM25-only and EpisodeReranker has no MMR). Switch scope, or pick RRF / Cross-encoder.'
        : undefined
    },
    { value: 'cross_encoder', label: GRAPH_SEARCH_RECIPE_LABELS.cross_encoder }
  ];
}

/** Search-scope options, with episodes scopes disabled when the recipe is MMR (cross-field rule). */
export function graphSearchScopeOptions(draft: WorkspacePreferences): PrefSelectOption[] {
  const mmrRecipe = draft.graph.search_recipe === 'mmr';
  const episodesDisabledTitle =
    'Episodes leg is BM25-only and EpisodeReranker has no MMR. Switch recipe to RRF or Cross-encoder, then select this scope.';
  return [
    { value: 'edges', label: GRAPH_SEARCH_SCOPE_LABELS.edges },
    { value: 'edges_and_nodes', label: GRAPH_SEARCH_SCOPE_LABELS.edges_and_nodes },
    {
      value: 'edges_and_episodes',
      label: `${GRAPH_SEARCH_SCOPE_LABELS.edges_and_episodes}${mmrRecipe ? ' (n/a with MMR)' : ''}`,
      disabled: mmrRecipe,
      title: mmrRecipe ? episodesDisabledTitle : undefined
    },
    {
      value: 'edges_nodes_episodes',
      label: `${GRAPH_SEARCH_SCOPE_LABELS.edges_nodes_episodes}${mmrRecipe ? ' (n/a with MMR)' : ''}`,
      disabled: mmrRecipe,
      title: mmrRecipe ? episodesDisabledTitle : undefined
    }
  ];
}

export const GRAPH_ENGINE_MANIFEST: PrefTabManifest = {
  cards: [
    {
      kind: 'card',
      id: 'graphExtraction',
      title: 'Graph Extraction',
      description:
        'Everything that builds the graph at ingest — the entity ontology, the heavy extraction model, the cheaper sub-step model, and the embedder. Changing any of these needs a re-ingest to rebuild the graph.',
      bodyId: PREFERENCES_SECTION_BODY_IDS.graphExtraction,
      collapsible: true,
      body: [
        {
          kind: 'grid',
          fields: [
            {
              kind: 'modelProfile',
              modelKind: 'chat',
              modelPath: 'graph.extraction_model',
              profilePath: 'graph.extraction_tuning_profile'
            },
            {
              kind: 'modelProfile',
              modelKind: 'chat',
              modelPath: 'graph.small_model',
              profilePath: 'graph.small_tuning_profile'
            },
            // Embedder (lock badge + download) + ontology share one grid column so the column beside
            // the tall instructions textarea stays filled.
            {
              kind: 'column',
              fields: [
                {
                  kind: 'embedder',
                  path: 'graph.embedder_model',
                  lockedPath: 'graph.embedder_model_locked',
                  heading: 'Embedder model'
                },
                { kind: 'select', path: 'graph.entity_ontology', options: ONTOLOGY_OPTIONS }
              ]
            },
            {
              kind: 'textarea',
              path: 'graph.custom_extraction_instructions',
              rows: 8,
              maxlength: 2000,
              placeholder: EXTRACTION_INSTRUCTIONS_PLACEHOLDER
            }
          ]
        }
      ]
    },
    {
      kind: 'card',
      id: 'graphEngine',
      title: 'Graph search & indexing',
      description:
        'The retrieval/ranking knobs the graph search uses, the observability tier, and the eval recalled-context format. These apply to both Agent Memory and Knowledge.',
      bodyId: PREFERENCES_SECTION_BODY_IDS.graphEngine,
      collapsible: true,
      body: [
        {
          kind: 'grid',
          fields: [
            { kind: 'select', path: 'graph.temporal_default', options: GRAPH_TEMPORAL_DEFAULT_LABELS },
            { kind: 'number', path: 'graph.k_hop' },
            { kind: 'select', path: 'graph.search_recipe', options: graphSearchRecipeOptions },
            { kind: 'select', path: 'graph.search_scope', options: graphSearchScopeOptions },
            { kind: 'number', path: 'graph.sim_min_score' },
            { kind: 'number', path: 'graph.query_timeout_s' },
            { kind: 'select', path: 'graph.observability', options: GRAPH_OBSERVABILITY_LABELS }
          ]
        },
        {
          kind: 'custom',
          component: 'graphEvalContextToggles',
          paths: ['graph.eval.show_event_time', 'graph.eval.show_expired_at', 'graph.eval.show_superseded']
        }
      ]
    },
    {
      kind: 'card',
      id: 'graphReranker',
      title: 'Graphiti Reranker (Cross-encoder)',
      description:
        'Reranks graph fact-search candidates with a real cross-encoder. Only active when the Search recipe above is set to Cross-encoder — otherwise these settings are disabled. Reuses the same reranker models as the flat path (cloud or local).',
      bodyId: PREFERENCES_SECTION_BODY_IDS.graphEngineReranker,
      collapsible: true,
      // Whole card gates on the search recipe via the field-level `gated` spec (banner + disabled
      // fieldset) — no card-level gating needed.
      body: [
        {
          kind: 'gated',
          disabledWhen: (d) => d.graph.search_recipe !== 'cross_encoder',
          banner: 'Set Search recipe → Cross-encoder above to enable these settings.',
          fields: [
            {
              kind: 'model',
              modelKind: 'rerank',
              path: 'graph.reranker.model_id',
              emptyFallback: 'llm.default_reranker'
            },
            {
              kind: 'grid',
              fields: [
                { kind: 'number', path: 'graph.reranker.min_relevance' },
                { kind: 'text', path: 'graph.reranker.device', placeholder: 'auto' }
              ]
            }
          ]
        }
      ]
    },
    {
      kind: 'card',
      id: 'graphEvalModels',
      title: 'Retrieval Agent Model & Prompt',
      description:
        'Model, profile, and system prompt for the agentic memory-retrieval loop (the Retrieval Agent caps below feed its placeholders).',
      bodyId: PREFERENCES_SECTION_BODY_IDS.graphEvalModels,
      collapsible: true,
      body: [
        {
          kind: 'grid',
          fields: [
            {
              kind: 'modelProfile',
              modelKind: 'chat',
              modelPath: 'graph.eval.retrieval_model',
              profilePath: 'graph.eval.retrieval_tuning_profile'
            },
            {
              kind: 'promptLibrary',
              dictPath: 'graph.eval.retrieval_agent_prompts',
              activeIdPath: 'graph.eval.active_retrieval_agent_prompt_id',
              hint: "Drives the memory eval's recall leg. Placeholders {MAX_AGENT_TURNS}, {MAX_PARALLEL_SEARCHES}, and {MAX_LIMIT} are filled from the Retrieval Agent caps card at runtime.",
              ariaLabel: 'Mem-eval retrieval agent prompt (markdown)',
              editorLabel: 'Retrieval agent prompt editor'
            }
          ]
        }
      ]
    },
    {
      kind: 'card',
      id: 'graphRetrievalAgent',
      title: 'Retrieval Agent',
      description:
        'Loop-bound caps for the agentic memory-retrieval path. One global value for eval and chat — tune without hand-editing preferences.json.',
      bodyId: PREFERENCES_SECTION_BODY_IDS.graphRetrievalAgent,
      collapsible: true,
      validate: (d) => validateRetrievalAgentLimits(d.graph.eval.retrieval_agent),
      body: [
        {
          kind: 'panel',
          title: 'Loop limits',
          fields: [
            {
              kind: 'grid',
              fields: [
                { kind: 'number', path: 'graph.eval.retrieval_agent.max_agent_turns' },
                { kind: 'number', path: 'graph.eval.retrieval_agent.max_parallel_searches' },
                { kind: 'number', path: 'graph.eval.retrieval_agent.hops_max' },
                { kind: 'number', path: 'graph.eval.retrieval_agent.limit_default' },
                { kind: 'number', path: 'graph.eval.retrieval_agent.limit_min' },
                { kind: 'number', path: 'graph.eval.retrieval_agent.limit_max' }
              ]
            }
          ]
        },
        {
          kind: 'panel',
          title: 'Answer context',
          hint: 'Caps the recalled set handed to the answerer + judge — score-ranked top-N per kind, each element sanitized to one capped line.',
          fields: [
            {
              kind: 'grid',
              fields: [
                { kind: 'number', path: 'graph.eval.max_elements_per_kind' },
                { kind: 'number', path: 'graph.eval.max_fact_chars' },
                { kind: 'number', path: 'graph.eval.max_episode_chars' },
                { kind: 'number', path: 'graph.eval.max_summary_chars' }
              ]
            }
          ]
        }
      ]
    },
    {
      kind: 'card',
      id: 'graphView',
      title: 'Graph view (display)',
      description:
        'Display-only settings for the shared Knowledge / Memories Graph tab. These tune the in-browser graph view and do not affect extraction, search, or retrieval.',
      bodyId: PREFERENCES_SECTION_BODY_IDS.graphView,
      collapsible: true,
      body: [{ kind: 'grid', fields: [{ kind: 'number', path: 'graph.view.large_type_threshold' }] }]
    }
  ]
};

/** Memory-tab field order, derived from the manifest — spread into `PREFERENCE_FIELD_ORDER`. */
export const GRAPH_ENGINE_FIELD_ORDER: readonly string[] = manifestFieldPaths(GRAPH_ENGINE_MANIFEST);
