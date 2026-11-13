// The app switcher's list: the apps the person using this app may open. Every Hiro backend answers it at /api/apps:
// the HiroLeague core (its dashboard's Apps card reads the same) and each app on the backend kit (hiro_extension_kit
// hiroleague_api.py, which asks the core: sites.list).
import { api } from './client';

/** One app: the core's Apps card entry. */
export type AppTile = {
	/** Its name in the core ("net"); "hiroleague" for the core itself. */
	extension: string;
	title: string;
	/** A name the kit draws (components/app-icons.ts); "hiroleague" = the core's logo. */
	icon: string;
	url: string;
	/** Connected to HiroLeague right now. */
	online: boolean;
	/** The app this list is shown in. */
	here: boolean;
};

export const listApps = async (): Promise<AppTile[]> => (await api<{ apps: AppTile[] }>('apps')).apps;
