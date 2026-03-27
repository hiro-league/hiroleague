"""Devices page — pairing dialog, revoke confirm, refreshable list (guidelines §2.3)."""

from __future__ import annotations

from collections.abc import Callable

from nicegui import run, ui

from hirocli.admin.context import get_selected_workspace
from hirocli.admin.features.devices.components import device_data_table
from hirocli.admin.features.devices.service import DeviceService
from hirocli.admin.shared.ui.confirm_dialog import confirm_dialog
from hirocli.admin.shared.ui.empty_state import empty_state
from hirocli.admin.shared.ui.error_banner import error_banner
from hirocli.admin.shared.ui.loading_state import loading_state
from hirocli.qr_rendering import render_qr_svg


class DevicePageController:
    """Pairing + approved devices; service calls off the UI thread where appropriate."""

    def __init__(self) -> None:
        self._service = DeviceService()
        self._refresh_table: Callable[[], None] | None = None
        self._pending_revoke_device_id = ""
        self._pending_qr_payload = ""

    def _refresh(self) -> None:
        if self._refresh_table:
            self._refresh_table()

    async def _copy_qr_payload(self) -> None:
        # ui.clipboard.write returns None in this NiceGUI version — do not await it.
        ui.clipboard.write(self._pending_qr_payload)
        ui.notify("Pairing message copied to clipboard.", color="positive", timeout=2500)

    async def _do_revoke_confirmed(self) -> None:
        ws = get_selected_workspace()
        res = await run.io_bound(
            self._service.revoke_device,
            self._pending_revoke_device_id,
            ws,
        )
        if not res.ok:
            ui.notify(res.error or "Revoke failed", color="negative")
            return False
        ui.notify(res.data or "Device revoked.", color="positive")
        self._refresh()
        return None

    def _build_pairing_dialog(self) -> None:
        self._pairing_dialog = ui.dialog()
        with self._pairing_dialog, ui.card().classes("w-96 items-center text-center gap-2"):
            ui.label("Pairing code").classes("text-base font-semibold")
            self._pairing_qr_html = ui.html("").classes("w-48 h-48 mx-auto my-2")
            self._pairing_code_label = ui.label("").classes(
                "text-5xl font-bold font-mono tracking-widest text-primary my-3"
            )
            self._pairing_expires_label = ui.label("").classes("text-sm opacity-60")
            ui.label("Scan the QR code or enter the code manually in the mobile app.").classes(
                "text-sm opacity-70 mb-2"
            )
            with ui.row().classes("w-full items-center justify-center gap-1 mb-1"):
                ui.icon("cable").classes("text-xs opacity-50")
                self._pairing_gateway_label = ui.label("").classes("text-xs font-mono opacity-60")

            ui.button(
                "Copy pairing message",
                icon="content_copy",
                on_click=self._copy_qr_payload,
            ).props("flat dense size=sm").classes("mb-1").tooltip(
                "Copy the full pairing JSON — paste it as a single field in the mobile app"
            )
            ui.button("Close", on_click=self._pairing_dialog.close).props("flat")

    def _build_revoke_confirm(self) -> None:
        self._revoke_confirm = confirm_dialog(
            title="Revoke device?",
            message="This device will no longer be able to connect.",
            confirm_label="Revoke",
            confirm_icon="link_off",
            on_confirm=self._do_revoke_confirmed,
        )

    async def _on_revoke_row(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        device_id = str(row.get("device_id", ""))
        self._pending_revoke_device_id = device_id
        display_name = row.get("device_name") or None
        if not display_name:
            short_id = device_id[:12] + "…" if len(device_id) > 12 else device_id
            display_name = short_id
        self._revoke_confirm.title_label.set_text(f"Revoke '{display_name}'?")
        self._revoke_confirm.dialog.open()

    async def _generate_pairing_code(self) -> None:
        ws = get_selected_workspace()
        res = await run.io_bound(self._service.generate_pairing_code, ws)
        if not res.ok:
            ui.notify(res.error or "Failed to generate code", color="negative")
            return
        data = res.data
        assert data is not None
        self._pairing_qr_html.set_content(render_qr_svg(data.qr_payload))
        self._pairing_code_label.set_text(data.code)
        expires = data.expires_at.replace("T", " ").replace("Z", " UTC")
        self._pairing_expires_label.set_text(f"Expires: {expires}")
        self._pairing_gateway_label.set_text(data.gateway_url or "no gateway configured")
        self._pending_qr_payload = data.qr_payload
        self._pairing_dialog.open()
        self._refresh()

    async def mount(self) -> None:
        self._build_pairing_dialog()
        self._build_revoke_confirm()

        @ui.refreshable
        async def device_list() -> None:
            ws_id = get_selected_workspace()
            if not ws_id:
                empty_state(
                    message="No workspace selected. Choose one in the sidebar.",
                    icon="storage",
                )
                return
            with ui.column().classes("w-full") as holder:
                with holder:
                    loading_state(message="Loading devices…")
                result = await run.io_bound(self._service.list_devices, ws_id)
                holder.clear()
                with holder:
                    if not result.ok:
                        error_banner(
                            message=result.error or "Failed to load devices",
                            on_retry=self._refresh,
                        )
                        return
                    devices = result.data or []
                    if not devices:
                        empty_state(
                            message="No paired devices. Use the button above to generate a pairing code.",
                            icon="devices",
                        )
                        return
                    table = device_data_table(devices)
                    table.on("revoke", self._on_revoke_row)

        self._refresh_table = device_list.refresh

        with ui.column().classes("w-full gap-6 p-6"):
            ui.label("Devices").classes("text-2xl font-semibold")
            with ui.card().classes("w-full"):
                ui.label("Pair new device").classes("text-base font-semibold mb-3")
                ui.label(
                    "Generate a short-lived code and enter it on your mobile device to authorize it."
                ).classes("text-sm opacity-60 mb-3")
                ui.button("Generate pairing code", icon="add_link", on_click=self._generate_pairing_code)
            ui.label("Approved devices").classes("text-lg font-semibold")
            await device_list()
