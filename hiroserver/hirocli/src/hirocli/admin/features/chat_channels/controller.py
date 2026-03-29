"""Tabbed chat channels: list/CRUD + read-only message transcript (guidelines §1.6)."""

from __future__ import annotations

from nicegui import app, run, ui

from hirocli.admin.context import get_selected_workspace
from hirocli.admin.features.chat_channels import components
from hirocli.admin.features.chat_channels.service import ChatChannelsService
from hirocli.admin.shared.tab_nav import TabNavRequest
from hirocli.admin.shared.ui.confirm_dialog import confirm_dialog
from hirocli.admin.shared.ui.empty_state import empty_state
from hirocli.admin.shared.ui.error_banner import error_banner
from hirocli.admin.shared.ui.loading_state import loading_state

TABS = ["channels", "messages"]
DEFAULT_TAB = "channels"
STORAGE_KEY = "chat_channels.active_tab"
PAGE_PATH = "/chats"


class ChatChannelsController:
    def __init__(self, nav: TabNavRequest | None = None) -> None:
        self._svc = ChatChannelsService()
        self._nav = nav
        self._filters: dict[str, dict] = {t: {} for t in TABS}
        self._loaded: set[str] = set()
        self._pending_delete: dict[str, object] = {}

    def _init_tab_state(self) -> None:
        nav = self._nav
        initial = (nav and nav.tab) or app.storage.tab.get(STORAGE_KEY) or DEFAULT_TAB
        if initial not in TABS:
            initial = DEFAULT_TAB
        app.storage.tab[STORAGE_KEY] = initial

        if nav:
            for t in TABS:
                self._filters[t] = nav.filter_for(t)

    async def mount(self) -> None:
        await ui.context.client.connected()
        self._init_tab_state()
        initial_tab = app.storage.tab[STORAGE_KEY]

        self._build_create_dialog()
        self._build_edit_dialog()
        self._delete_confirm = confirm_dialog(
            title="Delete conversation channel?",
            message="All messages in this channel will be removed.",
            confirm_label="Delete",
            confirm_icon="delete",
            on_confirm=self._do_delete_confirmed,
        )

        with ui.column().classes("w-full gap-0 p-6"):
            ui.label("Chat channels").classes("text-2xl font-semibold")
            ui.label(
                "Conversation threads in the selected workspace (data.db). "
                "Server messaging plugins live under Server → Channels."
            ).classes("text-sm opacity-70 max-w-3xl mb-4")

            with ui.tabs(value=initial_tab).bind_value(app.storage.tab, STORAGE_KEY) as tabs:
                ui.tab("channels", label="Channels", icon="forum")
                ui.tab("messages", label="Messages", icon="chat")

            tabs.on_value_change(self._on_tab_switch)

            with ui.tab_panels(tabs, value=initial_tab).bind_value(
                app.storage.tab, STORAGE_KEY
            ).classes("w-full"):
                with ui.tab_panel("channels"):
                    self._render_channels()
                with ui.tab_panel("messages"):
                    self._render_messages()

        self._mark_loaded(initial_tab)

    def _build_create_dialog(self) -> None:
        self._dlg_create = ui.dialog()
        with self._dlg_create, ui.card().classes("w-[28rem]"):
            ui.label("New conversation channel").classes("text-lg font-semibold mb-2")
            self._in_c_name = ui.input("Name").classes("w-full")
            self._in_c_user = ui.number("User ID").props("min=1").classes("w-full")
            self._in_c_agent = ui.input("Agent ID").classes("w-full")
            self._in_c_type = ui.input("Type").classes("w-full")
            self._in_c_type.value = "direct"

            async def _submit() -> None:
                ws = get_selected_workspace()
                name = (self._in_c_name.value or "").strip()
                uid = self._in_c_user.value
                agent = (self._in_c_agent.value or "").strip()
                ctype = (self._in_c_type.value or "direct").strip() or "direct"
                if not ws:
                    ui.notify("No workspace selected.", color="negative")
                    return
                if not name or not agent or uid is None or int(uid) < 1:
                    ui.notify("Name, User ID (≥1), and Agent ID are required.", color="negative")
                    return
                res = await run.io_bound(
                    lambda: self._svc.create_channel(
                        ws,
                        name=name,
                        user_id=int(uid),
                        agent_id=agent,
                        channel_type=ctype,
                    ),
                )
                if not res.ok:
                    ui.notify(res.error or "Create failed", color="negative")
                    return
                ui.notify("Channel created.", color="positive")
                self._dlg_create.close()
                self._render_channels.refresh()
                self._render_messages.refresh()

            with ui.row().classes("justify-end gap-2 w-full mt-4"):
                ui.button("Cancel", on_click=self._dlg_create.close).props("flat")
                ui.button("Create", on_click=_submit).props("color=primary")

    def _build_edit_dialog(self) -> None:
        self._edit_channel_id: int | None = None
        self._dlg_edit = ui.dialog()
        with self._dlg_edit, ui.card().classes("w-[28rem]"):
            ui.label("Edit conversation channel").classes("text-lg font-semibold mb-2")
            self._in_e_name = ui.input("Name").classes("w-full")
            self._in_e_user = ui.number("User ID").props("min=1").classes("w-full")
            self._in_e_agent = ui.input("Agent ID").classes("w-full")
            self._in_e_type = ui.input("Type").classes("w-full")

            async def _submit() -> None:
                ws = get_selected_workspace()
                cid = self._edit_channel_id
                if not ws or cid is None:
                    ui.notify("Missing workspace or channel.", color="negative")
                    return
                name = (self._in_e_name.value or "").strip()
                uid = self._in_e_user.value
                agent = (self._in_e_agent.value or "").strip()
                ctype = (self._in_e_type.value or "direct").strip() or "direct"
                if not name or not agent or uid is None or int(uid) < 1:
                    ui.notify("Name, User ID (≥1), and Agent ID are required.", color="negative")
                    return
                res = await run.io_bound(
                    lambda: self._svc.update_channel(
                        ws,
                        cid,
                        name=name,
                        channel_type=ctype,
                        agent_id=agent,
                        user_id=int(uid),
                    ),
                )
                if not res.ok:
                    ui.notify(res.error or "Update failed", color="negative")
                    return
                ui.notify("Channel updated.", color="positive")
                self._dlg_edit.close()
                self._render_channels.refresh()
                self._render_messages.refresh()

            with ui.row().classes("justify-end gap-2 w-full mt-4"):
                ui.button("Cancel", on_click=self._dlg_edit.close).props("flat")
                ui.button("Save", on_click=_submit).props("color=primary")

    def _on_tab_switch(self, e) -> None:
        self._mark_loaded(e.value)
        self._sync_url(e.value)

    def _mark_loaded(self, tab: str) -> None:
        if tab not in self._loaded:
            self._loaded.add(tab)
            refreshable = getattr(self, f"_render_{tab}", None)
            if refreshable:
                refreshable.refresh()

    def switch_to_tab(self, tab: str, **filters: object) -> None:
        self._filters[tab] = {k: v for k, v in filters.items() if v is not None}
        app.storage.tab[STORAGE_KEY] = tab
        self._loaded.add(tab)
        getattr(self, f"_render_{tab}").refresh()
        self._sync_url(tab)

    def _sync_url(self, tab: str) -> None:
        from urllib.parse import urlencode

        params: dict[str, str] = {"tab": tab}
        for k, v in self._filters.get(tab, {}).items():
            if v is not None:
                params[k] = str(v)
        query = urlencode(params)
        ui.run_javascript(f"history.replaceState(null, '', '{PAGE_PATH}?{query}')")

    @staticmethod
    def _effective_channel_id(
        channels: list[dict[str, object]],
        filters: dict[str, object],
    ) -> int | None:
        raw = filters.get("channel_id")
        if raw is not None and str(raw).strip():
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
        if channels:
            return int(channels[0]["id"])  # type: ignore[arg-type]
        return None

    @ui.refreshable
    async def _render_channels(self) -> None:
        if "channels" not in self._loaded:
            loading_state()
            return

        ws = get_selected_workspace()
        if not ws:
            empty_state(
                message="No workspace selected. Choose one in the header.",
                icon="storage",
            )
            return

        result = await run.io_bound(self._svc.list_channels, ws)
        if not result.ok:
            error_banner(
                message=result.error or "Failed to load channels",
                on_retry=self._render_channels.refresh,
            )
            return

        rows = result.data or []
        with ui.column().classes("w-full gap-4"):
            ui.button("Add channel", icon="add", on_click=self._open_create).props(
                "color=primary"
            )
            if not rows:
                empty_state(
                    message="No conversation channels yet.",
                    icon="forum",
                )
                return
            table = components.channels_data_table(rows)
            table.on("open_messages", self._on_open_messages)
            table.on("edit_channel", self._on_edit_channel)
            table.on("delete_channel", self._on_delete_channel)

    def _open_create(self) -> None:
        self._in_c_name.value = ""
        self._in_c_user.value = None
        self._in_c_agent.value = ""
        self._in_c_type.value = "direct"
        self._dlg_create.open()

    async def _on_open_messages(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        cid = row.get("id")
        if cid is None:
            return
        self.switch_to_tab("messages", channel_id=str(cid))

    def _on_edit_channel(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        cid = row.get("id")
        if cid is None:
            return
        self._edit_channel_id = int(cid)
        self._in_e_name.value = str(row.get("name") or "")
        self._in_e_user.value = int(row.get("user_id") or 0)
        self._in_e_agent.value = str(row.get("agent_id") or "")
        self._in_e_type.value = str(row.get("type") or "direct")
        self._dlg_edit.open()

    def _on_delete_channel(self, e) -> None:
        row = e.args if isinstance(e.args, dict) else {}
        self._pending_delete = dict(row)
        name = str(row.get("name") or row.get("id") or "?")
        self._delete_confirm.title_label.set_text(f"Delete channel '{name}'?")
        self._delete_confirm.dialog.open()

    async def _do_delete_confirmed(self) -> None:
        ws = get_selected_workspace()
        raw_id = self._pending_delete.get("id")
        if not ws or raw_id is None:
            ui.notify("Nothing to delete.", color="negative")
            return False
        cid = int(raw_id)
        res = await run.io_bound(self._svc.delete_channel, ws, cid)
        if not res.ok:
            ui.notify(res.error or "Delete failed", color="negative")
            return False
        ui.notify("Channel deleted.", color="positive")
        viewing = self._filters["messages"].get("channel_id")
        if viewing is not None and str(viewing) == str(cid):
            self._filters["messages"] = {}
        self._render_channels.refresh()
        self._render_messages.refresh()
        return None

    @ui.refreshable
    async def _render_messages(self) -> None:
        if "messages" not in self._loaded:
            loading_state()
            return

        ws = get_selected_workspace()
        if not ws:
            empty_state(
                message="No workspace selected. Choose one in the header.",
                icon="storage",
            )
            return

        list_res = await run.io_bound(self._svc.list_channels, ws)
        if not list_res.ok:
            error_banner(
                message=list_res.error or "Failed to load channels",
                on_retry=self._render_messages.refresh,
            )
            return

        channels = list_res.data or []
        eff_id = self._effective_channel_id(channels, self._filters["messages"])
        if eff_id is None:
            empty_state(
                message="No conversation channels. Create one on the Channels tab.",
                icon="chat",
            )
            return

        # Default to first channel when channel_id missing (most recently active first).
        if self._filters["messages"].get("channel_id") != str(eff_id):
            self._filters["messages"]["channel_id"] = str(eff_id)
            self._sync_url("messages")

        title_name = next(
            (str(c.get("name") or "") for c in channels if int(c["id"]) == eff_id),
            str(eff_id),
        )
        ui.label(f"Channel: {title_name} (id {eff_id})").classes("text-base font-medium mb-2")

        msg_res = await run.io_bound(self._svc.list_messages_all, ws, eff_id)
        if not msg_res.ok:
            error_banner(
                message=msg_res.error or "Failed to load messages",
                on_retry=self._render_messages.refresh,
            )
            return

        messages = msg_res.data or []
        if not messages:
            empty_state(message="No messages in this channel yet.", icon="chat_bubble_outline")
            return

        with ui.scroll_area().classes("w-full max-w-3xl").style("max-height: 70vh"):
            components.message_bubble_thread(messages)
