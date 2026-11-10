# App names on the LAN, set up by the core — build contract

Agreed with Michel 2026-11-10. An app (extension) gets its LAN name from its own address setting, with nothing to do
on the server: the core publishes the name and points the web proxy at the app.

## What people see

In the app's address setting (HomeHiro: Settings → HiroLeague → HomeHiro's address; the code reports: HiroLeague
settings → its own address) the person types either:

- a **subdomain**: `reports` → `reports.hiro.local` (the field shows `.hiro.local` after it), or
- a **one-word name**: `abc` → `abc.local`.

Save. If the name is free, the core sets it up at once and the app declares `http://<name>` as its site (the Apps
card and the return after signing in follow). If it's taken or wrong, the setting says why and nothing changes.

## Rules (decided)

- Only `<label>.hiro.local` or `<label>.local`; a label is letters, digits and dashes.
- One name per app: a new claim drops the app's old one (unpublished, proxy entry removed).
- Taken: a name another app holds, or any name in the proxy's hand-written file (hiro.local, homehiro.local,
  mozakra.local, adguard.local…). Hand-written names are never touched.
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
- Proxy: the core writes every claimed name as a Caddy block (`reverse_proxy 127.0.0.1:<port>`, SSE passed through),
  then runs the reload command. At start it publishes and writes every kept claim.

## Simone (aicam)

- `caddy/Caddyfile` ends with `import sites/*.caddy`; compose mounts `./caddy/sites` at `/etc/caddy/sites`;
  `caddy/sites/` is out of git (the core owns it).
- The reload command is `docker exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile`, through
  Caddy's control port on the server only (`admin localhost:2019`): graceful, so the app's own Save, which travels
  through Caddy, gets its answer. A `docker restart caddy` (the first try, 2026-11-10) took 10 s and cut that answer.
- `home.hiro.local`'s hand-made avahi alias and Caddy block go; HomeHiro claims it. `homehiro.local` stays
  hand-written (Home Assistant's add-on reaches HomeHiro through it).
