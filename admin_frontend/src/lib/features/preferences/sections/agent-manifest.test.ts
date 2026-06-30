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
import { AGENT_MANIFEST } from './agent-manifest';

const paths = manifestFieldPaths(AGENT_MANIFEST);

// Editable agent-tab schema fields the UI intentionally does not render (kept here so a genuinely
// missing field still fails the completeness check below).
const UNEXPOSED = ['memory.default_tuning_profile', 'chat.preferred_answering_language'];

describe('agent manifest', () => {
  it('covers exactly the editable agent-tab paths (manifest + intentionally-unexposed)', () => {
    const tabPaths = new Set(
      Object.values(PREFERENCES_FIELD_SCHEMA)
        .filter((m) => !m.readOnly && !m.preferencesSaveSkip)
        .map((m) => m.path)
        .filter((p) => tabForPreferencePath(p) === 'agent')
    );
    expect(new Set([...paths, ...UNEXPOSED])).toEqual(tabPaths);
  });

  it('every manifest path is a real, unique, editable field on the agent tab', () => {
    expect(new Set(paths).size).toBe(paths.length);
    for (const p of paths) {
      const meta = PREFERENCES_FIELD_SCHEMA[p];
      expect(meta, p).toBeTruthy();
      expect(Boolean(meta.readOnly || meta.preferencesSaveSkip), p).toBe(false);
      expect(tabForPreferencePath(p), p).toBe('agent');
    }
  });

  it('UNEXPOSED entries are real agent-tab fields genuinely absent from the manifest', () => {
    for (const p of UNEXPOSED) {
      expect(PREFERENCES_FIELD_SCHEMA[p], p).toBeTruthy();
      expect(tabForPreferencePath(p), p).toBe('agent');
      expect(paths.includes(p), p).toBe(false);
    }
  });

  it('manifest section labels match the search-index sectioning rules', () => {
    const sections = manifestSections(AGENT_MANIFEST);
    for (const p of paths) {
      expect(sectionForPreferencePath(p), p).toBe(sections[p]);
    }
  });
});
