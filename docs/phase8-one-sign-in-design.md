# Phase 8: one sign-in — build contract

The plan doc's Phase 8 ("HiroLeague and Home: the plan in steps"). One sign-in for HiroLeague and each
extension's own site; HiroLeague's dashboard opens them. **No pass-through**: each app keeps its own address
and its own pages.

We're in initial development mode (no backward compatibility, no wrappers). The one exception is family
data: HomeHiro's users' My room picks are carried over (step 3).

## Decisions (agreed 2026-11-10)

| Topic | Choice |
| --- | --- |
| Addresses | HiroLeague `hiro.local`; Home `home.hiro.local` if that name resolves on the family's phones and PCs (tested first), else `homehiro.local` stays. `homehiro.local` then sends you on |
| One sign-in | An extension's site sends a signed-out visitor to HiroLeague's sign-in page; HiroLeague sends them back with a one-time code; the extension asks the core whose code it is, then keeps its own sign-in |
| Sign-in page | HiroLeague's name + password always work. "Sign in with Home Assistant" shows only when a connected extension offers it; the extension checks the HA login and answers which person it is. The core knows nothing about HA |
| HA app | HomeHiro's entry in the Home Assistant app works as today (HA's add-on headers + PROXY_SECRET) |
| HiroLeague's settings | One switch per role, "can open HiroLeague's settings": Owner on (always), Adult and Kid off by default. Anyone else signed in sees only the dashboard's Apps card |
| Apps card | Each extension declares its site (title, icon, address, roles that see it) in `offers.shows`; HiroLeague's dashboard shows them, each opening in a new tab |
| Sessions | 90 days, HiroLeague and HomeHiro |
| Signing out of both | **Open** — proposed: signing out anywhere signs that browser out of both |
| Later | Sign in with Google, passkeys; rights per function (Phase 10) |

## The flows

### A. Signing in to an extension (one-time code)

```
browser ─GET home.hiro.local/anything──▶ HomeHiro: no session
   ◀── 303 http://hiro.local/sign-in?for=home&next=<path> ──
browser ─GET hiro.local/sign-in?for=home&next=…──▶ core
   signed in already? ──no──▶ sign-in page (password, or the HA button) ──▶ signed in
   ◀── 303 <home's address>/api/auth/hiro?code=<one-time>&next=<path> ──
browser ─GET home.hiro.local/api/auth/hiro?code=…──▶ HomeHiro
   HomeHiro ─ext request auth.code {code}──▶ core ──▶ {person_id, name, role_id}
   HomeHiro starts its own 90-day session (cookie homehiro_session), ──303──▶ <path>
```

- The code: 32 random bytes, one use, 60 seconds, bound to the extension that asked (`for=`). Only that
  extension's paired connection can redeem it. The core keeps only its hash, in memory.
- `next` must be a path on the extension's own declared address; anything else becomes `/`.
- `for=` names the extension (its pairing name). An unknown or offline extension: the sign-in page says so.
- The core's own cookie becomes `SameSite=Lax` (was Strict), so it's sent when another site sends the
  browser to `hiro.local` (a top-level GET). Still HttpOnly; `/api` writes stay POST/PUT/DELETE.

### B. "Sign in with Home Assistant" on the core's sign-in page

```
sign-in page shows the button when a connected extension offers sign_in "home_assistant"
browser ─GET hiro.local/api/auth/with/home_assistant?next=…──▶ core
   core ─ext request sign_in.start {client_id: http://hiro.local/, redirect_uri: …/api/auth/with/callback, state}──▶ HomeHiro
        ◀── {url: HA's authorize URL} (HomeHiro knows HA's address)
   ◀── 303 HA's login page
HA ──303 hiro.local/api/auth/with/callback?code&state──▶ core
   core ─ext request sign_in.finish {code, client_id}──▶ HomeHiro
        HomeHiro trades the code with HA (client_id = the core's address), finds the HA user's
        person through its links ◀── {person_id} or a reason ("Michel's HA user isn't linked to a person")
   core starts its session ──303──▶ next (or back into flow A)
```

- HomeHiro already has every piece (ha/login.py, People's links). It moves from its own routes into two
  extension request handlers. It hands HA's refresh token back at once, as today.
- The core stores nothing about HA: no address, no token, no HA user ids.

### C. Inside the HA app (unchanged)

HA's add-on adds the HA user + PROXY_SECRET; HomeHiro finds the person through its links. A user whose HA
person isn't linked to a core person waits, as today.

## Core (HiroLeague)

- **Roles:** `roles.admin INTEGER NOT NULL DEFAULT 0`; Owner is always 1 (not switchable). The People page
  gets a Roles card: each role, its people count, and the switch "Can open HiroLeague's settings".
  `roles.*` extension requests carry `admin` read-only (extensions can't grant it).
- **Middleware:** `RequireSignIn` also checks the role. A person whose role is off may call only
  `/api/auth/*` and `/api/apps`; anything else answers 403 "Your role doesn't open HiroLeague's settings".
  The admin shell shows them a short dashboard: their name, the Apps card, Sign out.
- **Sign-in for extensions:** `GET /sign-in` (the SPA's sign-in page reads `for` and `next`),
  `GET /api/auth/for/{extension}?next=` (signed in → 303 with a code; else 401 for the page to show the form),
  extension request `auth.code` (EXTENSIONS_ONLY).
- **Offered sign-ins:** `offers.can_do` entry `{"kind": "sign_in", "id": "home_assistant", "label": "Home Assistant"}`;
  extension requests `sign_in.start` / `sign_in.finish` (core → extension). `/api/auth/me` lists the offered
  sign-ins of connected extensions, for the page's buttons.
- **Apps card:** `offers.shows` entry `{"kind": "site", "title": "Home", "icon": "house", "url": "http://home.hiro.local", "roles": []}`
  (`roles: []` = every role). `GET /api/apps` lists the ones the caller's role sees, with online/offline.
- **Sessions:** `SESSION_DAYS = 90`; cookie `SameSite=Lax`.
- **Sign-out of both (if agreed):** `GET /sign-out?next=` ends the core session; an extension's Sign out goes
  through it.

## HomeHiro

- **Signed out → the core:** `/api/me` without a session answers 401 with `signin_url`
  (`<core admin address>/sign-in?for=<pairing name>&next=<path>`); the app goes there instead of showing
  its own sign-in page. `GET /api/auth/hiro?code&next` redeems the code (`auth.code`) and starts the session.
- **Its own HA sign-in goes:** `/api/auth/login`, `/api/auth/callback` and `components/sign-in.svelte`.
  ha/login.py stays, used by the `sign_in.start` / `sign_in.finish` handlers.
- **Users are core people:** `AppUser.id` becomes the core person id (was the HA user id). A migration
  re-keys existing rows through People's links, keeping My room picks, `denied` and seen-times; rows with no
  linked person are dropped (they could only wait). `ha_group`, `ha_owner` and the "Owner while not linked"
  fallback go: the role is the core person's. `WebSession.user_id` follows.
- **The HA app path** maps the HA user to the person through the links (`family.py`), then the same user row.
- **Declares** its site in `offers.shows` (address from a new Settings → HiroLeague field "HomeHiro's
  address", default `http://homehiro.local`) and its HA sign-in in `offers.can_do`.
- **Sessions:** stays 90 days.

## aicam (after the address test)

- avahi alias `home.hiro.local`; Caddy `http://home.hiro.local` → 127.0.0.1:8100 (as homehiro.local now);
  `http://homehiro.local` → `redir http://home.hiro.local{uri}`. The HA add-on keeps going to Caddy.
- Caddy's TV entry (192.168.1.10) is unchanged.

## Work

1. Mock-ups as real pages (flag `PHASE8_MOCKUP`): the core's sign-in page with the HA button and "Home asked
   you to sign in", the Apps card, the Roles card with the switch, the dashboard a Kid sees; HomeHiro's
   "Taking you to HiroLeague…". The `home.hiro.local` test on the family's devices.
2. Core: roles.admin + middleware, the code flow, offered sign-ins, Apps card, 90-day Lax sessions.
3. HomeHiro: signed-out → core, code redemption, HA sign-in as extension handlers, AppUser re-keyed
   (migration keeps My room picks), declares its site and sign-in.
4. aicam: home.hiro.local, the redirect.
5. Try it on the PC, then Simone.
