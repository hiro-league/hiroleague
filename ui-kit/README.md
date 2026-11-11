# @hiroleague/ui: the Hiro apps' shared UI kit

The frontend code every Hiro app shares: the Hiro theme (`src/lib/theme.css`), shadcn-svelte's components
(`components/ui`), the app shell (`components/app-shell.svelte`: who is asking, the menu, the page), shared pieces
(`ui/`), loading and saving (`state/`), formatting (`format/`), the one API client (`api/client.ts`) and the live
stream (`live.ts`). It started as HomeHiro's frontend; the palette and colour style are the HiroLeague admin's.

## How an app uses it

- **A copy, kept current:** each app has `scripts/kit-sync.mjs` (`npm run kit`, run by its dev, build, check and
  test). It copies this folder's `src/lib` to the app's `.kit/lib` (not committed). A copy, not a link, so the kit's
  files use the app's own svelte and bits-ui (one of each); a folder of the app's own, not `node_modules`, so the dev
  server watches it and reloads on a change.
- **Read as source:** the app's SvelteKit `alias` maps `$kit` to `.kit/lib`
  (`import Segmented from '$kit/ui/segmented.svelte'`). Inside the kit, files import each other as `$kit/...` too.
- **The app's own facts:** the kit reads them at `$hiro-app`, which the app maps to its `src/lib/app/`:
  `app.ts` (name, icon, words), `prefs.ts`, `pages.ts`, `menu.ts`, `notices.ts`, and `api.ts` (what the kit needs
  of the app's API: who is asking, starting a sign-in, signing out, and the core's AI for apps that use it).
- **Styles:** the app's stylesheet imports Tailwind, `tw-animate-css`, `shadcn-svelte/tailwind.css`, then the kit's
  `theme.css` from `.kit/lib`, and adds `@source` for that folder (Tailwind skips what git ignores unless told).
- **Packages:** the app lists the libraries the kit uses (this folder's `peerDependencies`) in its own `package.json`.
- **Vite settings:** an app's `vite.config.ts` is `defineConfig({ ...hiroVite({ apiEnv, apiDefault }) })`, with
  `hiroVite` imported from `./.kit/lib/vite-preset.js` (Tailwind, SvelteKit with the `$kit` and `$hiro-app` aliases,
  the `/api` dev proxy, the vitest settings). The file only exists after `npm run kit`, so every script that reads
  `vite.config.ts` runs it first.
- **Lint rules:** the house rules are `hiroRules` in `./.kit/lib/eslint-rules.js`; the app's `eslint.config.js` spreads them.
- **Settings page:** `$kit/pages/settings/settings-page.svelte` does the Settings tab handling; the app's
  `routes/settings/+page.svelte` passes `content={{ tabId: snippet }}`.
- **Standard pages:** `$kit/pages/logs`, `users`, `hiroleague`, `ai`; what is the app's own comes from
  `$hiro-app/<page>.ts`. Their backend contract: `mintdocs/build/ui-kit/standard-pages-api.mdx` in hiro-docs.
- **Where the kit is:** `scripts/kit-sync.mjs` takes it from `HIRO_KIT_DIR`, else from the HiroLeague checkout beside the app.

Change shared code here, never in an app's `.kit`. No published release yet: apps take it from the
HiroLeague checkout beside them.

## The kit's own project

This folder is also a small SvelteKit app: the **gallery** (`src/lib/gallery`), every shared piece on one page inside the
shared shell, running against a **sample app** (`src/sample`: what a real app keeps in its `src/lib/app`). A new
app starts with `node scripts/new-app.mjs <folder> <Name> [--port 8050] [--ai] [--icon Shapes]`, which writes the
whole frontend (from `scripts/app-template/` and `src/sample`); then `npm install` and `npm run check` in that
folder, with `HIRO_KIT_DIR` set when it does not sit beside the HiroLeague checkout. The gallery is a kit component (`Gallery`), so the HiroLeague
admin shows it too, at `/ui-kit` (Configuration, UI kit): the kit as that admin has it. Its tabs: **Pieces**, **Theme**
(the Theme designer) and **Standard pages** (`pages/logs`, `users`, `hiroleague`, `ai`: what they are, with the parts that
need no backend).

- **Theme designer:** every token of `theme.css`, light and dark, each with a colour picker and a text box; edits apply live
  to the page, are kept in this browser, and **Copy theme.css** writes only the differences from the kit.
- **A theme per app:** each app has `src/lib/app/theme.css` (empty by default; the sample's is `src/sample/theme.css`).
  Its stylesheet imports it right after the kit's `theme.css` (`@import "../lib/app/theme.css";`), so its tokens win.
  Paste the designer's output there, commit and deploy that app.
- `npm install` once, then `npm run dev` for the gallery and `npm run check` for svelte-check, ESLint and the tests.
- The repo's `./scripts/check.sh` runs `npm run check` here as its "ui-kit: check" part.
- shadcn's components are added here with its CLI (`npx shadcn-svelte@1.7.0 add <name> --yes`; `components.json`
  points it at `$kit`), one at a time; check the diff, since `--overwrite` also overwrites shared components.
