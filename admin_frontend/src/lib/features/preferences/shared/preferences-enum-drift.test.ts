import { describe, expect, it } from 'vitest';
import { PREFERENCES_FIELD_SCHEMA } from '$lib/api/preferences-field-schema';
import { MODELS_MANIFEST } from '$lib/features/preferences/sections/models-manifest';
import { AGENT_MANIFEST } from '$lib/features/preferences/sections/agent-manifest';
import { GRAPH_ENGINE_MANIFEST } from '$lib/features/preferences/sections/graph-engine/graph-engine-manifest';
import { KNOWLEDGE_MANIFEST } from '$lib/features/preferences/sections/knowledge/knowledge-manifest';
import { EVAL_MANIFEST } from '$lib/features/preferences/sections/eval/eval-manifest';
import type {
  PrefFieldSpec,
  PrefTabManifest
} from '$lib/features/preferences/widgets/manifest/manifest-types';
import {
  assertPrefSelectOptionsMatchEnum,
  normalizePrefSelectOptions,
  type PrefSelectOption
} from './preferences-field-options';
import { preferenceFieldMeta, type PreferencePath } from './preferences-schema';

// `PrefSelectField` already runs `assertPrefSelectOptionsMatchEnum` at RENDER time, but only for the
// fields on the mounted tab — a stale label map on a tab nobody opened in the test run slips through.
// This walks EVERY manifest's static select specs and validates them against the bundled schema enum,
// so backend enum drift (a renamed/added/removed value) fails CI regardless of which tab is active.
// Computed / cross-field option builders (function-valued `options`) are skipped — they depend on live
// draft state and are covered by the render-time assertion.

const MANIFESTS: Record<string, PrefTabManifest> = {
  models: MODELS_MANIFEST,
  agent: AGENT_MANIFEST,
  'graph-engine': GRAPH_ENGINE_MANIFEST,
  knowledge: KNOWLEDGE_MANIFEST,
  eval: EVAL_MANIFEST
};

// Only the static (non-function) option shapes — function-valued options are filtered out at collect
// time, so the stored type excludes them and `normalizePrefSelectOptions` accepts it directly.
type StaticSelect = { path: PreferencePath; options: PrefSelectOption[] | Record<string, string> };

function collectStaticSelects(spec: PrefFieldSpec, out: StaticSelect[]): void {
  switch (spec.kind) {
    case 'select':
      if (typeof spec.options !== 'function') out.push({ path: spec.path, options: spec.options });
      break;
    case 'grid':
    case 'column':
    case 'panel':
    case 'gated':
      for (const field of spec.fields) collectStaticSelects(field, out);
      break;
  }
}

describe('manifest select options match schema enums', () => {
  for (const [tab, manifest] of Object.entries(MANIFESTS)) {
    const selects: StaticSelect[] = [];
    for (const card of manifest.cards) for (const field of card.body) collectStaticSelects(field, selects);

    for (const { path, options } of selects) {
      it(`${tab}: ${path} labels cover exactly the schema enum`, () => {
        const meta = preferenceFieldMeta(PREFERENCES_FIELD_SCHEMA, path);
        // No-op when the field has no enum (a select over a non-enum path); throws on any drift.
        expect(() =>
          assertPrefSelectOptionsMatchEnum(meta, normalizePrefSelectOptions(options))
        ).not.toThrow();
      });
    }
  }
});
