"""Detail-panel rendering for the admin Logs page.

Populates a NiceGUI column container with structured field blocks from a
log-row dict.  JSON / Python-literal values are pretty-printed.
"""

from __future__ import annotations

import html

from nicegui import ui

from hirocli.tools.logs import (
    _segment_to_key_value,
    _split_extra_segments,
    pretty_print_log_value,
)


def fill_detail_panel(detail_body: ui.column, row: dict | None) -> None:
    """Rebuild *detail_body* from a grid row dict.

    Clears the container first, then renders labelled field blocks.
    Extra values and Message are pretty-printed when they parse as JSON or
    Python literals.
    """
    detail_body.clear()
    with detail_body:
        if not row:
            ui.label("Click a row in the table to inspect a log line.").classes(
                "text-sm opacity-50"
            )
            return

        def _block(title: str, text: str, *, try_structure: bool = False) -> None:
            ui.label(title).classes("log-detail-field-label")
            raw = text or ""
            if try_structure:
                ok, out = pretty_print_log_value(raw)
                if ok:
                    ui.html(
                        f'<pre class="log-detail-json">{html.escape(out)}</pre>'
                    )
                    return
            ui.label(raw if raw else "—").classes(
                "text-sm whitespace-pre-wrap break-words mt-0.5"
            )

        ts = row.get("timestamp")
        ts_line = (
            f"{row.get('date_display', '')} {row.get('timestamp_display', '')}".strip()
        )
        _block("Time", ts_line)
        _block("Timestamp (epoch)", str(ts) if ts is not None else "")
        _block("Source", str(row.get("source", "") or ""))
        _block("Level", str(row.get("level", "") or ""))
        _block("Module", str(row.get("module", "") or ""))
        _block("Message", str(row.get("message", "") or ""), try_structure=True)

        raw_extra = str(row.get("extra", "") or "")
        ui.label("Extra").classes("log-detail-field-label")
        segs = _split_extra_segments(raw_extra)
        if not segs:
            ui.label("—").classes("text-sm opacity-50 mt-0.5")
        else:
            for seg in segs:
                k, v = _segment_to_key_value(seg)
                sub = k if k else "value"
                ui.label(sub).classes("log-detail-field-label")
                ok, out = pretty_print_log_value(v)
                if ok:
                    ui.html(
                        f'<pre class="log-detail-json">{html.escape(out)}</pre>'
                    )
                else:
                    ui.label(v if v else "—").classes(
                        "text-sm whitespace-pre-wrap break-words mt-0.5"
                    )
