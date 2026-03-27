"""Shared UI composition primitives (thin wrappers around Quasar / NiceGUI)."""

from hirocli.admin.shared.ui.confirm_dialog import ConfirmDialogHandles, confirm_dialog
from hirocli.admin.shared.ui.data_table import data_table
from hirocli.admin.shared.ui.empty_state import empty_state
from hirocli.admin.shared.ui.error_banner import error_banner
from hirocli.admin.shared.ui.form_dialog import FormField, form_dialog
from hirocli.admin.shared.ui.loading_state import loading_state
from hirocli.admin.shared.ui.stat_card import stat_card
from hirocli.admin.shared.ui.status_badge import status_badge
from hirocli.admin.shared.ui.warning_callout import warning_callout

__all__ = [
    "ConfirmDialogHandles",
    "FormField",
    "confirm_dialog",
    "data_table",
    "empty_state",
    "error_banner",
    "form_dialog",
    "loading_state",
    "stat_card",
    "status_badge",
    "warning_callout",
]
