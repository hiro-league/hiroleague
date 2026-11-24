import { describe, expect, it } from 'vitest';
import { accessFromKeys, tabsFor } from './core-access';

describe('accessFromKeys', () => {
  it('gives see for a see key and use for any other action', () => {
    const a = accessFromKeys(['logs.see', 'ai.profiles.see', 'ai.profiles.change']);
    expect(a.logs).toBe('see');
    expect(a['ai.profiles']).toBe('use');
    expect(a['ai.providers']).toBe('no');
  });

  it("keeps a nested feature apart from its area's own: logs.see opens neither runs nor usage", () => {
    const a = accessFromKeys(['logs.see']);
    expect(a['logs.runs']).toBe('no');
    expect(a['logs.usage']).toBe('no');
  });

  it('opens nothing with a grant for their own things', () => {
    const a = accessFromKeys(['conversations.see:own', 'memories.see:own', 'memories.change:own']);
    expect(a.conversations).toBe('no');
    expect(a.memories).toBe('no');
  });

  it('counts an action of a feature that has no see', () => {
    expect(accessFromKeys(['ai.images.run'])['ai.images']).toBe('use');
  });
});

describe('tabsFor', () => {
  const tabs = [{ id: 'logs' }, { id: 'runs' }, { id: 'usage' }];
  const featureOf = (id: string) => (id === 'runs' ? 'logs.runs' : id === 'usage' ? 'logs.usage' : 'logs');

  it('keeps the tabs whose feature the person has', () => {
    expect(tabsFor(tabs, featureOf, accessFromKeys(['logs.see'])).map((t) => t.id)).toEqual(['logs']);
  });

  it('keeps every tab when none is open (the page itself is refused)', () => {
    expect(tabsFor(tabs, featureOf, {}).map((t) => t.id)).toEqual(['logs', 'runs', 'usage']);
  });
});
