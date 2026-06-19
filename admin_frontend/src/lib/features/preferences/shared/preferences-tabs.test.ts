import { afterEach, describe, expect, it, vi } from 'vitest';
import { migrateLegacyPreferenceHash } from './preferences-tabs';

describe('migrateLegacyPreferenceHash', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function stubLocation(href: string, hash: string) {
    const replaceState = vi.fn();
    vi.stubGlobal('window', {
      location: { href, hash },
      history: { replaceState }
    });
    return replaceState;
  }

  it('no-ops when hash is empty', () => {
    const replaceState = stubLocation('http://localhost/preferences', '');
    migrateLegacyPreferenceHash();
    expect(replaceState).not.toHaveBeenCalled();
  });

  it('no-ops for unknown legacy anchors', () => {
    const replaceState = stubLocation('http://localhost/preferences#unknown-anchor', '#unknown-anchor');
    migrateLegacyPreferenceHash();
    expect(replaceState).not.toHaveBeenCalled();
  });

  it('migrates a non-default tab hash to ?tab=', () => {
    const replaceState = stubLocation(
      'http://localhost/preferences#preferences-knowledge',
      '#preferences-knowledge'
    );
    migrateLegacyPreferenceHash();
    expect(replaceState).toHaveBeenCalledWith(null, '', '/preferences?tab=knowledge');
  });

  it('migrates the default models hash to a clean URL', () => {
    const replaceState = stubLocation(
      'http://localhost/preferences#preferences-models',
      '#preferences-models'
    );
    migrateLegacyPreferenceHash();
    expect(replaceState).toHaveBeenCalledWith(null, '', '/preferences');
  });

  it('maps the merged memory anchor to the agent tab', () => {
    const replaceState = stubLocation(
      'http://localhost/preferences#preferences-memory',
      '#preferences-memory'
    );
    migrateLegacyPreferenceHash();
    expect(replaceState).toHaveBeenCalledWith(null, '', '/preferences?tab=agent');
  });
});
