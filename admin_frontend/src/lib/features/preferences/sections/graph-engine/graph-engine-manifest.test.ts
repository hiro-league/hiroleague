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
import { GRAPH_ENGINE_MANIFEST } from './graph-engine-manifest';

// The manifest is the single source for what the Memory tab renders AND its search order, so these
// guard the two ways it could silently drift: a schema field added/removed without the manifest, or
// a manifest entry that points at the wrong tab / a stale section title.
const paths = manifestFieldPaths(GRAPH_ENGINE_MANIFEST);

describe('graph-engine manifest', () => {
  it('covers exactly the editable graph-engine-tab schema paths (no missing, no extra)', () => {
    const tabPaths = new Set(
      Object.values(PREFERENCES_FIELD_SCHEMA)
        .filter((m) => !m.readOnly && !m.preferencesSaveSkip)
        .map((m) => m.path)
        .filter((p) => tabForPreferencePath(p) === 'graph-engine')
    );
    expect(new Set(paths)).toEqual(tabPaths);
  });

  it('every manifest path is a real, unique, editable field on the graph-engine tab', () => {
    expect(new Set(paths).size).toBe(paths.length);
    for (const p of paths) {
      const meta = PREFERENCES_FIELD_SCHEMA[p];
      expect(meta, p).toBeTruthy();
      expect(Boolean(meta.readOnly || meta.preferencesSaveSkip), p).toBe(false);
      expect(tabForPreferencePath(p), p).toBe('graph-engine');
    }
  });

  it('manifest section labels match the search-index sectioning rules', () => {
    const sections = manifestSections(GRAPH_ENGINE_MANIFEST);
    for (const p of paths) {
      expect(sectionForPreferencePath(p), p).toBe(sections[p]);
    }
  });
});
