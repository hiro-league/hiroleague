// Settings → HiroLeague: the app as an extension of the HiroLeague core (each backend's hiroleague.py, hiroleague_api.py;
// the shapes are the ones in an app's generated API file).
import { api } from '$kit/api/client';

export type CoreInfo = { name: string; version: string; workspace?: string; admin_port?: number | null };
export type SiteKind = 'subdomain' | 'local';
export type HiroLeagueStatus = {
	url: string;
	/** no_address | not_paired | connecting | connected | disconnected | stopped */
	status: string;
	error?: string | null;
	core?: CoreInfo | null;
	admin_url_set?: string;
	admin_url?: string;
	site_url_set?: string;
	site_url?: string;
	site_label?: string | null;
	site_kind?: SiteKind | null;
};
export type HiroLeagueTest = { core: CoreInfo; elapsed_ms: number };
export type SiteNameOut = { name: string; url: string; published: boolean; proxied: boolean; note?: string; status: HiroLeagueStatus };

export const getHiroLeague = () => api<HiroLeagueStatus>('hiroleague');
export const setHiroLeagueUrl = (url: string) => api<HiroLeagueStatus>('hiroleague', { method: 'PUT', body: { url } });
export const pairHiroLeague = (code: string) => api<HiroLeagueStatus>('hiroleague/pair', { method: 'POST', body: { code } });
export const forgetHiroLeague = () => api<HiroLeagueStatus>('hiroleague/forget', { method: 'POST' });
export const testHiroLeague = () => api<HiroLeagueTest>('hiroleague/test', { method: 'POST' });
/** Where people open the core's admin (its Edit links), e.g. http://hiro.local; "" derives it. */
export const setHiroLeagueAdminUrl = (url: string) => api<HiroLeagueStatus>('hiroleague/admin-url', { method: 'PUT', body: { url } });
/** The app's own address (its Apps card, where sign-in comes back), a name the core sets up on the LAN:
 * `net` + subdomain → net.hiro.local, `abc` + local → abc.local. Refused (taken, wrong, not connected): nothing changes. */
export const claimSiteName = (label: string, kind: SiteKind) =>
	api<SiteNameOut>('hiroleague/site-name', { method: 'PUT', body: { label, kind } });
