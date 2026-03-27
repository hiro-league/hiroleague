---
name: HiroAdmin v2 Rebuild
overview: Build HiroAdmin v2 under hirocli/admin/ following hiroadmin_guidelines.md. V2 shares one NiceGUI app with legacy on admin_port; routes live under /v2/. Phases add features until parity, then legacy ui/ is removed.
todos:
  - id: p0-skeleton
    content: "Phase 0: Create hirocli/admin/ package skeleton with all __init__.py files"
    status: completed
  - id: p0-context
    content: "Phase 0: Create admin/context.py — frozen AdminContext dataclass + get_selected_workspace() helper"
    status: completed
  - id: p0-result
    content: "Phase 0: Create shared/result.py — Result[T] generic type with ok/fail"
    status: completed
  - id: p0-theme
    content: "Phase 0: Create shared/theme.py — apply_theme() calling app.colors() with brand palette"
    status: completed
  - id: p0-primitives
    content: "Phase 0: Create shared/ui/ primitives (stat_card, confirm_dialog, form_dialog, status_badge, data_table, empty_state, error_banner, loading_state)"
    status: completed
  - id: p0-shell
    content: "Phase 0: Create shell/navigation.py + shell/layout.py + router.py (APIRouter /v2) + workspace_service; mount v2 from ui/run.py"
    status: completed
  - id: p0-run
    content: "Phase 0: admin/run.py — build_admin_context, register_v2_routes, include_router on core.app (no second Uvicorn)"
    status: completed
  - id: p0-verify
    content: "Phase 0: Verify legacy / and v2 /v2/ on same admin_port; guidelines gate"
    status: completed
  - id: p1-dashboard
    content: "Phase 1: Dashboard feature — service, components, page on v2_router, tests; guidelines gate"
    status: completed
  - id: p2-workspaces
    content: "Phase 2: Workspaces feature — service, components, page, tests; guidelines gate"
    status: completed
  - id: p3-channels
    content: "Phase 3: Channels feature — service, components, page; guidelines gate"
    status: completed
  - id: p3-devices
    content: "Phase 3: Devices feature — service, components, page; guidelines gate"
    status: completed
  - id: p3-tests
    content: "Phase 3: Tests for channel and device services; guidelines gate"
    status: completed
  - id: p4-gateways
    content: "Phase 4: Gateways feature; guidelines gate"
    status: completed
  - id: p4-agents
    content: "Phase 4: Agents feature; guidelines gate"
    status: cancelled
  - id: p4-tests
    content: "Phase 4: Tests for gateway and agent services; guidelines gate"
    status: completed
  - id: p5-logs
    content: "Phase 5: Logs feature; guidelines gate"
    status: completed
  - id: p6-metrics
    content: "Phase 6: Metrics feature + formatters; guidelines gate"
    status: completed
  - id: p7-cutover
    content: "Phase 7: Cutover — parity, single UI at /, remove ui/, update docs; guidelines gate"
    status: completed
isProject: false
---

# HiroAdmin v2 — Clean Parallel Rebuild

Architecture guidelines: [hiroadmin_guidelines.md](d:\projects\hiroleague-website\docs\hiroadmin_guidelines.md)

Legacy UI: [hirocli/ui/](d:\projects\hiroleague\hiroserver\hirocli\src\hirocli\ui)

New code: `hiroserver/hirocli/src/hirocli/admin/`

---

## Significant gotchas (read before coding)

1. **Single NiceGUI app, path prefix required** — NiceGUI uses a global `core.app`. A second `ui.run_with()` does not give a second isolated app; duplicate `@ui.page("/")` would overwrite legacy routes. V2 must register with `APIRouter(prefix="/v2")` and `@v2_router.page(...)` so browser paths are `/v2/`, `/v2/workspaces`, etc. See [admin/router.py](d:\projects\hiroleague\hiroserver\hirocli\src\hirocli\admin\router.py) and [ui/run.py](d:\projects\hiroleague\hiroserver\hirocli\src\hirocli\ui\run.py) (`register_v2_routes` after `register_pages`).
2. **One admin port** — Legacy and v2 both use `http://127.0.0.1:{admin_port}`. Preview URL is `/v2/` (not a second port). Do not add a second Uvicorn for v2 unless you intentionally fork the architecture again.
3. **Nav paths vs `@ui.page`** — Sidebar `active_path` and `ui.navigate.to` must use **full paths** (e.g. `/v2/workspaces`), matching [navigation.py](d:\projects\hiroleague\hiroserver\hirocli\src\hirocli\admin\shell\navigation.py). Stubs pass both `rel_path` (for `@router.page`) and `nav_path` (for `create_page_layout(active_path=...)`); see [stubs.py](d:\projects\hiroleague\hiroserver\hirocli\src\hirocli\admin\stubs.py).
4. `**register_v2_routes` idempotency** — Guard with `_v2_admin_initialized` so `include_router` runs only once if startup ever calls registration twice.
5. **Quasar dark mode vs Tailwind** — `ui.dark_mode()` sets `body--dark`, not Tailwind `dark:`. Shell uses Quasar components / semantic classes per guidelines.
6. **Phase 7 route shape** — After cutover, v2 can move to `/` (drop prefix) or keep `/v2/`; plan assumes **legacy deleted and v2 owns root** — update router, NAV, and all `@router.page` paths in one coordinated change.

---

## Guidelines gate (end of every phase)

Before marking a phase complete, cross-check [hiroadmin_guidelines.md](d:\projects\hiroleague-website\docs\hiroadmin_guidelines.md):

- Thin **pages** only (no direct tool calls; no nested handlers that belong in components/controller).
- **Services** have no NiceGUI imports; return `Result` where applicable; context passed explicitly.
- **State**: right storage tier (`user` / `tab` / `client`); no scattered `storage.user` without helpers where the doc requires them.
- **Theming**: no stray hex in UI code outside `shared/theme.py`; Quasar/Tailwind classes elsewhere.
- **Shell**: workspace list via `WorkspaceSelectService` (or equivalent), not `WorkspaceListTool` inside `layout.py`.
- New **tests** for services introduced in that phase (minimum: service unit tests with mocked tools).

---

## Target folder structure

```text
hirocli/admin/
    __init__.py
    router.py                     # APIRouter prefix /v2
    run.py                          # build_admin_context, register_v2_routes
    context.py
    stubs.py
    shell/
        layout.py, navigation.py, workspace_service.py
    shared/
        result.py, theme.py, formatters.py
        ui/  (primitives)
    features/
        dashboard/   (page.py, … + tests/)
        …
```

---

## Key references

- Legacy entry: [hirocli/ui/run.py](d:\projects\hiroleague\hiroserver\hirocli\src\hirocli\ui\run.py) — sets legacy state, `register_pages()`, then `set_runtime_context`, `register_v2_routes()`, `apply_theme()`, one Uvicorn on `admin_port`.
- Composition: [server_process.py](d:\projects\hiroleague\hiroserver\hirocli\src\hirocli\runtime\server_process.py) — single `run_admin_ui(ctx)` when `--admin` (no separate v2 coroutine).
- Tools: `hirocli.tools.*` as today.

---

## Phase 0 — Foundation

- Package tree, `AdminContext`, `Result`, `theme`, `shared/ui` primitives, `shell` + `WorkspaceSelectService`, `router.py` + `v2_router`, dashboard placeholder on `@v2_router.page("/")`, stubs via `register_stub_pages(v2_router)`, `register_v2_routes()` from legacy `run_admin_ui`.
- **Verify**: `http://127.0.0.1:{admin_port}/` legacy + `http://127.0.0.1:{admin_port}/v2/` v2 shell and stubs.
- **Guidelines gate**: (checklist above).

---

## Phase 1 — Dashboard

- `DashboardService`, `components`, thin page on **v2 router** (path under `/v2/`), `Result` + loading/error/empty/data, tests.
- **Guidelines gate**.

---

## Phase 2 — Workspaces

- Full workspace service + components + page on `/v2/workspaces` (replace stub), tests, safety rules in service.
- **Guidelines gate**.

---

## Phase 3 — Channels + Devices

- Services, components, pages `/v2/channels`, `/v2/devices`; tests.
- **Guidelines gate**.

---

## Phase 4 — Gateways + Agents

- `/v2/gateways`, `/v2/agents`; tests.
- **Guidelines gate**.

---

## Phase 5 — Logs

- Service, controller, grid, components, styles, `/v2/logs`; `app.storage.tab` for log prefs; tests.
- **Guidelines gate**.

---

## Phase 6 — Metrics

- Service, charts, `/v2/metrics`, populate `shared/formatters.py`; tests.
- **Guidelines gate**.

---

## Phase 7 — Cutover

- **Done (partial)**: HiroAdmin owns `/` via `admin_router` (empty prefix); `server_process` calls `hirocli.admin.run.run_admin_ui`. Legacy `hirocli/ui/` tree kept on disk but `register_pages()` is not run — nothing under `hirocli.ui` is linked from production startup. `hirocli/ui/run.py` holds `_legacy_run_admin_ui_reference` only.
- Optional follow-up: delete `hirocli/ui/`, update mintdocs / website guidelines URLs.
- **Guidelines gate**: full app is HiroAdmin-only at root.

No backward compatibility required (initial development mode).