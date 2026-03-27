"""Gateway instances table — Quasar slots (parity with legacy gateways page)."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from hirocli.admin.shared.ui.data_table import data_table

GATEWAY_TABLE_COLUMNS: list[dict[str, Any]] = [
    {"name": "name", "label": "Name", "field": "name", "align": "left", "sortable": True},
    {"name": "status", "label": "Status", "field": "running", "align": "left"},
    {"name": "host_port", "label": "Host : Port", "field": "port", "align": "left"},
    {"name": "is_default", "label": "Default", "field": "is_default", "align": "center"},
    {"name": "path", "label": "Path", "field": "path", "align": "left"},
    {"name": "actions", "label": "", "field": "name", "align": "right"},
]


def gateway_data_table(rows: list[dict[str, Any]]) -> ui.table:
    table = data_table(columns=GATEWAY_TABLE_COLUMNS, rows=rows, row_key="name")
    _apply_gateway_table_slots(table)
    return table


def _apply_gateway_table_slots(table: ui.table) -> None:
    table.add_slot(
        "body-cell-status",
        """
            <q-td :props="props">
                <q-badge
                    :color="props.row.running ? 'positive' : 'grey-6'"
                    :label="props.row.running ? 'Running' : 'Stopped'" />
                <span v-if="props.row.pid && props.row.running"
                      class="text-xs opacity-50 q-ml-xs">PID {{ props.row.pid }}</span>
            </q-td>
            """,
    )
    table.add_slot(
        "body-cell-host_port",
        """
            <q-td :props="props">
                <span class="text-xs font-mono">{{ props.row.host }}:{{ props.row.port }}</span>
            </q-td>
            """,
    )
    table.add_slot(
        "body-cell-is_default",
        """
            <q-td :props="props" class="text-center">
                <q-icon v-if="props.row.is_default" name="star" color="warning" size="sm" />
            </q-td>
            """,
    )
    table.add_slot(
        "body-cell-path",
        """
            <q-td :props="props">
                <span class="text-xs font-mono opacity-60">{{ props.row.path }}</span>
            </q-td>
            """,
    )
    table.add_slot(
        "body-cell-actions",
        """
            <q-td :props="props">
              <div class="row no-wrap justify-end items-center">

                <q-btn v-if="!props.row.running"
                       flat size="sm" icon="play_arrow" color="positive"
                       title="Start" class="q-ma-xs"
                       @click="() => $parent.$emit('start', props.row)" />

                <q-btn v-if="props.row.running"
                       flat size="sm" icon="stop" color="negative"
                       title="Stop" class="q-ma-xs"
                       @click="() => $parent.$emit('stop', props.row)" />

                <q-btn flat size="sm" icon="delete" color="negative"
                       title="Remove (teardown)" class="q-ma-xs"
                       @click="() => $parent.$emit('remove', props.row)" />

              </div>
            </q-td>
            """,
    )
