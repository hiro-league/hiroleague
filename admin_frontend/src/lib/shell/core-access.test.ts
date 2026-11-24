import { describe, expect, it } from 'vitest';
import { tabsFor } from './core-access';

describe('tabsFor', () => {
  const tabs = [{ id: 'logs' }, { id: 'runs' }, { id: 'usage' }];
  const featureOf = (id: string) => (id === 'runs' ? 'logs.runs' : id === 'usage' ? 'logs.usage' : 'logs');

  it('keeps the tabs whose feature the person has', () => {
    expect(tabsFor(tabs, featureOf, { logs: 'see', 'logs.runs': 'no' }).map((t) => t.id)).toEqual(['logs']);
  });

  it('keeps every tab when none is open (the page itself is refused)', () => {
    expect(tabsFor(tabs, featureOf, {}).map((t) => t.id)).toEqual(['logs', 'runs', 'usage']);
  });
});
