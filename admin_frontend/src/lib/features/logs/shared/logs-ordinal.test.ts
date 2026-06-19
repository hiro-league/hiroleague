import { describe, expect, it } from 'vitest';
import type { LogRow } from '$lib/api/logs';
import {
  computeScopeMsgChipStripeByRowKey,
  createScopeMsgOrdinalState,
  getScopeMsgOrdinal,
  resetScopeMsgOrdinalState,
  syncScopeMsgOrdinalsFromRows,
  type ScopeMsgOrdinalState
} from './logs-ordinal';
import type { RenderLogRow } from './logs-ui';

function renderRow(
  p: Partial<LogRow> & { _rowKey: string; timestamp: number; scope_msg_id?: string }
): RenderLogRow {
  return {
    id: p._rowKey,
    timestamp_display: '',
    date_display: '',
    source: 'server',
    level: 'INFO',
    level_html: '',
    module: '',
    module_html: '',
    message: '',
    message_html: '',
    message_pretty: null,
    extra: '',
    extra_html: '',
    extra_tooltip_html: '',
    extra_segments: [],
    is_startup: false,
    ...p
  };
}

describe('syncScopeMsgOrdinalsFromRows', () => {
  it('assigns stable ordinals in chronological order of first sighting', () => {
    const state = createScopeMsgOrdinalState();
    const rows = [
      renderRow({ _rowKey: 'b:1', timestamp: 200, scope_msg_id: 'msg-b' }),
      renderRow({ _rowKey: 'a:0', timestamp: 100, scope_msg_id: 'msg-a' }),
      renderRow({ _rowKey: 'c:2', timestamp: 300, scope_msg_id: 'msg-b' })
    ];
    expect(syncScopeMsgOrdinalsFromRows(state, rows)).toBe(true);
    expect(getScopeMsgOrdinal(state, 'msg-a')).toBe(1);
    expect(getScopeMsgOrdinal(state, 'msg-b')).toBe(2);
    expect(syncScopeMsgOrdinalsFromRows(state, rows)).toBe(false);
  });

  it('skips rows without scope_msg_id', () => {
    const state = createScopeMsgOrdinalState();
    syncScopeMsgOrdinalsFromRows(state, [
      renderRow({ _rowKey: 'x:0', timestamp: 1 }),
      renderRow({ _rowKey: 'y:1', timestamp: 2, scope_msg_id: '  ' })
    ]);
    expect(state.ordinalMap.size).toBe(0);
  });
});

describe('computeScopeMsgChipStripeByRowKey', () => {
  it('alternates stripe when message ordinal changes between consecutive scoped rows', () => {
    const state: ScopeMsgOrdinalState = {
      ordinalMap: new Map([
        ['m1', 1],
        ['m2', 2],
        ['m3', 3]
      ]),
      nextSeq: 4
    };
    const visible = [
      renderRow({ _rowKey: 'r1', timestamp: 1, scope_msg_id: 'm1' }),
      renderRow({ _rowKey: 'r2', timestamp: 2, scope_msg_id: 'm1' }),
      renderRow({ _rowKey: 'r3', timestamp: 3, scope_msg_id: 'm2' }),
      renderRow({ _rowKey: 'r4', timestamp: 4, scope_msg_id: 'm3' })
    ];
    const stripes = computeScopeMsgChipStripeByRowKey(state, visible);
    expect(stripes.get('r1')).toBe(false);
    expect(stripes.get('r2')).toBe(false);
    expect(stripes.get('r3')).toBe(true);
    expect(stripes.get('r4')).toBe(false);
  });

  it('skips unscoped rows without flipping the stripe', () => {
    const state: ScopeMsgOrdinalState = {
      ordinalMap: new Map([
        ['m1', 1],
        ['m2', 2]
      ]),
      nextSeq: 3
    };
    const visible = [
      renderRow({ _rowKey: 'r1', timestamp: 1, scope_msg_id: 'm1' }),
      renderRow({ _rowKey: 'gap', timestamp: 2 }),
      renderRow({ _rowKey: 'r2', timestamp: 3, scope_msg_id: 'm2' })
    ];
    const stripes = computeScopeMsgChipStripeByRowKey(state, visible);
    expect(stripes.has('gap')).toBe(false);
    expect(stripes.get('r2')).toBe(true);
  });
});

describe('resetScopeMsgOrdinalState', () => {
  it('clears ordinals and resets the sequence counter', () => {
    const state = createScopeMsgOrdinalState();
    syncScopeMsgOrdinalsFromRows(state, [
      renderRow({ _rowKey: 'a:0', timestamp: 1, scope_msg_id: 'x' })
    ]);
    resetScopeMsgOrdinalState(state);
    expect(state.ordinalMap.size).toBe(0);
    expect(state.nextSeq).toBe(1);
    expect(getScopeMsgOrdinal(state, 'x')).toBeNull();
  });
});
