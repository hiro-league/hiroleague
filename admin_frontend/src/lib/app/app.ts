// What makes this app the HiroLeague admin, for the shared UI kit (@hiroleague/ui): the kit's shell, menu and
// helpers are the same in every Hiro app and read the app's own name, pages and keys from this folder
// ($hiro-app). UI kit step 2b.
//   app.ts      - this file: the name, the icon, the words
//   prefs.ts    - the keys the kit keeps in the browser
//   pages.ts    - the pages, the right that opens each, and whether this build has it
//   menu.ts     - the side menu: groups and pages
//   notices.ts  - the live notices the kit's own stream would carry (the admin has its own streams)
//   api.ts      - who is signed in, and signing out, as the kit asks for them
import type { ApiHooks } from '$kit/api/client';
import Logo from './logo.svelte';

export const APP = {
  /** The app's name, as people read it. */
  name: 'HiroLeague',
  /** Its icon: beside the name in the menu. */
  icon: Logo,
  /** What the home page ('/') is called, for the "couldn't open" page's way back. */
  homeTitle: 'Dashboard',
  /** Before every key the kit keeps in the browser ($kit/state/persist). The admin's own keys (lib/preferences)
   * start with the same words. */
  storagePrefix: 'hiro.admin.',
  /** Pages that show alone, with no sign-in and no menu: none (the layout handles /sign-in itself). */
  openRoutes: [] as string[],
  /** The kit's own client is not what the admin's pages call (lib/api/client.ts is); nothing to add. */
  api: {} as ApiHooks,
  signIn: {
    // The admin is where people sign in: the layout gives the shell its sign-in form, so these words (an app's
    // "off to HiroLeague" page) never show here.
    about: '',
    also: '',
    otherWay: 'Signed in'
  }
};
