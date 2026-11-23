import { describe, expect, it } from 'vitest';
import {
  draftValue,
  fieldsFromSchema,
  isSecretMarker,
  parseDraftValue,
  secretIsSet,
  type FieldSpec
} from './schema-form';

// WhatsApp-shaped schema (subset) + a secret field to exercise every branch.
const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    owner_number: { anyOf: [{ type: 'string' }, { type: 'null' }], title: 'Owner number', description: 'digits' },
    allowed_senders: { type: 'array', items: { type: 'string' }, title: 'Allowed senders' },
    send_read_receipts: { type: 'boolean', title: 'Read receipts', default: true },
    audio_out: { type: 'boolean', title: 'Voice out', default: true },
    mode: { enum: ['a', 'b'], title: 'Mode' },
    bot_token: { type: 'string', title: 'Bot token', secret: true }
  }
};

const byKey = (fields: FieldSpec[]) => Object.fromEntries(fields.map((f) => [f.key, f]));

describe('fieldsFromSchema', () => {
  it('derives ordered field specs with types, titles, secret + default', () => {
    const fields = fieldsFromSchema(SCHEMA);
    expect(fields.map((f) => f.key)).toEqual([
      'owner_number',
      'allowed_senders',
      'send_read_receipts',
      'audio_out',
      'mode',
      'bot_token'
    ]);
    const f = byKey(fields);
    expect(f.owner_number.type).toBe('string'); // nullable string via anyOf
    expect(f.allowed_senders.type).toBe('array');
    expect(f.send_read_receipts.type).toBe('boolean');
    expect(f.send_read_receipts.default).toBe(true);
    expect(f.mode.type).toBe('enum');
    expect(f.mode.enumValues).toEqual(['a', 'b']);
    expect(f.bot_token.secret).toBe(true);
  });

  it('returns [] for a channel with no schema', () => {
    expect(fieldsFromSchema(null)).toEqual([]);
    expect(fieldsFromSchema({})).toEqual([]);
  });
});

describe('draftValue', () => {
  const f = byKey(fieldsFromSchema(SCHEMA));

  it('falls back to the schema default when the key is absent', () => {
    expect(draftValue(f.send_read_receipts, {})).toBe(true); // default true, not stored
    expect(draftValue(f.audio_out, { audio_out: false })).toBe(false);
  });

  it('renders arrays as a comma list and coerces stored ints to strings', () => {
    expect(draftValue(f.allowed_senders, { allowed_senders: ['1', '2'] })).toBe('1, 2');
    expect(draftValue(f.owner_number, { owner_number: 201223504849 })).toBe('201223504849');
  });

  it('always starts secrets blank', () => {
    expect(draftValue(f.bot_token, { bot_token: { __secret__: true } })).toBe('');
  });
});

describe('secret markers', () => {
  const f = byKey(fieldsFromSchema(SCHEMA));

  it('detects the keyring sentinel', () => {
    expect(isSecretMarker({ __secret__: true })).toBe(true);
    expect(isSecretMarker('plain')).toBe(false);
    expect(secretIsSet(f.bot_token, { bot_token: { __secret__: true } })).toBe(true);
    expect(secretIsSet(f.bot_token, {})).toBe(false);
  });
});

describe('parseDraftValue', () => {
  const f = byKey(fieldsFromSchema(SCHEMA));

  it('splits arrays, coerces bools, and nulls empty strings', () => {
    expect(parseDraftValue(f.allowed_senders, '1, 2  3')).toEqual(['1', '2', '3']);
    expect(parseDraftValue(f.send_read_receipts, false)).toBe(false);
    expect(parseDraftValue(f.owner_number, '')).toBeNull();
    expect(parseDraftValue(f.owner_number, '20122')).toBe('20122');
  });
});
