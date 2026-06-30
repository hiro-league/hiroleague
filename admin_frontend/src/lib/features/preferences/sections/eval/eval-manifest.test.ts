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
import { EVAL_MANIFEST } from './eval-manifest';

// Guards the two ways the manifest could silently drift from the schema/search index (see the
// graph-engine manifest test for the rationale).
const paths = manifestFieldPaths(EVAL_MANIFEST);

describe('eval manifest', () => {
  it('covers exactly the editable eval-tab schema paths (no missing, no extra)', () => {
    const tabPaths = new Set(
      Object.values(PREFERENCES_FIELD_SCHEMA)
        .filter((m) => !m.readOnly && !m.preferencesSaveSkip)
        .map((m) => m.path)
        .filter((p) => tabForPreferencePath(p) === 'eval')
    );
    expect(new Set(paths)).toEqual(tabPaths);
  });

  it('every manifest path is a real, unique, editable field on the eval tab', () => {
    expect(new Set(paths).size).toBe(paths.length);
    for (const p of paths) {
      const meta = PREFERENCES_FIELD_SCHEMA[p];
      expect(meta, p).toBeTruthy();
      expect(Boolean(meta.readOnly || meta.preferencesSaveSkip), p).toBe(false);
      expect(tabForPreferencePath(p), p).toBe('eval');
    }
  });

  it('manifest section labels match the search-index sectioning rules', () => {
    const sections = manifestSections(EVAL_MANIFEST);
    for (const p of paths) {
      expect(sectionForPreferencePath(p), p).toBe(sections[p]);
    }
  });
});
