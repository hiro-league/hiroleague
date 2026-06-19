import { describe, it, expect, beforeEach, vi } from 'vitest';

// Session storage no-ops with browser off, isolating the URL-param logic under test.
vi.mock('$app/environment', () => ({ browser: false }));

// Mutable URL + a goto stub that applies the navigation (mirrors SvelteKit replacing the URL).
const nav = vi.hoisted(() => ({
  url: new URL('http://localhost/eval'),
  goto: vi.fn(async (href: string) => {
    nav.url = new URL(href, 'http://localhost');
  })
}));
vi.mock('$app/navigation', () => ({ goto: (...a: unknown[]) => nav.goto(...(a as [string])) }));
vi.mock('$app/state', () => ({
  get page() {
    return { url: nav.url };
  }
}));

import { createTabPreferences } from './create-tab-preferences.svelte';

beforeEach(() => {
  nav.url = new URL('http://localhost/eval');
  vi.clearAllMocks();
});

describe('createTabPreferences — param defaults to "tab"', () => {
  it('initialize reads ?tab=', () => {
    nav.url = new URL('http://localhost/p?tab=models&extra=keep');
    const prefs = createTabPreferences({
      storageKey: 'k',
      defaultTab: 'overview',
      allowed: ['overview', 'models']
    });
    prefs.initialize();
    expect(prefs.activeTab).toBe('models');
  });

  it('setActiveTab serialises ?tab=', async () => {
    nav.url = new URL('http://localhost/p');
    const prefs = createTabPreferences({
      storageKey: 'k',
      defaultTab: 'a',
      allowed: ['a', 'b']
    });
    await prefs.setActiveTab('b');
    expect(nav.goto).toHaveBeenCalledTimes(1);
    expect(nav.url.searchParams.get('tab')).toBe('b');
  });
});

describe('createTabPreferences — custom param ("sub")', () => {
  it('initialize reads ?sub= and ignores the page-level ?tab=', () => {
    nav.url = new URL('http://localhost/p?tab=knowledge&sub=report');
    const prefs = createTabPreferences({
      storageKey: 'k',
      defaultTab: 'execute',
      allowed: ['execute', 'report'],
      param: 'sub'
    });
    prefs.initialize();
    expect(prefs.activeTab).toBe('report');
  });

  it('setActiveTab writes ?sub= and preserves the page-level ?tab=', async () => {
    nav.url = new URL('http://localhost/p?tab=knowledge');
    const prefs = createTabPreferences({
      storageKey: 'k',
      defaultTab: 'execute',
      allowed: ['execute', 'answers'],
      param: 'sub'
    });
    await prefs.setActiveTab('answers');
    expect(nav.url.searchParams.get('sub')).toBe('answers');
    expect(nav.url.searchParams.get('tab')).toBe('knowledge');
  });

  it('syncActiveTabFromUrl picks up the custom param after navigation', () => {
    const prefs = createTabPreferences({
      storageKey: 'k',
      defaultTab: 'execute',
      allowed: ['execute', 'corpus'],
      param: 'sub'
    });
    prefs.initialize();
    expect(prefs.activeTab).toBe('execute');
    nav.url = new URL('http://localhost/p?sub=corpus');
    prefs.syncActiveTabFromUrl();
    expect(prefs.activeTab).toBe('corpus');
  });
});
