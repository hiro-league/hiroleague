import { describe, expect, it } from 'vitest';
import { scopeMsgIdAfterHydrate } from './logs-page-lifecycle';

describe('scopeMsgIdAfterHydrate', () => {
  it('keeps session scope when URL msg_id is absent or blank', () => {
    expect(scopeMsgIdAfterHydrate('session-msg', null)).toBe('session-msg');
    expect(scopeMsgIdAfterHydrate('session-msg', '')).toBe('session-msg');
    expect(scopeMsgIdAfterHydrate('session-msg', '   ')).toBe('session-msg');
  });

  it('overrides session scope when URL msg_id is non-empty', () => {
    expect(scopeMsgIdAfterHydrate('session-msg', 'url-msg')).toBe('url-msg');
    expect(scopeMsgIdAfterHydrate('session-msg', '  url-msg  ')).toBe('url-msg');
  });

  it('returns URL msg_id when session is empty', () => {
    expect(scopeMsgIdAfterHydrate('', 'url-msg')).toBe('url-msg');
  });
});
