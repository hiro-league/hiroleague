// Which environment a page is served from, told by its address alone, for the badge beside the app's name
// (env-badge.svelte). The ports are the standard's (workflow.md, "Ports"): environment N owns 7N00 to 7N49, env0
// included; live, Caddy serves each app by its LAN name on port 80. Anything else (a preview, a test server on
// another port) gets no badge.

export type Environment = { kind: 'live' } | { kind: 'dev'; n: number };

const LOCAL = new Set(['localhost', '127.0.0.1', '[::1]']);

/** The environment of a page at `hostname` and `port` (location.port: '' on the scheme's own port). */
export function environmentOf(hostname: string, port: string): Environment | null {
	if (port === '') return LOCAL.has(hostname) ? null : { kind: 'live' };
	const p = Number(port);
	if (!Number.isInteger(p) || p < 7000 || p > 7999 || p % 100 >= 50) return null;
	return { kind: 'dev', n: Math.floor(p / 100) - 70 };
}
