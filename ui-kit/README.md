# @hiroleague/ui: the Hiro apps' shared UI kit

The frontend code every Hiro app shares: the Hiro theme (`src/lib/theme.css`), shadcn-svelte's components
(`components/ui`), the app shell (`components/app-shell.svelte`: who is asking, the menu, the page), shared pieces
(`ui/`), loading and saving (`state/`), formatting (`format/`), the one API client (`api/client.ts`) and the live
stream (`live.ts`). It started as HomeHiro's frontend; the palette and colour style are the HiroLeague admin's.

## How an app uses it

- **Install:** `"@hiroleague/ui": "file:../../hiroleague/ui-kit"` with `install-links=true` in the app's `.npmrc`,
  so npm copies it into `node_modules` and it uses the app's own svelte and bits-ui (one copy of each).
- **Read as source:** the app's SvelteKit `alias` maps `$kit` to `node_modules/@hiroleague/ui/src/lib`
  (`import Segmented from '$kit/ui/segmented.svelte'`). Inside the kit, files import each other as `$kit/...` too.
- **The app's own facts:** the kit reads them at `$hiro-app`, which the app maps to its `src/lib/app/`:
  `app.ts` (name, icon, words), `prefs.ts`, `pages.ts`, `menu.ts`, `notices.ts`, and `api.ts` (what the kit needs
  of the app's API: `getMe`, `Me`, `Access`, and the core's AI for apps that use it).
- **Styles:** the app's stylesheet imports Tailwind, `tw-animate-css`, `shadcn-svelte/tailwind.css`, then the kit's
  `theme.css`, and adds `@source` for the kit's folder (Tailwind skips `node_modules` unless told).
- **Staying current:** npm does not copy a same-version local package again, so each app has
  `scripts/kit-sync.mjs` (`npm run kit`), run by its dev, build, check and test.

Change shared code here, never in an app's `node_modules`. No published release yet: apps take it from the
HiroLeague checkout beside them.

## The kit's own project

This folder is also a small SvelteKit app: the **gallery** (`src/routes`), every shared piece on one page inside the
shared shell, running against a **sample app** (`src/sample`: what a real app keeps in its `src/lib/app`). A new
app starts by copying `src/sample` and changing its words.

- `npm install` once, then `npm run dev` for the gallery and `npm run check` for svelte-check, ESLint and the tests.
- The repo's `./scripts/check.sh` runs `npm run check` here as its "ui-kit: check" part.
- shadcn's components are added here with its CLI (`npx shadcn-svelte@1.7.0 add <name> --yes`; `components.json`
  points it at `$kit`), one at a time; check the diff, since `--overwrite` also overwrites shared components.
