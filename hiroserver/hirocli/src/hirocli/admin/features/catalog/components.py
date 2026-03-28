"""Catalog tables — shared data_table columns (guidelines §4)."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from hirocli.admin.shared.ui.data_table import data_table

CATALOG_PROVIDER_COLUMNS: list[dict[str, Any]] = [
    {
        "name": "display_name",
        "label": "Provider",
        "field": "display_name",
        "align": "left",
        "sortable": True,
    },
    {"name": "id", "label": "ID", "field": "id", "align": "left", "sortable": True},
    {"name": "hosting", "label": "Hosting", "field": "hosting", "align": "left"},
    {
        "name": "credential_env_keys",
        "label": "Credential env",
        "field": "credential_env_keys",
        "align": "left",
    },
    {
        "name": "metadata_updated_at",
        "label": "Updated",
        "field": "metadata_updated_at",
        "align": "left",
    },
]

CATALOG_MODEL_COLUMNS: list[dict[str, Any]] = [
    {
        "name": "provider_label",
        "label": "Provider",
        "field": "provider_label",
        "align": "left",
        "sortable": True,
    },
    {
        "name": "model_label",
        "label": "Model",
        "field": "model_label",
        "align": "left",
        "sortable": True,
    },
    {"name": "model_kind", "label": "Kind", "field": "model_kind", "align": "left"},
    {"name": "model_class", "label": "Class", "field": "model_class", "align": "left"},
    {"name": "hosting", "label": "Hosting", "field": "hosting", "align": "left"},
    {
        "name": "context_window",
        "label": "Context",
        "field": "context_window",
        "align": "right",
    },
    {"name": "pricing", "label": "Pricing", "field": "pricing", "align": "left"},
    {"name": "features", "label": "Features", "field": "features", "align": "left"},
]


def catalog_providers_table(rows: list[dict[str, Any]]) -> ui.table:
    """Providers summary table with env keys as comma-separated string in rows."""
    return data_table(
        columns=CATALOG_PROVIDER_COLUMNS,
        rows=rows,
        row_key="id",
    )


def catalog_models_table(rows: list[dict[str, Any]]) -> ui.table:
    return data_table(
        columns=CATALOG_MODEL_COLUMNS,
        rows=rows,
        row_key="id",
    )
