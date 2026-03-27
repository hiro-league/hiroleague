"""Devices table — Quasar slots (parity with legacy devices page)."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from hirocli.admin.shared.ui.data_table import data_table

DEVICE_TABLE_COLUMNS: list[dict[str, Any]] = [
    {"name": "device_name", "label": "Name", "field": "device_name", "align": "left"},
    {"name": "device_id", "label": "Device ID", "field": "device_id", "align": "left"},
    {"name": "paired_at", "label": "Paired", "field": "paired_at", "align": "left"},
    {"name": "expires_at", "label": "Expires", "field": "expires_at", "align": "left"},
    {"name": "actions", "label": "", "field": "device_id", "align": "right"},
]


def device_data_table(rows: list[dict[str, Any]]) -> ui.table:
    table = data_table(columns=DEVICE_TABLE_COLUMNS, rows=rows, row_key="device_id")
    _apply_device_table_slots(table)
    return table


def _apply_device_table_slots(table: ui.table) -> None:
    table.add_slot(
        "body-cell-device_name",
        """
            <q-td :props="props">
                <span v-if="props.row.device_name" class="font-medium">{{ props.row.device_name }}</span>
                <span v-else class="opacity-40">—</span>
            </q-td>
            """,
    )
    table.add_slot(
        "body-cell-expires_at",
        """
            <q-td :props="props">
                {{ props.row.expires_at || '—' }}
            </q-td>
            """,
    )
    table.add_slot(
        "body-cell-actions",
        """
            <q-td :props="props" class="text-right">
                <q-btn flat dense size="sm" icon="link_off" color="negative" title="Revoke"
                       @click="() => $parent.$emit('revoke', props.row)" />
            </q-td>
            """,
    )
