"""Configured providers table — remove action slot (guidelines §4, table action rules)."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from hirocli.admin.shared.ui.data_table import data_table

PROVIDER_TABLE_COLUMNS: list[dict[str, Any]] = [
    {
        "name": "display_label",
        "label": "Provider",
        "field": "display_label",
        "align": "left",
        "sortable": True,
    },
    {"name": "hosting", "label": "Hosting", "field": "hosting", "align": "left"},
    {"name": "auth_method", "label": "Auth", "field": "auth_method", "align": "left"},
    {
        "name": "model_count",
        "label": "Models",
        "field": "model_count",
        "align": "right",
        "sortable": True,
    },
    {"name": "kinds", "label": "Kinds", "field": "kinds", "align": "left"},
    {
        "name": "actions",
        "label": "",
        "field": "provider_id",
        "align": "right",
    },
]


def configured_providers_table(rows: list[dict[str, Any]]) -> ui.table:
    """Table rows must include provider_id, display_label, hosting, auth_method, model_count, kinds."""
    table = data_table(columns=PROVIDER_TABLE_COLUMNS, rows=rows, row_key="provider_id")
    table.add_slot(
        "body-cell-actions",
        """
            <q-td :props="props">
                <q-btn
                    flat
                    size="sm"
                    icon="delete"
                    color="negative"
                    class="q-ma-xs"
                    @click="$parent.$emit('remove', props.row)"
                />
            </q-td>
        """,
    )
    return table


def rows_from_summaries(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shape ProviderListConfiguredTool rows for the table."""
    out: list[dict[str, Any]] = []
    for r in raw:
        pid = str(r.get("provider_id", ""))
        name = str(r.get("display_name", pid))
        kinds: list[str] = []
        if r.get("has_chat"):
            kinds.append("chat")
        if r.get("has_tts"):
            kinds.append("tts")
        if r.get("has_stt"):
            kinds.append("stt")
        count = r.get("available_model_count", 0)
        try:
            count_i = int(count)
        except (TypeError, ValueError):
            count_i = 0
        out.append(
            {
                "provider_id": pid,
                "display_label": f"{name} ({pid})",
                "hosting": str(r.get("hosting", "—")),
                "auth_method": str(r.get("auth_method", "—")),
                "model_count": str(count_i),
                "kinds": ", ".join(kinds) if kinds else "—",
            }
        )
    return out
