"""Theme-aware CSS for v2 logs — Quasar CSS variables only (guidelines §3.3)."""

from __future__ import annotations

LOG_COLORS_CSS = """
<style>
/* Level colours — semantic Quasar brand variables */
.log-lvl-debug    { color: var(--q-info) !important; }
.log-lvl-fineinfo { color: var(--q-secondary) !important; }
.log-lvl-info     { color: var(--q-positive) !important; }
.log-lvl-warning  { color: var(--q-warning) !important; font-weight: bold; }
.log-lvl-error    { color: var(--q-negative) !important; font-weight: bold; }
.log-lvl-critical { color: var(--q-accent) !important; font-weight: bold; }

/* Module colours — rotate brand hues */
.log-mod-0 { color: var(--q-info) !important; }
.log-mod-1 { color: var(--q-accent) !important; }
.log-mod-2 { color: var(--q-warning) !important; }
.log-mod-3 { color: var(--q-positive) !important; }

.log-startup-row .ag-cell {
  background-color: color-mix(in srgb, var(--q-dark) 12%, transparent) !important;
}
.body--dark .log-startup-row .ag-cell {
  background-color: color-mix(in srgb, var(--q-primary) 14%, transparent) !important;
}

.log-startup-msg { font-weight: 600; }

.log-extra-key { color: var(--q-secondary) !important; }
.log-extra-eq { color: var(--q-dark) !important; margin: 0 1px; opacity: 0.55; }
.log-extra-val { color: var(--q-primary) !important; }

.log-extra-tooltip-row {
    display: block;
    line-height: 1.45;
}
.log-extra-tooltip-row + .log-extra-tooltip-row {
    margin-top: 4px;
}

.ag-tooltip {
    max-width: 500px !important;
    white-space: pre-wrap !important;
    word-break: break-word !important;
    padding: 8px 12px !important;
    font-size: 12px !important;
    line-height: 1.4 !important;
}

.q-page:has(.logs-main-row) {
    overflow: hidden !important;
    padding: 0 !important;
}
.q-page:has(.logs-main-row) .nicegui-content {
    padding: 0 !important;
    box-sizing: border-box !important;
}
.logs-main-row {
    height: calc(100vh - 40px - 2rem) !important;
    max-height: calc(100vh - 40px - 2rem) !important;
    min-height: 12rem !important;
    overflow: hidden !important;
    box-sizing: border-box !important;
}
.logs-content-col {
    min-width: 0 !important;
    min-height: 0 !important;
    max-height: 100% !important;
    display: flex !important;
    flex-direction: column !important;
    overflow-y: auto !important;
}
.logs-grid-host {
    flex: 1 1 0 !important;
    min-height: 0 !important;
    min-width: 0 !important;
    overflow: hidden !important;
}
.logs-grid-host > * {
    height: 100% !important;
    min-height: 0 !important;
}

.log-detail-panel {
    display: flex;
    flex-direction: column;
    border-left: 1px solid color-mix(in srgb, var(--q-dark) 18%, transparent);
    background: color-mix(in srgb, var(--q-dark) 4%, transparent);
    height: 100%;
    min-height: 12rem;
}
.body--dark .log-detail-panel {
    border-left-color: color-mix(in srgb, var(--q-primary) 22%, transparent);
    background: color-mix(in srgb, var(--q-dark) 55%, transparent);
}
.log-detail-panel-header {
    flex-shrink: 0;
    border-bottom: 1px solid color-mix(in srgb, var(--q-dark) 14%, transparent);
    padding: 8px 10px;
}
.body--dark .log-detail-panel-header {
    border-bottom-color: color-mix(in srgb, var(--q-primary) 18%, transparent);
}
.log-detail-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 10px 12px;
}
.log-detail-field-label {
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    opacity: 0.55;
    margin-top: 10px;
}
.log-detail-field-label:first-child { margin-top: 0; }
.log-detail-json {
    font-family: ui-monospace, monospace;
    font-size: 0.75rem;
    line-height: 1.35;
    margin: 4px 0 0 0;
    padding: 8px 10px;
    border-radius: 6px;
    background: color-mix(in srgb, var(--q-dark) 8%, transparent);
    white-space: pre-wrap;
    word-break: break-word;
    overflow-x: auto;
}
.body--dark .log-detail-json {
    background: color-mix(in srgb, var(--q-dark) 40%, transparent);
}
</style>
"""
