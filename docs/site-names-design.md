# Names on the LAN and the front door, served by the core — build contract

Every name a machine serves on the LAN comes from the core: it announces each name, and its front door (Caddy, a
service of its own) sends each name to the app or site behind it. Apps listen on 127.0.0.1 only, so the front door is
the one way in. The design behind it: the Claude Doc "Design: the front door and installing apps", section 8.

## What people see

In an app's address setting (HomeHiro: Settings → HiroLeague → HomeHiro's address; CodeHiro: HiroLeague settings →
its own address) the person types either:

- a **subdomain** of the core's domain: `reports` → `reports.hiro.local` (the field shows `.hiro.local` after it), or
- a **one-word name**: `abc` → `abc.local`.

Save. If the name is free, the core serves it at once and the app declares `http://<name>` as its site (the Apps card
and the return after signing in follow). If it's taken or wrong, the setting says why and nothing changes.

The owner adds the rest with `hiro sites`:

- `hiro sites add homehiro.local --app home`: an **extra name** beside an app's own, sent to the same port;
- `hiro sites add adguard.local --target 3001`: an **other site**, a name sent to a port on this machine;
- `hiro sites add 192.168.1.10 --target 8100 --path /tv --path /_app/*`: the **machine's address**, for devices that
  can't look a name up (a Chromecast), limited to some paths (the rest answers 404);
- `hiro sites add frigate.local`: a name **only announced**, for a program that listens on the LAN itself;
- `hiro sites list`, `hiro sites remove <name>`.

A name nobody serves gets a page saying no app answers to it, with a link to the core's admin (`http://<domain>`).

## The core's name

- The core has one name, `core_name` in its `config.json` (`hiro` by default): one word of letters, digits and
  dashes. Its **domain** is `<core_name>.local` (`hiro.local`); its admin is served there, its gateway's default name
  is `gate.<domain>`, and an app's subdomain is `<label>.<domain>`.
- It is picked when a workspace is set up: `hiro workspaces setup --name testpc`, or setup's question for a new
  workspace; `hiro service install --name testpc` gives it to the service (`HIRO_CORE_NAME`), whose first start makes
  its workspace with it. A workspace keeps the name it was set up with: setup refuses another one in words, a
  service given another one keeps the workspace's own and says so at start, and a `config.json` without the key
  (Simone's) is `hiro`.
- Nothing renames a core yet: no command, no admin setting, no old names kept served.
- `welcome`'s `core` block carries `domain`, so an app can claim under it. Today's backend kit still claims
  `<app>.hiro.local` (the SDK's `SITES_DOMAIN`): on a core named otherwise that claim is refused as `invalid`, and
  the app's own address setting takes a one-word `<label>.local` name. Its sign-in, with the core on the same
  machine, also goes to `http://hiro.local` until its admin address is set to `http://<domain>`.

## Rules (decided)

- An app's name is `<label>.<domain>` (`<label>.hiro.local`) or `<label>.local`; a label is letters, digits and
  dashes. An other site is such a name or the machine's IPv4 address.
- A name belongs to one of an app, the core or an other site, never two: each table's key is the name, and adding
  refuses a taken one.
- One main name per app: a new claim drops the app's old main one; its extra names stay and follow its new port.
- An app's main name is the app's: only extra names and other sites are the owner's to remove. Removing an app gives
  back all its names at once when the core runs, else at its next start.
- The core serves its own two names from its config: its domain (`hiro.local`: its admin, `admin_port`) and the
  gateway's at `gateway_port` while the core runs the gateway itself (`gateway_builtin`). The gateway's name is the
  host of `gateway_url` when that is a name the core serves (`ws://gate.hiro.local` → `gate.hiro.local`), else its
  default `gate.<domain>` (`gateway_url` is `localhost` or an address). Taken: those two (the gateway's even when it
  runs elsewhere). A name an app claimed before the core took its own stays the app's.
- No approval step for an app's claim: pairing the app with HiroLeague is the owner's approval.

## Contract (hiro_channel_sdk.constants)

`sites.claim` extension → core, `{name, port}` → `{name, url, published, proxied, note}`; errors `invalid`, `taken`.
`port` is where the app listens on the core's machine (127.0.0.1:<port>). `published`: the name is announced;
`proxied`: the front door took it; `note` says why not.

## Core

- **Tables** (workspace.db): `site_names (name PK, extension_id, port, claimed_at, extra)`, an app's main name and
  the owner's extra ones; `other_sites (name PK, target, paths, added_at)`, `target` empty for a name only announced,
  `paths` a JSON list.
- **Announcing** (`runtime/name_publisher.py`), on a machine set up for it (`hiro extension names --ip <LAN address>`;
  empty = nothing announced, claims kept): Linux runs one `avahi-publish -a -R <name> <ip>` per name, restarted when
  it ends (no sudo); Windows and Mac announce from inside the core with python-zeroconf, on that address only. The
  machine's address is never announced.
- **The front door** (`runtime/front_door.py`, `domain/front_door.py`): the core loads Caddy's **whole
  configuration** through its admin API (`POST /load`, a Caddyfile) at start and on every change: no file written, no
  reload command. Every load carries the same admin block (a load without one moves Caddy's API to its default
  `localhost:2019`), `auto_https off`, one block per proxied name (live updates, SSE, passed through) and the page for
  any other name. A configuration Caddy refuses leaves it serving what it had; the core says why once and tries again
  every 30 s until Caddy takes one (the cut-over on Simone relies on it).
- **Which core drives it:** only a core whose service was given the front door's address (`HIRO_FRONT_DOOR`, set by
  `hiro service install` for the machine's default service). A dev core, an environment's core and a named
  workspace's service never touch any Caddy.
- **When:** at start, on a claim, on `extension.removed` and on `sites.changed` (`hiro sites`, which goes through the
  running core when there is one).

## Setting up the front door (`hiro service install`)

Made once, in the core's own setup step an admin approves, never by the core (`front_door_setup.py`). Caddy is the
release pinned in `caddy_release.py` (fetched, its SHA-256 checked), kept in the Hiro home's `caddy/<version>/`, and
started with `caddy run --resume --config initial.json`: the admin API alone until the core's first load, then its own
autosave (`XDG_CONFIG_HOME`), so it serves its last configuration with or without the core.

| System | Account | Admin API | Port 80 | Firewall |
|---|---|---|---|---|
| Linux | `hiro-caddy` (`hiro-caddy.service`) | `/run/hiro-caddy/admin.sock`, mode 0660; the core's account joins the `hiro-caddy` group | `CAP_NET_BIND_SERVICE` in Caddy's unit only | none added |
| Windows | `NT SERVICE\hiro-caddy`, under WinSW | `127.0.0.1:18079` (Caddy takes no socket on Windows); Caddy checks the Host of every call | needs no right | TCP 80 for caddy.exe, UDP 5353 for the core's Python |
| Mac (untried) | the core's account (`com.hiroleague.caddy`) | an owner-only socket in the Hiro home | needs no root since Mojave | none added |

`hiro service uninstall` of the default service removes Caddy's service, its account (Linux) and the firewall rules;
its folder stays.

## Simone

The front door moves from aicam to the core in one cut-over, after the deploy that brings this code: `sudo hiro
service install` sets up `hiro-caddy` beside aicam's Caddy, whose port 80 refuses the core's loads until aicam's Caddy
stops; then the core's Caddy takes port 80 within 30 s. aicam's fixed names become the owner's: `homehiro.local` (the
Home Assistant add-on), `mozakra.local` and `reports.local` extra names, `adguard.local` and the TV page by the
server's address other sites, `frigate.local` a name only announced. Going back: stop `hiro-caddy`, start aicam's.
