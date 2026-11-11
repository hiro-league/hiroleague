// What the Logs page makes of the lines: the area a logger belongs to, and repeats shown once.
import { LOGS } from '$hiro-app/logs';
import type { Level, LogLine, Source } from './api';

export const SOURCES: { value: Source | 'all'; label: string }[] = [{ value: 'all', label: 'All sources' }, ...LOGS.sources];

const AREAS = LOGS.areas;

/** The area a logger belongs to, in words; its own name when there is none. */
export function areaOf(logger: string): string {
	return AREAS.find(([p]) => logger === p || logger.startsWith(p + '.'))?.[1] ?? logger;
}

export const isProblem = (l: Level) => l !== 'INFO';
export const isError = (l: Level) => l === 'ERROR' || l === 'CRITICAL';

/** Lines that say the same thing, apart from numbers (ids, counts, seconds): shown once, with how often. */
export type Group = { key: string; line: LogLine; count: number; first: string; last: string; lines: LogLine[] };

export const sameKey = (l: LogLine) => `${l.level}|${l.logger}|${l.message.replace(/\d+(\.\d+)?/g, '#')}`;

/** `lines` newest first: each group's line is its latest. */
export function group(lines: LogLine[]): Group[] {
	const byKey = new Map<string, Group>();
	for (const l of lines) {
		const key = sameKey(l);
		const g = byKey.get(key);
		if (g) {
			g.count++;
			g.first = l.at;
			g.lines.push(l);
		} else byKey.set(key, { key, line: l, count: 1, first: l.at, last: l.at, lines: [l] });
	}
	return [...byKey.values()];
}

/** Each line on its own (repeats not grouped). */
export const single = (lines: LogLine[]): Group[] => lines.map((l) => ({ key: l.id, line: l, count: 1, first: l.at, last: l.at, lines: [l] }));
