/**
 * Turn a channel's declared JSON Schema (§5.1) into a flat list of form fields the
 * generic Settings form renders — no per-channel UI code. Secret fields (§5.6) are
 * flagged so the form masks them and the controller routes their values to the
 * keyring instead of the config blob.
 *
 * Pure helpers only (unit-tested); no Svelte, no side effects.
 */

export type FieldType = 'string' | 'integer' | 'number' | 'boolean' | 'array' | 'enum';

export type FieldSpec = {
  key: string;
  type: FieldType;
  title: string;
  description: string;
  secret: boolean;
  /** Schema default, applied when the stored config omits the key. */
  default?: unknown;
  /** For type 'enum': the allowed string values. */
  enumValues?: string[];
};

type JsonSchema = Record<string, unknown>;

function asRecord(value: unknown): JsonSchema | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonSchema) : null;
}

/**
 * The single scalar JSON-Schema type of a property spec, mirroring the backend's
 * `_target_scalar_type`: honors `type`, a nullable `type` array, and pydantic's
 * `anyOf` rendering of `X | None`.
 */
function scalarType(spec: JsonSchema): string | null {
  const t = spec.type;
  if (typeof t === 'string') return t;
  if (Array.isArray(t)) {
    const nonNull = t.filter((x) => x !== 'null');
    return nonNull.length === 1 ? String(nonNull[0]) : null;
  }
  for (const key of ['anyOf', 'oneOf'] as const) {
    const branches = spec[key];
    if (Array.isArray(branches)) {
      const types = branches
        .map((b) => asRecord(b)?.type)
        .filter((x): x is string => typeof x === 'string' && x !== 'null');
      if (types.length === 1) return types[0];
    }
  }
  return null;
}

function enumValues(spec: JsonSchema): string[] | null {
  if (Array.isArray(spec.enum)) return spec.enum.map(String);
  for (const key of ['anyOf', 'oneOf'] as const) {
    const branches = spec[key];
    if (Array.isArray(branches)) {
      for (const b of branches) {
        const rec = asRecord(b);
        if (rec && Array.isArray(rec.enum)) return rec.enum.map(String);
      }
    }
  }
  return null;
}

function fieldType(spec: JsonSchema): FieldType {
  const en = enumValues(spec);
  if (en) return 'enum';
  const t = scalarType(spec);
  if (t === 'boolean') return 'boolean';
  if (t === 'integer') return 'integer';
  if (t === 'number') return 'number';
  if (t === 'array') return 'array';
  return 'string';
}

/** Ordered field specs derived from a channel config schema (empty if none). */
export function fieldsFromSchema(schema: unknown): FieldSpec[] {
  const props = asRecord(asRecord(schema)?.properties);
  if (!props) return [];
  const fields: FieldSpec[] = [];
  for (const [key, rawSpec] of Object.entries(props)) {
    const spec = asRecord(rawSpec);
    if (!spec) continue;
    const type = fieldType(spec);
    fields.push({
      key,
      type,
      title: typeof spec.title === 'string' ? spec.title : key,
      description: typeof spec.description === 'string' ? spec.description : '',
      secret: spec.secret === true,
      default: 'default' in spec ? spec.default : undefined,
      enumValues: type === 'enum' ? (enumValues(spec) ?? []) : undefined
    });
  }
  return fields;
}

const SECRET_MARKER_KEY = '__secret__';

/** True if a stored config value is the §5.6 keyring sentinel (secret is set). */
export function isSecretMarker(value: unknown): boolean {
  return (
    !!value && typeof value === 'object' && (value as Record<string, unknown>)[SECRET_MARKER_KEY] === true
  );
}

/**
 * Draft form value for one field, seeded from the stored config and falling back to
 * the schema default when the key is absent. Arrays render as a comma/space list;
 * secrets always start blank (the value is never sent to the UI).
 */
export function draftValue(field: FieldSpec, config: Record<string, unknown>): string | boolean {
  if (field.secret) return '';
  const raw = field.key in config ? config[field.key] : field.default;
  if (field.type === 'boolean') return Boolean(raw);
  if (field.type === 'array') return Array.isArray(raw) ? raw.map(String).join(', ') : '';
  return raw == null ? '' : String(raw);
}

/** Whether a secret field currently has a value stored (shows "set" in the UI). */
export function secretIsSet(field: FieldSpec, config: Record<string, unknown>): boolean {
  return field.secret && isSecretMarker(config[field.key]);
}

/** Parse a draft value back to the JSON shape the config API expects. */
export function parseDraftValue(field: FieldSpec, value: string | boolean): unknown {
  if (field.type === 'boolean') return Boolean(value);
  if (field.type === 'array') {
    return String(value)
      .split(/[,\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
  }
  if (field.type === 'integer' || field.type === 'number') {
    const s = String(value).trim();
    if (s === '') return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : s;
  }
  const s = String(value).trim();
  return s === '' ? null : s;
}
