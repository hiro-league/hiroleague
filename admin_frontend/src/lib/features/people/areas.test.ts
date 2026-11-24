import { describe, expect, it } from 'vitest';
import type { AccessFeature } from '$lib/api/people';
import { groupByArea } from './areas';

const f = (id: string, name = id): AccessFeature => ({ id, name, rights: [], not_for_owner: false });

describe('groupByArea', () => {
  it("puts an area's own feature and its nested ones under the area's name", () => {
    const groups = groupByArea([f('logs', 'Logs'), f('logs.runs'), f('logs.usage'), f('server', 'Server')], { logs: 'Logs' });
    expect(groups.map((g) => [g.area, g.name, g.features.map((x) => x.id)])).toEqual([
      ['logs', 'Logs', ['logs', 'logs.runs', 'logs.usage']],
      [null, 'Server', ['server']]
    ]);
  });

  it('leaves an app with no areas one feature per group', () => {
    expect(groupByArea([f('streams'), f('people')], {}).map((g) => g.area)).toEqual([null, null]);
  });
});
