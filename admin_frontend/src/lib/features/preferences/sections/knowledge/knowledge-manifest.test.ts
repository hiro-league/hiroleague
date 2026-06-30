import { describe, expect, it } from 'vitest';
import { PREFERENCES_FIELD_SCHEMA } from '$lib/api/preferences-field-schema';
import {
  sectionForPreferencePath,
  tabForPreferencePath
} from '$lib/features/preferences/shared/preferences-tabs';
import {
  manifestFieldPaths,
  manifestSections
} from '$lib/features/preferences/widgets/manifest/manifest-types';
import { KNOWLEDGE_MANIFEST } from './knowledge-manifest';

const paths = manifestFieldPaths(KNOWLEDGE_MANIFEST);

// Editable knowledge-tab fields the UI intentionally does not render.
const UNEXPOSED = [
  'knowledge.retrieval.reranker.device',
  'knowledge.retrieval.reranker.batch_size'
];

describe('knowledge manifest', () => {
  it('covers exactly the editable knowledge-tab paths (manifest + intentionally-unexposed)', () => {
    const tabPaths = new Set(
      Object.values(PREFERENCES_FIELD_SCHEMA)
        .filter((m) => !m.readOnly && !m.preferencesSaveSkip)
        .map((m) => m.path)
        .filter((p) => tabForPreferencePath(p) === 'knowledge')
    );
    expect(new Set([...paths, ...UNEXPOSED])).toEqual(tabPaths);
  });

  it('every manifest path is a real, unique, editable field on the knowledge tab', () => {
    expect(new Set(paths).size).toBe(paths.length);
    for (const p of paths) {
      const meta = PREFERENCES_FIELD_SCHEMA[p];
      expect(meta, p).toBeTruthy();
      expect(Boolean(meta.readOnly || meta.preferencesSaveSkip), p).toBe(false);
      expect(tabForPreferencePath(p), p).toBe('knowledge');
    }
  });

  it('UNEXPOSED entries are real knowledge-tab fields genuinely absent from the manifest', () => {
    for (const p of UNEXPOSED) {
      expect(PREFERENCES_FIELD_SCHEMA[p], p).toBeTruthy();
      expect(tabForPreferencePath(p), p).toBe('knowledge');
      expect(paths.includes(p), p).toBe(false);
    }
  });

  it('manifest section labels match the search-index sectioning rules', () => {
    const sections = manifestSections(KNOWLEDGE_MANIFEST);
    for (const p of paths) {
      expect(sectionForPreferencePath(p), p).toBe(sections[p]);
    }
  });
});
