// The app's address as a LAN name the HiroLeague core sets up (Settings → HiroLeague → the app's address; backend
// site_name.py has the same rules): a subdomain of the core's own name (hiro.local, or <name>.local when the house
// named its core: the status's `domain`) or a one-word .local name.
import { APP } from '$hiro-app/app';
import { HIROLEAGUE } from '$hiro-app/hiroleague';
import type { SiteKind, SiteNameOut } from './api';

/** The core's name before it says (a core from before it named itself). */
export const DEFAULT_DOMAIN = 'hiro.local';

/** What a kind of name ends with: `.<the core's domain>` or `.local`. */
export const suffixFor = (kind: SiteKind, domain: string = DEFAULT_DOMAIN) => (kind === 'subdomain' ? `.${domain}` : '.local');

/** The two kinds, as the form offers them under the core's domain. */
export const kindOptions = (domain: string = DEFAULT_DOMAIN) =>
	[
		{ value: 'subdomain', label: `Subdomain of ${domain}`, title: `${HIROLEAGUE.siteLabel} → ${HIROLEAGUE.siteLabel}.${domain}` },
		{ value: 'local', label: 'One-word .local name', title: 'abc → abc.local' }
	] as const satisfies readonly { value: SiteKind; label: string; title: string }[];

/** The label to show as an example: `net` for a subdomain, `nethiro` for a one-word name. */
export const examplePlaceholder = (kind: SiteKind) => (kind === 'subdomain' ? HIROLEAGUE.siteLabel : APP.name.toLowerCase());

/** The address a label and kind make, as the backend will save it (trimmed, lower case; the suffix pasted too is
 * dropped), or '' while there is no label. */
export function addressFor(label: string, kind: SiteKind, domain: string = DEFAULT_DOMAIN): string {
	const suffix = suffixFor(kind, domain);
	let clean = label.trim().toLowerCase();
	if (clean.endsWith(suffix)) clean = clean.slice(0, -suffix.length);
	return clean ? `http://${clean}${suffix}` : '';
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
