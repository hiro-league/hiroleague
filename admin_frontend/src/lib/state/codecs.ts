/** Total string ↔ T converter — decode never throws; encode returns null to remove the key. */
export interface Codec<T> {
  decode(raw: string | null): T;
  encode(value: T): string | null;
}

/** Per-field schema for a JSON-backed record (`jsonRecordCodec`). */
export type FieldSchema<T> = { [K in keyof T]: JsonFieldCodec<T[K]> };

/** Field codec for native JSON values inside a stored object. */
export type JsonFieldCodec<T> = {
  decode(raw: unknown): T;
  encode(value: T): unknown;
};

export function enumCodec<T extends string>(allowed: readonly T[], def: T): Codec<T> {
  return {
    decode: (raw) =>
      raw != null && (allowed as readonly string[]).includes(raw) ? (raw as T) : def,
    encode: (v) => v
  };
}

export function intCodec(o: { min?: number; max?: number; default: number }): Codec<number> {
  return {
    decode(raw) {
      if (raw == null) return o.default;
      const n = Number.parseInt(raw, 10);
      if (!Number.isFinite(n)) return o.default;
      let v = n;
      if (o.min != null) v = Math.max(o.min, v);
      if (o.max != null) v = Math.min(o.max, v);
      return v;
    },
    encode: (v) => String(v)
  };
}

export function boolCodec(def: boolean, encoding: 'bool' | 'bool01' = 'bool'): Codec<boolean> {
  return {
    decode(raw) {
      if (raw == null) return def;
      if (encoding === 'bool01') {
        if (raw === '1') return true;
        if (raw === '0') return false;
        return def;
      }
      if (raw === 'true') return true;
      if (raw === 'false') return false;
      return def;
    },
    encode(v) {
      if (encoding === 'bool01') return v ? '1' : '0';
      return String(v);
    }
  };
}

export function stringCodec(def = ''): Codec<string> {
  return {
    decode: (raw) => (raw != null ? raw : def),
    encode: (v) => (v === def ? null : v)
  };
}

export function jsonBoolField(def: boolean): JsonFieldCodec<boolean> {
  return {
    decode: (raw) => (typeof raw === 'boolean' ? raw : def),
    encode: (v) => v
  };
}

export function jsonEnumField<T extends string>(
  allowed: readonly T[],
  def: T
): JsonFieldCodec<T> {
  return {
    decode: (raw) =>
      typeof raw === 'string' && (allowed as readonly string[]).includes(raw) ? (raw as T) : def,
    encode: (v) => v
  };
}

export function jsonStringField(def = ''): JsonFieldCodec<string> {
  return {
    decode: (raw) => (typeof raw === 'string' ? raw : def),
    encode: (v) => v
  };
}

export function jsonArrayField<T>(
  filter: (item: unknown) => item is T,
  def: readonly T[]
): JsonFieldCodec<T[]> {
  return {
    decode(raw) {
      if (!Array.isArray(raw)) return [...def];
      return raw.filter(filter);
    },
    encode: (v) => [...v]
  };
}

export function jsonRecordCodec<T extends object>(
  schema: FieldSchema<T>,
  defaults: T
): Codec<T> {
  return {
    decode(raw) {
      if (raw == null) return { ...defaults };
      let parsed: unknown;
      try {
        parsed = JSON.parse(raw);
      } catch {
        return { ...defaults };
      }
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        return { ...defaults };
      }
      const obj = parsed as Record<string, unknown>;
      const out = { ...defaults };
      for (const k in schema) {
        out[k] = schema[k].decode(obj[k]);
      }
      return out;
    },
    encode(value) {
      const obj: Record<string, unknown> = {};
      for (const k in schema) {
        obj[k] = schema[k].encode(value[k]);
      }
      return JSON.stringify(obj);
    }
  };
}

export function keyedMap<V>(value: Codec<V>): Codec<Record<string, V>> {
  return {
    decode(raw) {
      if (raw == null) return {};
      let parsed: unknown;
      try {
        parsed = JSON.parse(raw);
      } catch {
        return {};
      }
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return {};
      const obj = parsed as Record<string, string | null>;
      const out: Record<string, V> = {};
      for (const k of Object.keys(obj)) {
        out[k] = value.decode(obj[k] ?? null);
      }
      return out;
    },
    encode(map) {
      const obj: Record<string, string | null> = {};
      for (const k of Object.keys(map)) {
        obj[k] = value.encode(map[k]);
      }
      return JSON.stringify(obj);
    }
  };
}
