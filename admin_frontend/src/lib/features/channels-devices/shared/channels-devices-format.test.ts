import { describe, expect, it } from 'vitest';
import { displayDeviceName, formatDeviceTimestamp } from './channels-devices-format';

describe('formatDeviceTimestamp', () => {
  it('formats ISO strings with UTC suffix', () => {
    expect(formatDeviceTimestamp('2026-06-19T12:00:00Z')).toBe('2026-06-19 12:00:00 UTC');
  });

  it('returns dash for null', () => {
    expect(formatDeviceTimestamp(null)).toBe('-');
  });
});

describe('displayDeviceName', () => {
  it('prefers device_name when set', () => {
    expect(
      displayDeviceName({
        device_id: 'abc123',
        device_name: 'Phone',
        paired_at: '',
        expires_at: null
      })
    ).toBe('Phone');
  });

  it('truncates long device_id', () => {
    expect(
      displayDeviceName({
        device_id: '0123456789abcdef',
        device_name: null,
        paired_at: '',
        expires_at: null
      })
    ).toBe('0123456789ab...');
  });

  it('keeps short device_id when name is missing', () => {
    expect(
      displayDeviceName({
        device_id: 'short-id',
        device_name: null,
        paired_at: '',
        expires_at: null
      })
    ).toBe('short-id');
  });
});
