---
name: Phase 3a Admin UI
overview: Build two new admin dashboard pages — a read-only Catalog Browser under the Configuration nav group and a workspace-scoped Providers management page under the Server nav group — following the established page/controller/service pattern.
todos:
  - id: pricing-formatter
    content: Add format_pricing_summary helper to admin/shared/formatters.py
    status: completed
  - id: catalog-service
    content: Create admin/features/catalog/service.py wrapping the 3 catalog tools
    status: completed
  - id: catalog-controller
    content: Create admin/features/catalog/controller.py with providers summary + filterable models table
    status: completed
  - id: catalog-page
    content: Create admin/features/catalog/page.py with /catalog route
    status: completed
  - id: providers-service
    content: Create admin/features/providers/service.py wrapping provider tools + scan_env
    status: completed
  - id: providers-controller
    content: Create admin/features/providers/controller.py with status table, add/remove/scan actions
    status: completed
  - id: providers-page
    content: Create admin/features/providers/page.py with /providers route
    status: completed
  - id: nav-and-registration
    content: Add NavItems to navigation.py, imports to run.py, clean stubs.py
    status: completed
  - id: mintdocs-update
    content: Review and update mintdocs for the new admin pages
    status: completed
isProject: false
---

# Phase 3a — Admin UI: Catalog Browser and Providers Page

No backward compatibility required (initial development mode).

## Existing Architecture

Admin features follow a strict vertical-slice pattern (`page.py` -> `controller.py` -> `service.py`):

- **page.py** — thin route: `@admin_router.page(...)`, calls `create_page_layout(active_path=...)`, mounts controller
- **controller.py** — NiceGUI UI: `@ui.refreshable`, `run.io_bound(service_method, ...)`, dialogs
- **service.py** — no NiceGUI: wraps tools via `Tool().execute(...)`, returns `Result[T]`

Shared UI in `[admin/shared/ui/](hiroserver/hirocli/src/hirocli/admin/shared/ui/__init__.py)`: `data_table`, `form_dialog`, `confirm_dialog`, `loading_state`, `error_banner`, `empty_state`, `status_badge`

Navigation defined in `[admin/shell/navigation.py](hiroserver/hirocli/src/hirocli/admin/shell/navigation.py)` — append `NavItem` entries. Registration in `[admin/run.py](hiroserver/hirocli/src/hirocli/admin/run.py)` — import page module.

## 1. Catalog Browser Page (read-only reference)

**Route:** `/catalog` under "Configuration" nav group.

**New feature directory:** `admin/features/catalog/`

### `service.py`

Wraps the three existing catalog tools — no workspace required (catalog is static):

- `list_providers(hosting: str | None) -> Result[list[dict]]` — wraps `LlmCatalogListProvidersTool`
- `list_models(provider_id, model_kind, model_class, hosting) -> Result[list[dict]]` — wraps `LlmCatalogListModelsTool`
- `get_model(model_id: str) -> Result[dict]` — wraps `LlmCatalogGetModelTool` (for detail expansion)

### `controller.py`

Two-section layout:

**Providers summary** (top) — compact `data_table` or stat cards showing the 6 providers with hosting type, credential requirements, docs link.

**Models table** (main) — `data_table` with all catalog models, columns:

- Provider (display_name)
- Model (display_name + canonical ID)
- Kind (chat/tts/stt/embedding)
- Class (agentic/fast/balanced/reasoning or "—")
- Context window (formatted or "—")
- Pricing summary (smart format: "$X.XX / 1M in" for chat, "$X.XX / char" for TTS, etc. or "Free (local)")
- Key features (badges for tools, streaming, structured_output)

**Filters** — row of `ui.select` dropdowns above the table:

- Provider (all providers from catalog)
- Kind (chat, tts, stt, embedding, image_gen)
- Class (agentic, fast, balanced, reasoning, creative, coding)
- Hosting (cloud, local)

Filters call service with combined params, refresh the table. No workspace dependency — this page works without selecting a workspace.

### `page.py`

Standard thin route: `@admin_router.page("/catalog")`, `create_page_layout(active_path="/catalog")`, mount controller.

## 2. Providers Page (workspace-scoped)

**Route:** `/providers` under "Server" nav group.

**New feature directory:** `admin/features/providers/`

### `service.py`

Wraps existing provider tools — workspace-scoped:

- `list_configured(workspace_id: str) -> Result[list[dict]]` — wraps `ProviderListConfiguredTool`
- `add_api_key(workspace_id: str, provider_id: str, api_key: str) -> Result[dict]` — wraps `ProviderAddApiKeyTool`
- `remove_provider(workspace_id: str, provider_id: str) -> Result[dict]` — wraps `ProviderRemoveTool`
- `list_unconfigured_cloud_providers(workspace_id: str) -> Result[list[dict]]` — combines catalog `list_providers(hosting="cloud")` with `list_configured` to find providers not yet set up (for the "Add" dropdown)
- `scan_env(workspace_id: str) -> Result[int]` — uses `CredentialStore.import_detected_env_keys()` directly (no tool wrapper exists; call domain layer directly). Returns count of imported keys.

### `controller.py`

Workspace-gated (uses `get_selected_workspace()`):

**Provider status table** — `@ui.refreshable` async table showing:

- Provider (display_name)
- Status (status_badge: configured/not set/local)
- Auth method (api_key / local_endpoint / "—")
- Available models count
- Model kinds available (has_chat, has_tts, has_stt shown as badges)
- Actions column: Remove button (configured providers)

**Action bar** (above table):

- "Add API Key" button — opens `form_dialog` with:
  - Provider dropdown (populated from `list_unconfigured_cloud_providers` — only shows providers not yet configured)
  - API key input (password/masked)
  - On submit: calls `service.add_api_key(...)`, refreshes table, shows `ui.notify` success/error
- "Scan Environment" button — calls `service.scan_env(...)`, refreshes table, notifies how many keys imported
- Refresh button

**Remove flow** — `confirm_dialog`: "Remove credentials for {provider_name}? This workspace will lose access to {N} models." On confirm: `service.remove_provider(...)`, refresh table.

**Empty/error states** — no workspace selected -> `empty_state`; load failure -> `error_banner` with retry.

### `page.py`

Standard thin route: `@admin_router.page("/providers")`, `create_page_layout(active_path="/providers")`, mount controller.

## 3. Navigation and Registration

### `[navigation.py](hiroserver/hirocli/src/hirocli/admin/shell/navigation.py)` — add two entries

```python
# Under "Server" group (after Characters):
NavItem("Server", "Providers", "key", "/providers"),

# Under "Configuration" group (after Logs):
NavItem("Configuration", "Catalog", "auto_stories", "/catalog"),
```

### `[run.py](hiroserver/hirocli/src/hirocli/admin/run.py)` — import both page modules

```python
from hirocli.admin.features.catalog import page as _catalog    # noqa: F401
from hirocli.admin.features.providers import page as _providers  # noqa: F401
```

### Remove `/catalog` and `/providers` from stubs if present in `[stubs.py](hiroserver/hirocli/src/hirocli/admin/stubs.py)`.

## 4. Pricing Formatter Utility

Add a `format_pricing_summary(pricing: dict | None, model_kind: str) -> str` helper to `[admin/shared/formatters.py](hiroserver/hirocli/src/hirocli/admin/shared/formatters.py)` that produces human-readable one-line pricing:

- chat/embedding: `"$2.50 / $10.00 per 1M tokens"` (input/output)
- tts: `"$0.015 per 1K chars"`
- stt: `"$X.XX per minute"`
- image_gen: `"$X.XX per image"`
- None / local: `"Free (local)"` or `"—"`

This is reused by both the Catalog page and the future character editor (Phase 3b).

## 5. File Summary

New files to create:

- `admin/features/catalog/__init__.py`
- `admin/features/catalog/page.py`
- `admin/features/catalog/controller.py`
- `admin/features/catalog/service.py`
- `admin/features/providers/__init__.py`
- `admin/features/providers/page.py`
- `admin/features/providers/controller.py`
- `admin/features/providers/service.py`

Files to modify:

- `admin/shell/navigation.py` — add 2 NavItem entries
- `admin/run.py` — add 2 page imports
- `admin/shared/formatters.py` — add pricing formatter
- `admin/stubs.py` — remove stubs if present for `/catalog` or `/providers`

## 6. Mintlify Docs

Per project rules, review and update mintdocs if needed for the new admin pages. At minimum, mention the Catalog Browser and Providers pages in any existing admin documentation.