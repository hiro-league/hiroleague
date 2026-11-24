import { describe, expect, it } from 'vitest';
import { accessFromKeys } from './core-access';

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
