/**
 * Declarative manifest for the General (models) tab (manifest rollout). Replaces `ModelsSection`'s
 * two cards: Default models (the workspace model picks + default tuning profile, with inline
 * embedder/reranker downloads) and Modalities (input/output toggle panels). The tab's field order
 * derives from this manifest (`MODELS_FIELD_ORDER`).
 */
import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
import {
  manifestFieldPaths,
  type PrefTabManifest
} from '$lib/features/preferences/widgets/manifest/manifest-types';

export const MODELS_MANIFEST: PrefTabManifest = {
  cards: [
    {
      kind: 'card',
      id: 'modelsDefault',
      title: 'Default models',
      description: 'Fallback models used when a character has no available preferred model.',
      bodyId: PREFERENCES_SECTION_BODY_IDS.modelsChat,
      collapsible: true,
      // Each picker is its own titled cell so the 2-column grid packs (no half-empty rows).
      body: [
        {
          kind: 'grid',
          fields: [
            { kind: 'model', modelKind: 'chat', path: 'llm.default_chat', labelled: true },
            { kind: 'model', modelKind: 'stt', path: 'llm.default_stt', labelled: true },
            { kind: 'tuningProfile', path: 'llm.default_tuning_profile', scope: 'llm' },
            { kind: 'model', modelKind: 'tts', path: 'llm.default_tts', labelled: true },
            {
              kind: 'model',
              modelKind: 'embedding',
              path: 'llm.default_embedder',
              labelled: true,
              download: 'embedder'
            },
            {
              kind: 'model',
              modelKind: 'rerank',
              path: 'llm.default_reranker',
              labelled: true,
              download: 'reranker'
            }
          ]
        },
        // Workspace-wide provider connection keepalive (seconds). Its own row below the model
        // pickers — it's a shared HTTP-connection setting, not a per-model choice. Bounds/step come
        // from the schema (5–1800, step 5); takes effect on server restart.
        { kind: 'grid', fields: [{ kind: 'number', path: 'llm.http_keepalive_s' }] }
      ]
    },
    {
      kind: 'card',
      id: 'modelsModalities',
      title: 'Modalities',
      descriptionOf: (ctrl) => ctrl.sectionDescription('media'),
      bodyId: PREFERENCES_SECTION_BODY_IDS.mediaInput,
      collapsible: true,
      body: [
        {
          kind: 'panel',
          title: 'Input Modalities',
          fields: [
            {
              kind: 'grid',
              fields: [
                { kind: 'toggle', path: 'media.input.voice' },
                { kind: 'toggle', path: 'media.input.image' },
                { kind: 'toggle', path: 'media.input.video' },
                { kind: 'toggle', path: 'media.input.file' }
              ]
            }
          ]
        },
        {
          kind: 'panel',
          title: 'Output Modalities',
          fields: [
            {
              kind: 'grid',
              fields: [
                { kind: 'toggle', path: 'media.output.voice' },
                { kind: 'toggle', path: 'media.output.image' },
                { kind: 'toggle', path: 'media.output.video' },
                { kind: 'toggle', path: 'media.output.file' }
              ]
            }
          ]
        }
      ]
    }
  ]
};

/** General-tab field order, derived from the manifest — spread into `PREFERENCE_FIELD_ORDER`. */
export const MODELS_FIELD_ORDER: readonly string[] = manifestFieldPaths(MODELS_MANIFEST);
