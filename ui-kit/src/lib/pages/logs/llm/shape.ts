// The LLM requests log reads any request the same way, whatever asked it: the answer's shape in words from the
// JSON schema that was sent, and the reply as a value to show (JSON when it parses, else its text).

export type ShapeRow = { path: string; depth: number; allowed: string };

type Schema = {
	type?: string | string[];
	enum?: unknown[];
	properties?: Record<string, Schema>;
	items?: Schema;
	description?: string;
	maxLength?: number;
	minimum?: number;
	maximum?: number;
};

function allowed(s: Schema): string {
	let what: string;
	if (s.enum) what = `one of: ${s.enum.join(', ')}`;
	else if (s.properties) what = 'these parts:';
	else if (s.type === 'array') what = s.items?.properties ? 'a list; each item has:' : `a list of ${s.items ? allowed(s.items) : 'values'}`;
	else if (s.type === 'integer' || s.type === 'number') what = s.minimum !== undefined || s.maximum !== undefined ? `a number ${s.minimum ?? ''}–${s.maximum ?? ''}` : 'a number';
	else if (s.type === 'boolean') what = 'yes or no';
	else what = s.maxLength ? `text, up to ${s.maxLength} characters` : 'text';
	return s.description ? `${what} (${s.description})` : what;
}

/** The answer's shape as rows to read: one per part, nested parts indented. */
export function shape(schema: unknown): ShapeRow[] {
	const rows: ShapeRow[] = [];
	const walk = (s: Schema, depth: number) => {
		const props = s.properties ?? (s.type === 'array' ? s.items?.properties : undefined);
		for (const [name, sub] of Object.entries(props ?? {})) {
			rows.push({ path: name, depth, allowed: allowed(sub) });
			walk(sub, depth + 1);
		}
	};
	walk((schema ?? {}) as Schema, 0);
	return rows;
}

/** The reply as a value when it is JSON (shown as a readable tree), else null (shown as text). */
export function parsed(reply: string): unknown {
	try {
		const v = JSON.parse(reply);
		return v !== null && typeof v === 'object' ? v : null;
	} catch {
		return null;
	}
}

/** The reply laid out for reading: JSON indented, anything else as it came. */
export const pretty = (reply: string) => {
	const v = parsed(reply);
	return v === null ? reply : JSON.stringify(v, null, 2);
};

/** The reply in one line, for the list: "light off · people: TMona · high · lying down". */
export function oneLine(reply: string): string {
	const say = (v: unknown, top = false): string => {
		if (Array.isArray(v)) return v.length ? v.map((x) => say(x)).join(', ') : 'none';
		if (v && typeof v === 'object') {
			const entries = Object.entries(v);
			if (top) return entries.map(([k, x]) => `${k} ${say(x)}`).join(' · ');
			return entries
				.slice(0, 3)
				.map(([, x]) => say(x))
				.join(' · ');
		}
		return String(v);
	};
	const v = parsed(reply);
	return v === null ? reply : say(v, true);
}
