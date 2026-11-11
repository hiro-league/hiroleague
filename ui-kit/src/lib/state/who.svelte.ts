// Who is using the app (backend /api/me, auth/api.py): asked once when the app starts, again after
// signing out, and while someone waits for a role. The layout shows the "taking you to HiroLeague" page, the "no access"
// page or the app from `state`. An app-wide singleton: every page reads the same answer.
// Phase 8 (one sign-in): signing in happens at HiroLeague. An app sends the browser there and gets it back signed
// in; the HiroLeague core itself shows its sign-in form (the shell's `signedOut` view).
// UI kit, step 2: how to ask who is there, start a sign-in and sign out are the app's ($hiro-app/api), so the
// same state serves an app and the core.
import { ApiError, errorMessage } from '$kit/api/client';
import { getMe, signOut, startSignIn, type Me } from '$hiro-app/api';

export type WhoState =
	| 'loading' // not asked yet
	| 'signin' // nobody known: off to HiroLeague's sign-in page
	| 'blocked' // known, but waiting for a role (or a link on People) or given No access
	| 'ok' // known, with a role
	| 'error'; // the backend couldn't say (down, restarting): show the app, whose pages say so too

class Who {
	me = $state<Me | null>(null);
	state = $state<WhoState>('loading');
	error = $state('');
	/** Signed out here just now: stay on the app's page, or HiroLeague (still signed in) would send them straight back. */
	signedOut = $state(false);

	load = async () => {
		try {
			const me = await getMe();
			this.me = me;
			this.state = me.state === 'ok' ? 'ok' : 'blocked';
			this.error = '';
		} catch (e) {
			if (e instanceof ApiError && e.status === 401) {
				this.me = null;
				this.state = 'signin';
			} else if (this.state === 'loading') {
				this.state = 'error'; // a later failed check keeps what was known
				this.error = errorMessage(e);
			}
		}
	};

	/** Start a sign-in, to come back to this page afterwards (an app: off to HiroLeague's sign-in page). */
	signIn = () => {
		const url = new URL(location.href);
		url.searchParams.delete('signin_error');
		startSignIn(url.pathname + url.search);
	};

	/** Signs out of the app and HiroLeague both (Phase 8): the app's sign-out names where the browser goes next
	 * (HiroLeague's sign-out, which ends that session too). With nowhere to go, only this app's session ends. */
	signOut = async () => {
		const { then } = await signOut();
		if (then) {
			location.assign(then);
			return;
		}
		this.me = null;
		this.signedOut = true;
		this.state = 'signin';
	};
}

export const who = new Who();
