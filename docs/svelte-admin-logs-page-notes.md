# Svelte Admin Logs Page Notes

## Current NiceGUI Features

- Route: `/logs`, mounted through `LogsPageController`.
- Loads logs for the selected workspace through the existing Python log tools.
- Initial load tails the latest `500` rows per discovered log source.
- Live tail polling runs every `0.5s`.
- Supported sources:
  - `server`
  - `channels`
  - `gateway`, only when `gateway.log` exists
  - `cli`, only when `cli.log` exists
- Source filter chips toggle each source on or off.
- Channel logs are grouped under `Channels`; individual channel filtering uses a multi-select.
- Channel selector is visible only when `Channels` is enabled.
- Level filter chips support `DEBUG`, `FINEINFO`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL`.
- Search box searches `message` and `extra`, case-insensitive.
- Search mode disables live polling until search text is cleared.
- Search results use the log search tool default limit of `200`.
- Sort toggle switches between `Newest first` and `Oldest first` using numeric timestamp order.
- Pause/Resume stops or restarts live polling.
- Auto-scroll scrolls to the newest visible edge based on sort order.
- Main table uses AG Grid with multi-row selection.
- Grid columns are hidden `timestamp`, `Date`, `Time`, `Source`, `Module`, `Lvl`, `Message`, and `Extra`.
- `Message` and `Extra` show tooltips.
- `Extra` renders colored `key=value` segments and has multi-line tooltip formatting.
- Log levels and modules are color-styled.
- Server startup rows are visually highlighted.
- Row selection is restored after reload/filter refresh when row IDs still match.
- Optional right-side `Log details` panel can be opened or closed.
- Clicking a row populates the details panel.
- Detail panel shows formatted time, raw epoch timestamp, source, level, module, message, and parsed extra fields.
- Detail panel pretty-prints JSON-like values where possible.
- Per-tab preferences persist paused state, sort order, active sources, active channels, level filters, search text, and detail panel open state.
- Shows a loading state while inspecting logs.
- Shows an error banner if runtime context has no log directory or log directory discovery fails.

## Svelte Implementation Notes

- Do not change or replace the NiceGUI logs page.
- If backend changes are needed to feed Svelte and may affect the NiceGUI log tools/page, call that out before making the change.
- Keep the UX and feature set aligned with NiceGUI, but do not port the NiceGUI controller/grid mutation model directly.
- Keep Python log parsing and discovery as the source of truth behind HTTP API endpoints.
- Use API calls for initial tail, poll-after-offsets, and search.
- Keep polling at `0.5s`, matching NiceGUI.
- Use Svelte reactive state or a dedicated store for rows, offsets, filters, search text, sort order, polling state, auto-scroll state, selected rows, and detail row.
- Implement polling with `setInterval` or a Svelte effect started on mount and cleaned up on destroy.
- Append new rows into reactive state; let the table render from state instead of imperatively mutating the grid.
- Use `@tanstack/svelte-table` with table rows derived from the current row array.
- Keep source, channel, and level filters as explicit client-side state over the current returned rows.
- Use client-side search if the Svelte page has all rows needed for the search scope; use server-backed search when full log search is required.
- Implement sort as derived state over visible rows, using numeric timestamp order.
- Implement auto-scroll by scrolling the table container directly after row updates.
- Track the active detail row in Svelte state.
- Support keyboard row navigation with arrow keys; when the detail panel is open, moving through rows should update the detail panel.
- Multi-row selection is not required for the Svelte implementation.
- Use `sessionStorage` for NiceGUI-like per-tab persistence.
- Start with the installed `@tanstack/svelte-table`; if its limitations affect expected logs UX, document the limitation and options before adding another grid dependency.
