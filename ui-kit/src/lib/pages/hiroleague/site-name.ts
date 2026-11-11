// The app's address as a LAN name the HiroLeague core sets up (Settings → HiroLeague → the app's address; backend
// domain/site_name.py has the same rules): a subdomain of hiro.local or a one-word .local name.
import { APP } from '$hiro-app/app';
import { HIROLEAGUE } from '$hiro-app/hiroleague';
import type { SiteKind, SiteNameOut } from './api';

export const SUFFIX: Record<SiteKind, string> = { subdomain: '.hiro.local', local: '.local' };

export const KIND_OPTIONS = [
	{ value: 'subdomain', label: 'Subdomain of hiro.local', title: `${HIROLEAGUE.siteLabel} → ${HIROLEAGUE.siteLabel}.hiro.local` },
	{ value: 'local', label: 'One-word .local name', title: 'abc → abc.local' }
] as const satisfies readonly { value: SiteKind; label: string; title: string }[];

/** The label to show as an example: `net` for a subdomain, `nethiro` for a one-word name. */
export const examplePlaceholder = (kind: SiteKind) => (kind === 'subdomain' ? HIROLEAGUE.siteLabel : APP.name.toLowerCase());

/** The address a label and kind make, as the backend will save it (trimmed, lower case; the suffix pasted too is
 * dropped), or '' while there is no label. */
export function addressFor(label: string, kind: SiteKind): string {
	let clean = label.trim().toLowerCase();
	if (clean.endsWith(SUFFIX[kind])) clean = clean.slice(0, -SUFFIX[kind].length);
	return clean ? `http://${clean}${SUFFIX[kind]}` : '';
}

/** What the core said about the name, in a line: fine when it is published on the LAN and its proxy points here. */
export function claimSaid(r: SiteNameOut): { text: string; ok: boolean } {
	const ok = r.published && r.proxied;
	if (ok) return { text: `${APP.name} is now at ${r.url}: HiroLeague published the name and points it here.`, ok };
	const missing = [!r.published && 'not published on the network', !r.proxied && `not proxied to ${APP.name}`]
		.filter(Boolean)
		.join(' and ');
	return { text: `${APP.name} is now at ${r.url}, but the name is ${missing} yet.${r.note ? ` ${r.note}` : ''}`, ok };
}
