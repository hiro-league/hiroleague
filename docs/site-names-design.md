# App names on the LAN, set up by the core — build contract

Agreed with Michel 2026-11-10. An app (extension) gets its LAN name from its own address setting, with nothing to do
on the server: the core publishes the name and points the web proxy at the app.

## What people see

In the app's address setting (HomeHiro: Settings → HiroLeague → HomeHiro's address; CodeHiro: HiroLeague
settings → its own address) the person types either:

- a **subdomain**: `reports` → `reports.hiro.local` (the field shows `.hiro.local` after it), or
- a **one-word name**: `abc` → `abc.local`.

Save. If the name is free, the core sets it up at once and the app declares `http://<name>` as its site (the Apps
card and the return after signing in follow). If it's taken or wrong, the setting says why and nothing changes.

## Rules (decided)

- Only `<label>.hiro.local` or `<label>.local`; a label is letters, digits and dashes.
- One name per app: a new claim drops the app's old one (unpublished, proxy entry removed).
- Removing an app gives its name back: it is unpublished and its proxy entry goes at once when the core runs, else at
  its next start.
- The core claims its own two names the same way, from its config: `hiro.local` (its admin, `admin_port`) and the
  gateway's (the host of `gateway_url`, e.g. `gate.hiro.local`, at `gateway_port`) while the core runs the gateway
  itself (`gateway_builtin`).
- Taken: a name another app holds, the core's own two (the gateway's even when it runs elsewhere), or any name in
  the proxy's hand-written file (homehiro.local, mozakra.local, adguard.local…). Hand-written names are never touched.
- A name is never in both files: Caddy refuses a name defined twice and then serves none. So the core leaves one of
  its own names to the hand-written file while that file still has it, and takes it at its next write once the block
  is gone; a name an app claimed before the core took its own stays the app's.
- No approval step: pairing the app with HiroLeague is the owner's approval.
- Windows asks AdGuard for names with a dot before `.local`: its `*.hiro.local` rewrite covers them (set once).

## Contract (hiro_channel_sdk.constants)

`sites.claim` extension → core, `{name, port}` → `{name, url, published, proxied, note}`; errors `invalid`, `taken`.
`port` is where the app listens on the core's machine (127.0.0.1:<port>).

## Core

- Claims kept in workspace.db `site_names (name PK, extension_id, port, claimed_at)`.
- Machine setup in the workspace config (`hiro extension names …`): `site_names_ip` (the LAN address names point at;
  empty = names aren't set up on this machine, claims are only kept), `site_names_caddy_file` (the file the core
  writes, imported by Caddy), `site_names_caddy_main` (the hand-written Caddyfile, read for taken names),
  `site_names_caddy_reload` (the command that makes Caddy read it again).
- Publishing: one `avahi-publish -a -R <name> <ip>` per name, run and restarted by the core (no sudo needed).
- Proxy: the core writes every claimed name and its own as a Caddy block (`reverse_proxy 127.0.0.1:<port>`, SSE passed
  through), then runs the reload command. At start it publishes and writes every kept claim and its own names, and
  again whenever an app claims a name or is removed (`extension.removed` on the bus), reading the hand-written file
  each time.

## Simone (aicam)

- `caddy/Caddyfile` ends with `import sites/*.caddy`; compose mounts `./caddy/sites` at `/etc/caddy/sites`;
  `caddy/sites/` is out of git (the core owns it).
- The reload command is `docker exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile`, through
  Caddy's control port on the server only (`admin localhost:2019`): graceful, so the app's own Save, which travels
  through Caddy, gets its answer. A `docker restart caddy` (the first try, 2026-11-10) took 10 s and cut that answer.
- `home.hiro.local` is HomeHiro's claim. `homehiro.local` stays hand-written (Home Assistant's add-on reaches HomeHiro
  through it).
- `hiro.local` and `gate.hiro.local` are the core's once their blocks leave aicam's Caddyfile and the
  `avahi-alias-hiro` unit stops (an avahi name published twice collides); until then the hand-written blocks serve
  them.
