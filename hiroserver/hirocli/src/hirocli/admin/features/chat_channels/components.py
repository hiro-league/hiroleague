"""Chat channels UI fragments — tables and message bubbles."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from hirocli.admin.shared.ui.data_table import data_table

CHANNEL_TABLE_COLUMNS: list[dict[str, Any]] = [
    {"name": "id", "label": "ID", "field": "id", "align": "left"},
    {"name": "name", "label": "Name", "field": "name", "align": "left"},
    {"name": "type", "label": "Type", "field": "type", "align": "left"},
    {"name": "agent_id", "label": "Agent", "field": "agent_id", "align": "left"},
    {"name": "user_id", "label": "User", "field": "user_id", "align": "left"},
    {"name": "last_message_at", "label": "Last activity", "field": "last_message_at", "align": "left"},
    {"name": "actions", "label": "", "field": "id", "align": "right"},
]


def channels_data_table(rows: list[dict[str, Any]]) -> ui.table:
    table = data_table(columns=CHANNEL_TABLE_COLUMNS, rows=rows, row_key="id")
    _apply_channel_table_slots(table)
    return table


def _apply_channel_table_slots(table: ui.table) -> None:
    table.add_slot(
        "body-cell-last_message_at",
        """
            <q-td :props="props">
                {{ props.row.last_message_at || '—' }}
            </q-td>
            """,
    )
    table.add_slot(
        "body-cell-actions",
        """
            <q-td :props="props" class="text-right nowrap">
                <q-btn flat dense size="sm" icon="chat" color="primary" title="Messages"
                       class="q-mr-xs"
                       @click="() => $parent.$emit('open_messages', props.row)" />
                <q-btn flat dense size="sm" icon="edit" color="secondary" title="Edit"
                       class="q-mr-xs"
                       @click="() => $parent.$emit('edit_channel', props.row)" />
                <q-btn flat dense size="sm" icon="delete" color="negative" title="Delete"
                       @click="() => $parent.$emit('delete_channel', props.row)" />
            </q-td>
            """,
    )


def message_bubble_thread(messages: list[dict[str, Any]]) -> None:
    """Read-only transcript: user messages right, agent (and other) left."""
    with ui.column().classes("w-full gap-3 py-2"):
        for m in messages:
            sender_type = str(m.get("sender_type") or "")
            is_user = sender_type == "user"
            row_cls = "w-full flex justify-end" if is_user else "w-full flex justify-start"
            bubble_cls = (
                "rounded-2xl px-4 py-2 max-w-[85%] shadow-sm "
                "bg-primary text-white"
                if is_user
                else "rounded-2xl px-4 py-2 max-w-[85%] shadow-sm bg-grey-3"
            )
            body = str(m.get("body") or "")
            ts = str(m.get("created_at") or "")
            sid = str(m.get("sender_id") or "")
            meta = f"{sender_type or 'unknown'} · {sid}" if sid else (sender_type or "unknown")
            with ui.element("div").classes(row_cls):
                with ui.column().classes(bubble_cls + " gap-1"):
                    ui.label(body).classes("text-sm whitespace-pre-wrap break-words")
                    ui.label(meta).classes("text-xs opacity-70")
                    if ts:
                        ui.label(ts).classes("text-xs opacity-50")
