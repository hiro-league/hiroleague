"""Workspaces table columns and Quasar cell slots (parity with legacy workspaces page)."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from hirocli.admin.shared.ui.data_table import data_table

WORKSPACE_TABLE_COLUMNS: list[dict[str, Any]] = [
    {"name": "name", "label": "Name", "field": "name", "align": "left", "sortable": True},
    {"name": "setup", "label": "Setup", "field": "is_configured", "align": "left"},
    {"name": "status", "label": "Server", "field": "running", "align": "left"},
    {"name": "autostart", "label": "Autostart", "field": "autostart_method", "align": "left"},
    {"name": "gateway_url", "label": "Gateway", "field": "gateway_url", "align": "left"},
    {"name": "http_port", "label": "HTTP", "field": "http_port", "align": "left"},
    {"name": "admin_port", "label": "Admin", "field": "admin_port", "align": "left"},
    {"name": "folder", "label": "Folder", "field": "path", "align": "left"},
    {"name": "is_default", "label": "Default", "field": "is_default", "align": "center"},
    {"name": "actions", "label": "", "field": "name", "align": "right"},
]


def workspace_data_table(rows: list[dict[str, Any]]) -> ui.table:
    """Shared ``data_table`` primitive + workspace-specific Quasar slots (guidelines §4)."""
    table = data_table(columns=WORKSPACE_TABLE_COLUMNS, rows=rows, row_key="id")
    apply_workspace_table_slots(table)
    return table


def apply_workspace_table_slots(table: ui.table) -> None:
    """Register body-cell-* slots; events are emitted to the table (setup, pubkey, …)."""
    table.add_slot(
        "body-cell-setup",
        """
            <q-td :props="props">
                <q-badge
                    :color="props.row.is_configured ? 'positive' : 'warning'"
                    :label="props.row.is_configured ? 'Configured' : 'Needs setup'" />
            </q-td>
            """,
    )
    table.add_slot(
        "body-cell-status",
        """
            <q-td :props="props">
                <q-badge
                    :color="props.row.running ? 'positive' : 'grey-6'"
                    :label="props.row.running ? 'Running' : 'Stopped'" />
                <q-badge v-if="props.row.is_current" color="info" label="this UI"
                         class="q-ml-xs" />
            </q-td>
            """,
    )
    table.add_slot(
        "body-cell-autostart",
        """
            <q-td :props="props">
                <q-badge v-if="props.row.autostart_method === 'elevated'"
                         color="deep-purple" label="elevated" />
                <q-badge v-else-if="props.row.autostart_method === 'schtasks'"
                         color="primary" label="schtasks" />
                <q-badge v-else-if="props.row.autostart_method === 'registry'"
                         color="teal" label="registry" />
                <q-badge v-else-if="props.row.autostart_method === 'skipped'"
                         color="grey-6" label="skipped" />
                <q-badge v-else-if="props.row.autostart_method === 'failed'"
                         color="negative" label="failed" />
                <span v-else class="opacity-30 text-xs">—</span>
            </q-td>
            """,
    )
    table.add_slot(
        "body-cell-gateway_url",
        """
            <q-td :props="props">
                <div v-if="props.row.gateway_url && props.row.running"
                     class="row items-center gap-1">
                    <q-icon name="cable" size="xs" color="primary" />
                    <a :href="props.row.gateway_url.replace(/^ws/, 'http')"
                       target="_blank"
                       class="text-xs font-mono text-primary hover:underline cursor-pointer"
                       :title="props.row.gateway_url">
                        {{ props.row.gateway_url }}
                    </a>
                </div>
                <span v-else-if="props.row.gateway_url" class="text-xs font-mono opacity-50">
                    {{ props.row.gateway_url }}
                </span>
                <span v-else class="opacity-30 text-xs">—</span>
            </q-td>
            """,
    )
    table.add_slot(
        "body-cell-http_port",
        """
            <q-td :props="props">
                <div v-if="props.row.running" class="row items-center gap-2">
                    <a :href="'http://127.0.0.1:' + props.row.http_port + '/status'"
                       target="_blank"
                       class="text-primary hover:opacity-70"
                       :title="'http://127.0.0.1:' + props.row.http_port + '/status'">
                        <q-icon name="open_in_browser" size="xs" />
                    </a>
                </div>
                <span v-else class="text-xs font-mono opacity-50">
                    {{ props.row.http_port }}
                </span>
            </q-td>
            """,
    )
    table.add_slot(
        "body-cell-admin_port",
        """
            <q-td :props="props">
                <div v-if="props.row.running" class="row items-center gap-2">
                    <a :href="'http://127.0.0.1:' + props.row.admin_port + '/'"
                       target="_blank"
                       class="text-primary hover:opacity-70"
                       :title="'Admin UI: http://127.0.0.1:' + props.row.admin_port + '/'">
                        <q-icon name="dashboard" size="xs" />
                    </a>
                </div>
                <span v-else class="text-xs font-mono opacity-50">
                    {{ props.row.admin_port }}
                </span>
            </q-td>
            """,
    )
    table.add_slot(
        "body-cell-folder",
        """
            <q-td :props="props">
                <span class="text-xs cursor-pointer text-primary hover:underline"
                      @click="() => $parent.$emit('open-folder', props.row)"
                      title="Open workspace folder">
                    📁
                </span>
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
        "body-cell-actions",
        """
            <q-td :props="props">
              <div class="row no-wrap justify-end items-center">

                <q-btn v-if="!props.row.is_configured"
                       flat size="sm" icon="settings" color="warning"
                       title="Run setup" class="q-ma-xs"
                       @click="() => $parent.$emit('setup', props.row)" />

                <q-btn v-if="props.row.is_configured"
                       flat size="sm" icon="key" color="secondary"
                       title="View / regenerate public key" class="q-ma-xs"
                       @click="() => $parent.$emit('pubkey', props.row)" />

                <q-btn v-if="props.row.is_configured && !props.row.running"
                       flat size="sm" icon="play_arrow" color="positive"
                       title="Start" class="q-ma-xs"
                       @click="() => $parent.$emit('start', props.row)" />

                <q-btn v-if="props.row.running && !props.row.is_current"
                       flat size="sm" icon="stop" color="negative"
                       title="Stop" class="q-ma-xs"
                       @click="() => $parent.$emit('stop', props.row)" />

                <q-btn v-if="props.row.running"
                       flat size="sm" icon="restart_alt" color="primary"
                       title="Restart" class="q-ma-xs"
                       @click="() => $parent.$emit('restart', props.row)" />

                <q-btn flat size="sm" icon="edit" color="secondary"
                       title="Edit workspace" class="q-ma-xs"
                       @click="() => $parent.$emit('edit', props.row)" />

                <q-btn v-if="!props.row.is_current"
                       flat size="sm" icon="delete" color="negative"
                       title="Remove" class="q-ma-xs"
                       @click="() => $parent.$emit('remove', props.row)" />
                <q-btn v-if="props.row.is_current"
                       flat size="sm" icon="lock" color="grey-5"
                       title="Cannot remove: this workspace is running the Admin UI"
                       class="q-ma-xs" disable />

              </div>
            </q-td>
            """,
    )
