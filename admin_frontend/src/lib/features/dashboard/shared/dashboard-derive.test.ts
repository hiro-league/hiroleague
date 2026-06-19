import { describe, expect, it } from 'vitest';
import { activeProviderDisplayNames, activeProviderOverflowCount } from './dashboard-derive';

describe('activeProviderDisplayNames', () => {
  it('prefers display_name and caps the list', () => {
    const rows = [
      { provider_id: 'openai', display_name: 'OpenAI' },
      { provider_id: 'anthropic', display_name: null },
      { provider_id: 'google', display_name: 'Google' }
    ];
    expect(activeProviderDisplayNames(rows)).toEqual(['OpenAI', 'anthropic']);
    expect(activeProviderDisplayNames(rows, 1)).toEqual(['OpenAI']);
  });
});

describe('activeProviderOverflowCount', () => {
  it('counts providers beyond the shown limit', () => {
    expect(activeProviderOverflowCount(5)).toBe(3);
    expect(activeProviderOverflowCount(2)).toBe(0);
    expect(activeProviderOverflowCount(1, 3)).toBe(0);
  });
});
