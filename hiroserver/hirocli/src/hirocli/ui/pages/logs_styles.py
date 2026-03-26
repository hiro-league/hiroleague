"""Theme-aware CSS for the admin Logs page (AG Grid cells, tooltips, detail panel).

cellStyle {"function": "..."} does not apply in NiceGUI's AG Grid wrapper,
so colours are driven by html_columns + classes defined here.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Theme-aware CSS for log level and module colours.
# ---------------------------------------------------------------------------
LOG_COLORS_CSS = """
<style>
/* Level colours — light mode */
.log-lvl-debug    { color: #3b82f6 !important; }
.log-lvl-fineinfo { color: #0891b2 !important; }
.log-lvl-info     { color: #16a34a !important; }
.log-lvl-warning  { color: #ca8a04 !important; font-weight: bold; }
.log-lvl-error    { color: #dc2626 !important; font-weight: bold; }
.log-lvl-critical { color: #9333ea !important; font-weight: bold; }

/* Module colours — light mode (hash bucket 0-3) */
.log-mod-0 { color: #0891b2 !important; }
.log-mod-1 { color: #c026d3 !important; }
.log-mod-2 { color: #ca8a04 !important; }
.log-mod-3 { color: #16a34a !important; }

/* Dark-mode overrides */
.body--dark .log-lvl-debug    { color: #60a5fa !important; }
.body--dark .log-lvl-fineinfo { color: #22d3ee !important; }
.body--dark .log-lvl-info     { color: #4ade80 !important; }
.body--dark .log-lvl-warning  { color: #facc15 !important; }
.body--dark .log-lvl-error    { color: #f87171 !important; }
.body--dark .log-lvl-critical { color: #c084fc !important; }

.body--dark .log-mod-0 { color: #22d3ee !important; }
.body--dark .log-mod-1 { color: #e879f9 !important; }
.body--dark .log-mod-2 { color: #fde047 !important; }
.body--dark .log-mod-3 { color: #86efac !important; }

/* Startup row — neutral slate tint applied to every cell in the row.
   rowClassRules adds "log-startup-row" to the AG Grid row element when
   data.is_startup is true; targeting .ag-cell fills all columns. */
.log-startup-row .ag-cell { background-color: rgba(203, 213, 225, 0.35) !important; }
.body--dark .log-startup-row .ag-cell { background-color: rgba(71, 85, 105, 0.35) !important; }

/* Message text in startup rows — semi-bold for extra visual weight */
.log-startup-msg { font-weight: 600; }

/* Extra column — key / = / value hues (cell + custom HTML tooltip) */
:root {
    --log-extra-key: #64748b;
    --log-extra-eq: #94a3b8;
    --log-extra-val: #2563eb;
}
.body--dark {
    --log-extra-key: #94a3b8;
    --log-extra-eq: #cbd5e1;
    --log-extra-val: #93c5fd;
}

.log-extra-key { color: var(--log-extra-key) !important; }
.log-extra-eq { color: var(--log-extra-eq) !important; margin: 0 1px; }
.log-extra-val { color: var(--log-extra-val) !important; }

/* Extra tooltip: one block per key=value (innerHTML tooltip, not textContent) */
.log-extra-tooltip-row {
    display: block;
    line-height: 1.45;
}
.log-extra-tooltip-row + .log-extra-tooltip-row {
    margin-top: 4px;
}

/* Tooltip styling — wrap long cell values nicely (Message column uses plain text + newlines) */
.ag-tooltip {
    max-width: 500px !important;
    white-space: pre-wrap !important;
    word-break: break-word !important;
    padding: 8px 12px !important;
    font-size: 12px !important;
    line-height: 1.4 !important;
}

/* Log detail panel — page-level sibling of content column, fills full height */
.log-detail-panel {
    display: flex;
    flex-direction: column;
    border-left: 1px solid rgba(148, 163, 184, 0.45);
    background: rgba(248, 250, 252, 0.85);
    height: 100%;
    min-height: 12rem;
}
.body--dark .log-detail-panel {
    border-left-color: rgba(71, 85, 105, 0.8);
    background: rgba(15, 23, 42, 0.55);
}
.log-detail-panel-header {
    flex-shrink: 0;
    border-bottom: 1px solid rgba(148, 163, 184, 0.35);
    padding: 8px 10px;
}
.body--dark .log-detail-panel-header {
    border-bottom-color: rgba(71, 85, 105, 0.6);
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
    background: rgba(15, 23, 42, 0.06);
    white-space: pre-wrap;
    word-break: break-word;
    overflow-x: auto;
}
.body--dark .log-detail-json {
    background: rgba(0, 0, 0, 0.25);
}
</style>
"""
