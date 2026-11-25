import { describe, expect, it } from 'vitest';
import type { AppApproval, ApprovalItem } from '$lib/api/extensions';
import { approvedOptional, declinable, groups, itemKey, networkName } from './approval-items';

const item = (permission: string, extra: Partial<ApprovalItem> = {}): ApprovalItem => ({
  permission,
  subject: '',
  words: permission,
  required: true,
  why: '',
  approved: true,
  waiting: false,
  understood: true,
  ...extra
});

const app = (items: ApprovalItem[], pending = false): AppApproval => ({
  extension_id: 'x',
  name: 'home',
  approved_for_everything: false,
  pending,
  waits: items.some((i) => i.waiting),
  items,
  claimed: []
});

describe('an app’s Permissions tab', () => {
  it('lists a new version’s extras first, then required and optional, without its address', () => {
    const a = app([
      item('people.see'),
      item('ai.search', { required: false, approved: false, waiting: true }),
      item('ai.use', { required: false }),
      item('site.address', { subject: 'http://home.hiro.local' })
    ]);
    const g = groups(a);
    expect(g.fresh.map((i) => i.permission)).toEqual(['ai.search']);
    expect(g.required.map((i) => i.permission)).toEqual(['people.see']);
    expect(g.optional.map((i) => i.permission)).toEqual(['ai.use']);
  });

  it('shows a new address waiting with the new items, and nothing new for a never-answered app', () => {
    const moved = app([item('site.address', { subject: 'http://house.hiro.local', approved: false, waiting: true })]);
    expect(groups(moved).fresh.map(itemKey)).toEqual(['site.address:http://house.hiro.local']);
    const fresh = app([item('people.see', { approved: false, waiting: true })], true);
    expect(groups(fresh).fresh).toEqual([]);
    expect(groups(fresh).required.map((i) => i.permission)).toEqual(['people.see']);
  });

  it('starts the switches as approved, and offers Decline only when it takes the app away', () => {
    const a = app([item('ai.use', { required: false }), item('ai.search', { required: false, approved: false })]);
    expect(approvedOptional(a)).toEqual(['ai.use']);
    expect(declinable(a)).toBe(false);
    expect(declinable(app([item('people.see', { waiting: true, approved: false })]))).toBe(true);
  });

  it('says the network name it holds', () => {
    expect(networkName(app([item('site.name', { subject: 'home.hiro.local:8100' })]))).toBe('home.hiro.local → port 8100');
    expect(networkName(null)).toBe('');
  });
});
