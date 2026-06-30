/**
 * Declarative manifest for the Knowledge tab (manifest rollout). Replaces the three hand-written
 * cards: Indexing Options (embedder + chunking + graph backend), Retrieval defaults (hybrid/score
 * knobs + the gated reranker), and Knowledge Answering (rewrite + model/profile + answer behavior).
 * The tab's field order derives from this manifest (`KNOWLEDGE_FIELD_ORDER`).
 *
 * `knowledge.retrieval.reranker.device` and `.batch_size` are editable knowledge-tab fields the UI
 * intentionally doesn't surface (see the manifest test's UNEXPOSED set).
 */
import {
  GRAPH_BACKEND_LABELS,
  KNOWLEDGE_LANGUAGE_POLICY_LABELS
} from '$lib/features/preferences/shared/preferences-enum-labels';
import {
  knowledgeAnsweringModelHint,
  knowledgeHybridPrefetchActive
} from '$lib/features/preferences/shared/preferences-helpers';
import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
import type { WorkspacePreferences } from '$lib/api/preferences';
import {
  manifestFieldPaths,
  type PrefTabManifest
} from '$lib/features/preferences/widgets/manifest/manifest-types';

const rerankerOff = (d: WorkspacePreferences) => !d.knowledge.retrieval.reranker.enabled;

export const KNOWLEDGE_MANIFEST: PrefTabManifest = {
  cards: [
    {
      kind: 'card',
      id: 'knowledgeIndexing',
      title: 'Indexing Options',
      description:
        'Everything applied when documents are indexed — the knowledge embedder (empty inherits the workspace default), document chunking, and the knowledge graph backend.',
      bodyId: PREFERENCES_SECTION_BODY_IDS.knowledgeEmbedding,
      collapsible: true,
      body: [
        {
          kind: 'grid',
          fields: [{ kind: 'custom', component: 'knowledgeEmbedder', paths: ['knowledge.default_embedding_model'] }]
        },
        {
          kind: 'grid',
          fields: [
            { kind: 'number', path: 'knowledge.chunking.chunk_size' },
            { kind: 'number', path: 'knowledge.chunking.chunk_overlap' },
            { kind: 'toggle', path: 'knowledge.chunking.markdown.respect_headings' },
            { kind: 'toggle', path: 'knowledge.chunking.embed_structural_context' },
            {
              kind: 'select',
              path: 'graph.backend',
              options: GRAPH_BACKEND_LABELS,
              hintSuffix:
                'The graph engine itself — extraction/small models, embedder, search recipe, and reranker — is shared with Agent Memory and configured in the Graph Engine tab.'
            }
          ]
        }
      ]
    },
    {
      kind: 'card',
      id: 'knowledgeRetrieval',
      title: 'Retrieval defaults',
      bodyId: PREFERENCES_SECTION_BODY_IDS.knowledgeRetrieval,
      collapsible: true,
      body: [
        {
          kind: 'grid',
          fields: [
            {
              kind: 'toggle',
              path: 'knowledge.retrieval.hybrid',
              hint: 'Runs BM25 keyword search alongside dense embeddings and fuses them with Reciprocal Rank Fusion — recovers exact terms, proper nouns, and Arabic surface forms. Sparse model: Qdrant/bm25 (local, no extra setup).'
            },
            { kind: 'number', path: 'knowledge.retrieval.min_score' }
          ]
        },
        {
          kind: 'grid',
          fields: [
            {
              kind: 'gated',
              disabledWhen: (d) => !knowledgeHybridPrefetchActive(d),
              fields: [{ kind: 'number', path: 'knowledge.retrieval.prefetch_limit' }]
            },
            { kind: 'number', path: 'knowledge.retrieval.top_k' }
          ]
        },
        {
          kind: 'panel',
          title: 'Reranker',
          hint: 'Optional cross-encoder that reorders retrieved candidates by relevance before answering (precision step). Cloud models need a provider key; local models must be downloaded first. Switching is a hot swap — no re-ingest.',
          fields: [
            {
              kind: 'toggle',
              path: 'knowledge.retrieval.reranker.enabled',
              hint: 'Cloud scores are calibrated [0,1]; local cross-encoder scores are sigmoid-normalized. A normalized relevance is emitted whether reranking is on (reranker score) or off (retrieval rank), so downstream ranking stays consistent.'
            },
            {
              kind: 'gated',
              disabledWhen: rerankerOff,
              fields: [
                {
                  kind: 'model',
                  modelKind: 'rerank',
                  path: 'knowledge.retrieval.reranker.model_id',
                  emptyFallback: 'llm.default_reranker',
                  download: 'reranker'
                }
              ]
            },
            {
              kind: 'gated',
              disabledWhen: rerankerOff,
              fields: [{ kind: 'number', path: 'knowledge.retrieval.reranker.top_n' }]
            }
          ]
        }
      ]
    },
    {
      kind: 'card',
      id: 'knowledgeAnswering',
      title: 'Knowledge Answering (Ask Tab)',
      descriptionOf: (ctrl) => (ctrl.draft ? knowledgeAnsweringModelHint(ctrl.draft) : ''),
      bodyId: PREFERENCES_SECTION_BODY_IDS.knowledgeAnsweringModel,
      collapsible: true,
      body: [
        {
          kind: 'grid',
          fields: [
            {
              kind: 'toggle',
              path: 'knowledge.rewrite.default_on',
              hint: 'Optional LLM step that rewrites a question before retrieval — normalizes wording and extracts literal keywords. Reuses the answering model; toggled per query on the Ask tab.'
            },
            {
              kind: 'prompt',
              path: 'knowledge.rewrite.prompt',
              hint: 'Sent as the system prompt for the rewrite call. Keep the instruction to copy proper nouns and identifiers verbatim so the BM25 keyword branch keeps its exact-match signal.',
              ariaLabel: 'Knowledge query rewrite prompt (markdown)',
              editorLabel: 'Rewrite prompt editor'
            }
          ]
        },
        {
          kind: 'grid',
          fields: [
            {
              kind: 'modelProfile',
              modelKind: 'chat',
              modelPath: 'knowledge.answering.model',
              profilePath: 'knowledge.default_tuning_profile',
              scope: 'knowledge',
              heading: 'Knowledge Answering Model'
            },
            {
              kind: 'column',
              fields: [
                {
                  kind: 'prompt',
                  path: 'knowledge.answering.prompt',
                  hint: 'Base system prompt for answer generation. The relaxed default allows partial answers and avoids a bare "I don\'t know" when the context covers part of the question; use "Restore default" in the editor to bring it back. The citation and language settings below are appended automatically.',
                  ariaLabel: 'Knowledge answering prompt (markdown)',
                  editorLabel: 'Answering prompt editor'
                },
                {
                  kind: 'select',
                  path: 'knowledge.answering.language_policy',
                  options: KNOWLEDGE_LANGUAGE_POLICY_LABELS
                },
                { kind: 'toggle', path: 'knowledge.answering.cite_sources' }
              ]
            }
          ]
        }
      ]
    }
  ]
};

/** Knowledge-tab field order, derived from the manifest — spread into `PREFERENCE_FIELD_ORDER`. */
export const KNOWLEDGE_FIELD_ORDER: readonly string[] = manifestFieldPaths(KNOWLEDGE_MANIFEST);
