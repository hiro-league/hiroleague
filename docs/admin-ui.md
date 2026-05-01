# Hiro Admin UI

The admin UI is a SvelteKit static app served by the `hirocli` admin FastAPI process.

## Source And Package Output

- Frontend source: `admin_frontend/`
- Packaged static output: `hiroserver/hirocli/src/hirocli/admin_svelte/static/`
- Python API routes: `hiroserver/hirocli/src/hirocli/admin_svelte/api.py`
- Static mount helper: `hiroserver/hirocli/src/hirocli/admin_svelte/static_server.py`

## Development

Start the Hiro admin server:

```sh
hiro start --admin
```

Start the Svelte dev server:

```sh
npm --prefix admin_frontend install
npm --prefix admin_frontend run dev
```

Open:

```text
http://127.0.0.1:5173/
```

During development, Vite proxies `/api/*` to the running Hiro admin server. The default target is `http://127.0.0.1:18083`. Override it with `HIRO_ADMIN_ORIGIN` when needed.

## Packaging

Build the static app into the Python package:

```sh
npm --prefix admin_frontend run package:python
```

The `hirocli` wheel includes:

```text
src/hirocli/admin_svelte/static/**
```

## Runtime Routes

When Hiro is started with admin enabled:

```text
http://127.0.0.1:<admin_port>/
```

The browser app calls:

```text
/api/config
/api/events/status
/api/workspaces
/api/gateways
/api/catalog/providers
/api/catalog/models
/api/providers
/api/characters
/api/channels
/api/devices
/api/chat-channels
/api/logs/layout
/api/logs/tail
/api/logs/search
/api/metrics/tick
/api/metrics/configure
```
