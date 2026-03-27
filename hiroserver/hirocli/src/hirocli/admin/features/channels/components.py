"""Channels table — Quasar slots (parity with legacy channels page)."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME

from hirocli.admin.shared.ui.data_table import data_table

CHANNEL_TABLE_COLUMNS: list[dict[str, Any]] = [
    {"name": "name", "label": "Name", "field": "name", "align": "left", "sortable": True},
    {"name": "enabled", "label": "Status", "field": "enabled", "align": "left"},
    {"name": "command", "label": "Command", "field": "command", "align": "left"},
    {"name": "config_keys", "label": "Config keys", "field": "config_keys", "align": "left"},
    {"name": "actions", "label": "", "field": "name", "align": "right"},
]


def channel_data_table(rows: list[dict[str, Any]]) -> ui.table:
    """Full-width channel table with status, config chips, and enable/disable actions."""
    table = data_table(columns=CHANNEL_TABLE_COLUMNS, rows=rows, row_key="name")
    _apply_channel_table_slots(table)
    return table


def _apply_channel_table_slots(table: ui.table) -> None:
    # Mandatory channel name is fixed; embed for Quasar template (same as legacy).
    mandatory = MANDATORY_CHANNEL_NAME
    table.add_slot(
        "body-cell-enabled",
        """
            <q-td :props="props">
                <q-badge :color="props.row.enabled ? 'positive' : 'grey-6'"
                         :label="props.row.enabled ? 'Enabled' : 'Disabled'" />
            </q-td>
            """,
    )
    table.add_slot(
        "body-cell-config_keys",
        """
            <q-td :props="props">
                <q-chip v-for="key in props.row.config_keys" :key="key"
                        dense size="sm" :label="key" class="mr-1" />
            </q-td>
            """,
    )
    table.add_slot(
        "body-cell-actions",
        f"""
            <q-td :props="props" class="text-right">
                <template v-if="props.row.name !== '{mandatory}'">
                    <q-btn v-if="props.row.enabled" flat dense size="sm"
                           icon="toggle_on" color="positive" title="Disable"
                           @click="() => $parent.$emit('disable', props.row)" />
                    <q-btn v-else flat dense size="sm"
                           icon="toggle_off" color="grey-6" title="Enable"
                           @click="() => $parent.$emit('enable', props.row)" />
                </template>
                <q-icon v-else name="lock" size="sm" class="opacity-30"
                        title="Mandatory channel — cannot be disabled" />
            </q-td>
            """,
    )
