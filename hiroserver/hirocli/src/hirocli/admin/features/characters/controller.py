"""Characters — tabbed browse + detail (view/edit), Cropper photo (guidelines §1.6, §2.3)."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import tempfile
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from nicegui import app, run, ui

from hirocli.admin.context import get_selected_workspace
from hirocli.admin.features.catalog.service import CatalogBrowserService
from hirocli.admin.features.characters.components import character_avatar_thumbnail, markdown_split_row
from hirocli.admin.features.characters.service import CharacterService
from hirocli.admin.features.characters.styles import register_character_admin_styles
from hirocli.admin.shared.tab_nav import TabNavRequest
from hirocli.admin.shared.ui.confirm_dialog import ConfirmDialogHandles, confirm_dialog
from hirocli.admin.shared.ui.empty_state import empty_state
from hirocli.admin.shared.ui.error_banner import error_banner
from hirocli.admin.shared.ui.loading_state import loading_state

TABS = ["browse", "detail"]
DEFAULT_TAB = "browse"
STORAGE_KEY = "characters.active_tab"
PAGE_PATH = "/characters"
_DETAIL_TAB_LABEL_MAX = 32


def _truncate_tab_label(text: str, max_len: int = _DETAIL_TAB_LABEL_MAX) -> str:
    t = (text or "").strip()
    if len(t) <= max_len:
        return t or "—"
    return t[: max_len - 1] + "…"


def _json_pretty(value: object) -> str:
    if value is None:
        return ""
    try:
        return json.dumps(value, indent=2)
    except TypeError:
        return str(value)


def _decode_data_url_png(data_url: str) -> bytes | None:
    if not data_url or not data_url.startswith("data:"):
        return None
    try:
        meta, b64 = data_url.split(",", 1)
    except ValueError:
        return None
    if "base64" not in meta:
        return None
    try:
        return base64.standard_b64decode(b64)
    except binascii.Error:
        return None


def _merged_voice_models_rows(
    tts: list[dict[str, Any]],
    stt: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in tts + stt:
        mid = row.get("id")
        if isinstance(mid, str) and mid not in by_id:
            by_id[mid] = row
    return list(by_id.values())


def _payload_str_field(p: dict[str, Any], key: str, mark_dirty: Any, e: Any) -> None:
    p[key] = e.value
    mark_dirty()


class CharactersPageController:
    """Browse (cards) + Detail (read-only view or edit) on one tabbed page."""

    def __init__(self, nav: TabNavRequest | None = None) -> None:
        self._nav = nav
        self._service = CharacterService()
        self._catalog = CatalogBrowserService()
        self._filters: dict[str, dict[str, Any]] = {t: {} for t in TABS}
        self._prev_tab = DEFAULT_TAB
        self._tabs_element: ui.tabs | None = None

        self._detail_character_id: str | None = None
        self._detail_mode: str = "view"
        self._detail_is_default: bool = False
        self._dirty = False
        self._view_character: dict[str, Any] | None = None
        self._photo_url: str | None = None
        self._photo_error: str | None = None
        self._edit_payload: dict[str, Any] = {}
        self._pending_delete_id = ""

        self._catalog_ready = False
        self._llm_select_options: dict[str, str] = {}
        self._voice_select_options: dict[str, str] = {}

        self._delete_confirm: ConfirmDialogHandles | None = None
        self._crop_dialog: ui.dialog | None = None
        self._crop_holder: ui.column | None = None
        self._detail_tab: Any = None  # ui.tab — set in mount()
        self._detail_tab_label = "Detail"

    def _init_tab_state(self) -> None:
        nav = self._nav
        initial = DEFAULT_TAB
        if nav and nav.tab in TABS:
            initial = nav.tab
        else:
            initial = app.storage.tab.get(STORAGE_KEY) or DEFAULT_TAB
        if initial not in TABS:
            initial = DEFAULT_TAB
        app.storage.tab[STORAGE_KEY] = initial

        if nav:
            for t in TABS:
                self._filters[t] = nav.filter_for(t)

        d = self._filters.get("detail", {})
        self._detail_character_id = d.get("character_id")
        # Browse landing: detail filters empty → view mode without id (coerced to browse tab; detail tab hidden).
        # New character uses tab=detail&mode=edit (no character_id).
        if not self._detail_character_id:
            m = d.get("mode")
            self._detail_mode = m if m in ("view", "edit") else "view"
        else:
            m = d.get("mode", "view")
            self._detail_mode = m if m in ("view", "edit") else "view"

        # Detail tab is hidden until a character is opened (or New character). A view URL with no id is empty.
        if (
            app.storage.tab.get(STORAGE_KEY) == "detail"
            and not self._detail_character_id
            and self._detail_mode == "view"
        ):
            app.storage.tab[STORAGE_KEY] = DEFAULT_TAB

        if app.storage.tab.get(STORAGE_KEY) == "detail":
            if self._detail_character_id:
                self._detail_tab_label = _truncate_tab_label(str(self._detail_character_id))
            elif self._detail_mode == "edit":
                self._detail_tab_label = "New character"
            else:
                self._detail_tab_label = "Detail"

    def _update_detail_tab_chrome(self) -> None:
        """Show the detail tab only while that panel is active; label shows character (or New character)."""
        el = self._detail_tab
        if el is None:
            return
        active = app.storage.tab.get(STORAGE_KEY)
        if active == "detail":
            el.set_visibility(True)
            el.set_label(_truncate_tab_label(self._detail_tab_label))
        else:
            el.set_visibility(False)

    async def _ensure_catalog_options(self) -> None:
        if self._catalog_ready:
            return
        chat = await run.io_bound(partial(self._catalog.list_models, model_kind="chat"))
        tts = await run.io_bound(partial(self._catalog.list_models, model_kind="tts"))
        stt = await run.io_bound(partial(self._catalog.list_models, model_kind="stt"))
        if chat.ok and chat.data:
            _, models = chat.data
            self._llm_select_options = {
                m["id"]: f"{m.get('display_name', m['id'])} ({m['id']})" for m in models if m.get("id")
            }
        tts_rows = tts.data[1] if tts.ok and tts.data else []
        stt_rows = stt.data[1] if stt.ok and stt.data else []
        merged = _merged_voice_models_rows(tts_rows, stt_rows)
        self._voice_select_options = {
            m["id"]: f"{m.get('display_name', m['id'])} ({m['id']})" for m in merged if m.get("id")
        }
        self._catalog_ready = True

    def _reset_edit_payload_new(self) -> None:
        self._edit_payload = {
            "new_id": "",
            "name": "",
            "description": "",
            "prompt": "",
            "backstory": "",
            "llm_models": [],
            "voice_models": [],
            "extras_json": "",
            "emotions_enabled": False,
        }

    def _reset_edit_payload_from_character(self, ch: dict[str, Any]) -> None:
        self._edit_payload = {
            "new_id": str(ch.get("id", "")),
            "name": str(ch.get("name", "")),
            "description": str(ch.get("description", "")),
            "prompt": str(ch.get("prompt", "")),
            "backstory": str(ch.get("backstory", "")),
            "llm_models": list(ch.get("llm_models") or []) if isinstance(ch.get("llm_models"), list) else [],
            "voice_models": list(ch.get("voice_models") or [])
            if isinstance(ch.get("voice_models"), list)
            else [],
            "extras_json": _json_pretty(ch.get("extras")),
            "emotions_enabled": bool(ch.get("emotions_enabled")),
        }

    def _sync_url(self, tab: str) -> None:
        params: dict[str, str] = {"tab": tab}
        if tab == "detail":
            params["mode"] = self._detail_mode
            if self._detail_character_id:
                params["character_id"] = self._detail_character_id
        query = urlencode(params)
        ui.run_javascript(f"history.replaceState(null, '', '{PAGE_PATH}?{query}')")

    def switch_to_tab(self, tab: str, **filters: Any) -> None:
        if tab not in TABS:
            return
        flt = dict(filters)
        tab_label_kw = flt.pop("tab_label", None)
        self._filters[tab] = {k: v for k, v in flt.items() if v is not None}
        if tab == "detail":
            self._detail_character_id = flt.get("character_id")
            if not self._detail_character_id:
                self._detail_is_default = False
                m = flt.get("mode")
                self._detail_mode = m if m in ("view", "edit") else "edit"
                self._reset_edit_payload_new()
                self._detail_tab_label = "New character"
            else:
                m = flt.get("mode", "view")
                self._detail_mode = m if m in ("view", "edit") else "view"
                if tab_label_kw is not None:
                    self._detail_tab_label = _truncate_tab_label(str(tab_label_kw))
                else:
                    self._detail_tab_label = _truncate_tab_label(str(self._detail_character_id))
        # Match tabbed_demo: drive tabs only via storage (bind_value). Do not set tabs.value — that can
        # emit a second on_value_change and double-call _on_tab_switch / _refresh_tab_panel, which
        # duplicates async refreshable content when opening Detail from Browse via View.
        prev_storage_tab = app.storage.tab.get(STORAGE_KEY)
        app.storage.tab[STORAGE_KEY] = tab
        self._update_detail_tab_chrome()
        # Same tab (e.g. already on Detail, switching character or New): storage write may not emit
        # on_value_change — refresh here so the panel updates once.
        same_tab = prev_storage_tab == tab
        if same_tab:
            self._refresh_tab_panel(tab)
        self._sync_url(tab)

    def _refresh_tab_panel(self, tab: str) -> None:
        if tab == "browse":
            self._render_browse.refresh()
        elif tab == "detail":
            self._render_detail.refresh()

    async def _on_tab_switch(self, e: Any) -> None:
        new_tab = getattr(e, "value", None) or (e.args if hasattr(e, "args") else None)
        if new_tab not in TABS:
            return
        old = self._prev_tab
        if old == "detail" and new_tab != "detail" and self._dirty:
            ok = await ui.run_javascript(
                "return confirm('Discard unsaved changes?');",
                timeout=30.0,
            )
            if not ok:
                if self._tabs_element is not None:
                    self._tabs_element.value = "detail"
                app.storage.tab[STORAGE_KEY] = "detail"
                return
        self._dirty = False
        self._prev_tab = new_tab
        self._refresh_tab_panel(new_tab)
        self._update_detail_tab_chrome()
        self._sync_url(new_tab)

    async def _load_detail_for_view(self, workspace_id: str | None) -> None:
        # Workspace captured by caller — avoid get_selected_workspace() after await (no UI context).
        ws = workspace_id
        cid = self._detail_character_id
        if not ws or not cid:
            self._view_character = None
            self._photo_url = None
            self._photo_error = None
            return
        res = await run.io_bound(self._service.get_character, ws, cid)
        if not res.ok or not res.data:
            self._view_character = None
            self._photo_url = None
            self._photo_error = res.error or "Failed to load character"
            return
        self._view_character = res.data
        self._detail_is_default = bool(res.data.get("is_default"))
        self._photo_error = None
        pres = await run.io_bound(self._service.character_detail_photo_data_url, ws, cid)
        if pres.ok:
            self._photo_url = pres.data
        else:
            self._photo_url = None
            self._photo_error = pres.error

    async def _load_detail_for_edit(self, workspace_id: str | None) -> None:
        ws = workspace_id
        cid = self._detail_character_id
        if not cid:
            self._reset_edit_payload_new()
            self._dirty = False
            return
        if not ws:
            return
        res = await run.io_bound(self._service.get_character, ws, cid)
        if res.ok and res.data:
            self._reset_edit_payload_from_character(res.data)
            self._detail_is_default = bool(res.data.get("is_default"))
        self._dirty = False

    async def _save_character(self) -> None:
        ws = get_selected_workspace()
        if not ws:
            ui.notify("No workspace selected.", color="negative")
            return
        extras_raw = str(self._edit_payload.get("extras_json", ""))
        v3 = CharacterService.validate_optional_json_object("Extras", extras_raw)
        if not v3.ok:
            ui.notify(v3.error or "Validation failed", color="negative")
            return
        llm_list = self._edit_payload.get("llm_models") or []
        voice_list = self._edit_payload.get("voice_models") or []
        llm_raw = json.dumps(llm_list) if llm_list else ""
        voice_raw = json.dumps(voice_list) if voice_list else ""
        v1 = CharacterService.validate_optional_json_array("LLM models", llm_raw)
        v2 = CharacterService.validate_optional_json_array("Voice models", voice_raw)
        if not v1.ok or not v2.ok:
            ui.notify((v1.error or v2.error) or "Validation failed", color="negative")
            return

        prompt_raw = str(self._edit_payload.get("prompt", ""))
        prompt_for_create = None if not prompt_raw.strip() else prompt_raw

        res: Any = None
        if not self._detail_character_id:
            cid = str(self._edit_payload.get("new_id", "")).strip()
            if not cid:
                ui.notify("Character id is required.", color="negative")
                return
            res = await run.io_bound(
                partial(
                    self._service.create_character,
                    ws,
                    character_id=cid,
                    name=str(self._edit_payload.get("name", "")).strip(),
                    description=str(self._edit_payload.get("description", "")),
                    prompt=prompt_for_create,
                    backstory=str(self._edit_payload.get("backstory", "")),
                    llm_models_json=llm_raw,
                    voice_models_json=voice_raw,
                    emotions_enabled=bool(self._edit_payload.get("emotions_enabled")),
                    extras_json=extras_raw,
                ),
            )
            if res.ok and res.data:
                self._detail_character_id = cid
        else:
            res = await run.io_bound(
                partial(
                    self._service.update_character,
                    ws,
                    self._detail_character_id,
                    name=str(self._edit_payload.get("name", "")).strip(),
                    description=str(self._edit_payload.get("description", "")),
                    prompt=prompt_raw,
                    backstory=str(self._edit_payload.get("backstory", "")),
                    llm_models_json=llm_raw,
                    voice_models_json=voice_raw,
                    emotions_enabled=bool(self._edit_payload.get("emotions_enabled")),
                    extras_json=extras_raw,
                ),
            )

        if not res.ok:
            ui.notify(res.error or "Save failed", color="negative")
            return
        if res.data is None:
            ui.notify("Save returned no data.", color="negative")
            return
        for w in res.data.warnings:
            ui.notify(w, color="warning")
        ui.notify("Character saved.", color="positive", timeout=2000)
        self._dirty = False
        self._detail_mode = "edit"
        cid = self._detail_character_id or ""
        self._detail_tab_label = _truncate_tab_label(
            str(self._edit_payload.get("name", "")).strip() or cid
        )
        self._update_detail_tab_chrome()
        self._sync_url("detail")
        await self._load_detail_for_edit(ws)
        self._render_detail.refresh()
        self._render_browse.refresh()

    def _enter_view_mode(self) -> None:
        self._detail_mode = "view"
        self._dirty = False
        cid = self._detail_character_id or ""
        ch = self._view_character
        if ch:
            self._detail_tab_label = _truncate_tab_label(str(ch.get("name") or "").strip() or cid)
        self._update_detail_tab_chrome()
        self._sync_url("detail")
        self._render_detail.refresh()

    async def _enter_edit_mode(self) -> None:
        self._detail_mode = "edit"
        ws = get_selected_workspace()
        await self._load_detail_for_edit(ws)
        await self._ensure_catalog_options()
        cid = self._detail_character_id or ""
        self._detail_tab_label = _truncate_tab_label(
            str(self._edit_payload.get("name", "")).strip() or cid or "New character"
        )
        self._update_detail_tab_chrome()
        self._sync_url("detail")
        self._render_detail.refresh()

    async def _cancel_edit(self) -> None:
        ws = get_selected_workspace()
        if self._dirty:
            ok = await ui.run_javascript(
                "return confirm('Discard unsaved changes?');",
                timeout=30.0,
            )
            if not ok:
                return
        if self._detail_character_id:
            self._detail_mode = "view"
            await self._load_detail_for_view(ws)
        else:
            self.switch_to_tab("browse")
            return
        self._dirty = False
        cid = self._detail_character_id or ""
        ch = self._view_character
        if ch:
            self._detail_tab_label = _truncate_tab_label(str(ch.get("name") or "").strip() or cid)
        self._update_detail_tab_chrome()
        self._sync_url("detail")
        self._render_detail.refresh()

    async def _do_delete_confirmed(self) -> None:
        ws = get_selected_workspace()
        res = await run.io_bound(self._service.delete_character, ws, self._pending_delete_id)
        if not res.ok:
            ui.notify(res.error or "Delete failed", color="negative")
            return False
        ui.notify("Character deleted.", color="positive")
        self.switch_to_tab("browse")
        return None

    def _open_delete_confirm(self) -> None:
        cid = self._detail_character_id or ""
        self._pending_delete_id = cid
        handles = self._delete_confirm
        assert handles is not None
        handles.title_label.set_text(f"Delete '{cid}'?")
        handles.dialog.open()

    async def _on_pick_photo(self, e: Any) -> None:
        ws = get_selected_workspace()
        cid = self._detail_character_id
        if not ws or not cid:
            ui.notify("Save the character before uploading a photo.", color="warning")
            return
        data = e.content.read() if hasattr(e, "content") else b""
        if not data:
            ui.notify("Empty file.", color="warning")
            return
        mime = "image/png"
        name = getattr(e, "name", "") or ""
        lower = name.lower()
        if lower.endswith((".jpg", ".jpeg")):
            mime = "image/jpeg"
        elif lower.endswith(".webp"):
            mime = "image/webp"
        elif lower.endswith(".gif"):
            mime = "image/gif"
        b64 = base64.standard_b64encode(data).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"
        await self._open_crop_dialog(data_url)

    async def _open_crop_dialog(self, image_data_url: str) -> None:
        assert self._crop_dialog is not None
        assert self._crop_holder is not None
        self._crop_holder.clear()
        with self._crop_holder:
            ui.label("Adjust square crop").classes("text-sm font-medium mb-2")
            ui.image(image_data_url).classes("hiro-char-crop-target max-w-full max-h-96 block mx-auto")
            with ui.row().classes("gap-2 justify-end mt-4 w-full"):
                ui.button("Cancel", on_click=self._crop_dialog.close).props("flat")
                ui.button(
                    "Upload",
                    icon="cloud_upload",
                    on_click=self._finalize_crop_upload,
                ).props("color=primary")
        self._crop_dialog.open()
        await asyncio.sleep(0.2)
        await ui.run_javascript(
            """
            if (window.__hiroCharCropper) {
                window.__hiroCharCropper.destroy();
                window.__hiroCharCropper = null;
            }
            const el = document.querySelector('img.hiro-char-crop-target');
            if (el && window.Cropper) {
                window.__hiroCharCropper = new Cropper(el, {
                    aspectRatio: 1,
                    viewMode: 1,
                    responsive: true,
                    autoCropArea: 0.9,
                });
            }
            """
        )

    async def _finalize_crop_upload(self) -> None:
        ws = get_selected_workspace()
        cid = self._detail_character_id
        if not ws or not cid:
            ui.notify("No character to upload to.", color="warning")
            return
        data_url = await ui.run_javascript(
            """
            if (!window.__hiroCharCropper) return null;
            const canvas = window.__hiroCharCropper.getCroppedCanvas({
                width: 512, height: 512, imageSmoothingQuality: 'high',
            });
            return canvas.toDataURL('image/png');
            """,
            timeout=60.0,
        )
        if not data_url or not isinstance(data_url, str):
            ui.notify("Cropper not ready.", color="warning")
            return
        raw = _decode_data_url_png(data_url)
        if not raw:
            ui.notify("Invalid image data.", color="negative")
            return
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        try:
            res = await run.io_bound(self._service.upload_photo, ws, cid, tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        if not res.ok:
            ui.notify(res.error or "Upload failed", color="negative")
            return
        ui.notify(f"Photo updated ({res.data}).", color="positive")
        await ui.run_javascript(
            """
            if (window.__hiroCharCropper) {
                window.__hiroCharCropper.destroy();
                window.__hiroCharCropper = null;
            }
            """
        )
        assert self._crop_dialog is not None
        self._crop_dialog.close()
        await self._load_detail_for_view(ws)
        self._render_detail.refresh()
        self._render_browse.refresh()

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _on_llm_select_change(self, e: Any) -> None:
        v = e.value
        if isinstance(v, (list, tuple)):
            self._edit_payload["llm_models"] = [str(x) for x in v]
        elif v is None:
            self._edit_payload["llm_models"] = []
        else:
            self._edit_payload["llm_models"] = [str(v)]
        self._mark_dirty()

    def _on_voice_select_change(self, e: Any) -> None:
        v = e.value
        if isinstance(v, (list, tuple)):
            self._edit_payload["voice_models"] = [str(x) for x in v]
        elif v is None:
            self._edit_payload["voice_models"] = []
        else:
            self._edit_payload["voice_models"] = [str(v)]
        self._mark_dirty()

    def _on_emotions_change(self, e: Any) -> None:
        self._edit_payload["emotions_enabled"] = bool(e.value)
        self._mark_dirty()

    @ui.refreshable
    async def _render_browse(self) -> None:
        ws_id = get_selected_workspace()
        if not ws_id:
            empty_state(
                message="No workspace selected. Choose one in the sidebar.",
                icon="storage",
            )
            return
        with ui.column().classes("w-full") as holder:
            with holder:
                loading_state(message="Loading characters…")
            result = await run.io_bound(self._service.list_characters_with_preview_images, ws_id)
            holder.clear()
            with holder:
                if not result.ok:
                    error_banner(
                        message=result.error or "Failed to load characters",
                        on_retry=self._render_browse.refresh,
                    )
                    return
                rows = result.data or []
                if not rows:
                    empty_state(
                        message="No characters yet. Create one with the button above.",
                        icon="face",
                    )
                    return
                with ui.row().classes("w-full gap-4 flex-wrap"):
                    for c in rows:
                        cid = c["id"]
                        tab_title = str(c.get("name") or cid).strip() or cid
                        with ui.card().classes(
                            "w-full max-w-sm cursor-pointer hover:shadow-md transition-shadow"
                        ) as card:
                            card.on(
                                "click",
                                lambda _, ch_id=cid, title=tab_title: self.switch_to_tab(
                                    "detail",
                                    character_id=ch_id,
                                    mode="view",
                                    tab_label=title,
                                ),
                            )
                            with card:
                                with ui.row().classes("items-start gap-3 no-wrap"):
                                    with ui.column().classes("shrink-0"):
                                        character_avatar_thumbnail(c.get("photo_data_url"))
                                    with ui.column().classes("min-w-0 flex-grow gap-1"):
                                        with ui.row().classes("items-center gap-2 flex-wrap"):
                                            ui.label(c.get("name") or cid).classes(
                                                "text-base font-semibold truncate"
                                            )
                                            if c.get("is_default"):
                                                ui.badge("default").props("color=primary outline")
                                        if c.get("error"):
                                            ui.label(str(c["error"])).classes("text-xs text-negative")
                                        else:
                                            desc = (c.get("description") or "").strip()
                                            ui.label(desc or "—").classes("text-sm opacity-70")

    @ui.refreshable
    async def _render_detail(self) -> None:
        ws = get_selected_workspace()
        if not ws:
            empty_state(message="No workspace selected.", icon="storage")
            return

        if not self._detail_character_id and self._detail_mode == "view":
            with ui.column().classes("gap-4 max-w-2xl"):
                ui.label("No character selected").classes("text-lg font-medium")
                ui.label("Pick a character from Browse or create a new one.").classes(
                    "text-sm opacity-70"
                )
                ui.button("Go to Browse", icon="grid_view", on_click=lambda: self.switch_to_tab("browse")).props(
                    "color=primary"
                )
            return

        if self._detail_mode == "view":
            await self._load_detail_for_view(ws)
            ch = self._view_character
            if not ch:
                error_banner(
                    message=self._photo_error or "Character not found.",
                    on_retry=self._render_detail.refresh,
                )
                return
            cid = self._detail_character_id or ""
            self._detail_tab_label = _truncate_tab_label(str(ch.get("name") or "").strip() or cid)
            self._update_detail_tab_chrome()
            with ui.column().classes("w-full gap-6 max-w-4xl"):
                with ui.row().classes("w-full items-center justify-between gap-4 flex-wrap"):
                    ui.label(ch.get("name") or cid).classes("text-2xl font-semibold")
                    with ui.row().classes("gap-2"):
                        ui.button(
                            "Edit",
                            icon="edit",
                            on_click=self._enter_edit_mode,
                        ).props("color=primary")
                        ui.button(
                            "Back to Browse",
                            icon="arrow_back",
                            on_click=lambda: self.switch_to_tab("browse"),
                        ).props("flat")
                with ui.row().classes("w-full gap-6 flex-wrap items-start"):
                    with ui.column().classes("gap-2 shrink-0"):
                        if self._photo_url:
                            ui.image(self._photo_url).classes(
                                "w-48 h-48 rounded object-cover border border-grey-4"
                            )
                        else:
                            character_avatar_thumbnail(None, size_class="w-48 h-48")
                        if self._photo_error:
                            ui.label(self._photo_error).classes("text-xs text-negative max-w-48")
                    with ui.column().classes("flex-grow gap-3 min-w-72"):
                        ui.label(f"Id: {cid}").classes("text-sm opacity-80")
                        desc = (ch.get("description") or "").strip() or "—"
                        ui.label("Description").classes("text-xs opacity-60")
                        ui.label(desc).classes("text-sm")
                        ui.label("Prompt").classes("text-xs opacity-60")
                        ui.markdown((ch.get("prompt") or "—").strip() or "—").classes("text-sm")
                        ui.label("Backstory").classes("text-xs opacity-60")
                        ui.markdown((ch.get("backstory") or "—").strip() or "—").classes("text-sm")
                        ui.label("LLM models").classes("text-xs opacity-60")
                        ui.label(_json_pretty(ch.get("llm_models")) or "—").classes(
                            "text-sm font-mono whitespace-pre-wrap"
                        )
                        ui.label("Voice models").classes("text-xs opacity-60")
                        ui.label(_json_pretty(ch.get("voice_models")) or "—").classes(
                            "text-sm font-mono whitespace-pre-wrap"
                        )
            return

        await self._ensure_catalog_options()
        if self._detail_character_id:
            await self._load_detail_for_edit(ws)
        else:
            self._reset_edit_payload_new()

        p = self._edit_payload
        if not self._detail_character_id:
            self._detail_tab_label = "New character"
        else:
            self._detail_tab_label = _truncate_tab_label(
                str(p.get("name", "")).strip() or (self._detail_character_id or "")
            )
        self._update_detail_tab_chrome()

        with ui.column().classes("w-full gap-6 max-w-5xl"):
            with ui.row().classes("w-full items-center justify-between gap-4 flex-wrap"):
                title = "New character" if not self._detail_character_id else f"Edit — {self._detail_character_id}"
                ui.label(title).classes("text-2xl font-semibold")
                with ui.row().classes("gap-2"):
                    if self._detail_character_id and not self._detail_is_default:
                        ui.button("Delete", icon="delete", on_click=self._open_delete_confirm).props(
                            "flat color=negative"
                        )
                    ui.button("Cancel", on_click=self._cancel_edit).props("flat")
                    ui.button("Save", icon="save", on_click=self._save_character).props("color=primary")

            if not self._detail_character_id:
                ni = (
                    ui.input(label="Character id", value=p.get("new_id", ""))
                    .classes("w-full max-w-md")
                    .props("outlined dense")
                )
                ni.on_value_change(lambda e: _payload_str_field(p, "new_id", self._mark_dirty, e))

            nm = ui.input(label="Display name", value=p.get("name", "")).classes("w-full").props("outlined dense")
            nm.on_value_change(lambda e: _payload_str_field(p, "name", self._mark_dirty, e))

            desc = ui.textarea(label="Description", value=p.get("description", "")).classes("w-full").props(
                "outlined rows=3"
            )
            desc.on_value_change(lambda e: _payload_str_field(p, "description", self._mark_dirty, e))

            ui.label("Prompt (markdown)").classes("text-sm font-medium mt-2")
            ta_p = markdown_split_row(label="", value=p.get("prompt", ""))
            ta_p.on_value_change(lambda e: _payload_str_field(p, "prompt", self._mark_dirty, e))

            ui.label("Backstory (markdown)").classes("text-sm font-medium mt-2")
            ta_b = markdown_split_row(label="", value=p.get("backstory", ""))
            ta_b.on_value_change(lambda e: _payload_str_field(p, "backstory", self._mark_dirty, e))

            llm_vals = [x for x in (p.get("llm_models") or []) if isinstance(x, str)]
            ui.select(
                label="LLM models",
                options=self._llm_select_options,
                multiple=True,
                value=llm_vals,
            ).classes("w-full").props("outlined dense use-chips").on_value_change(self._on_llm_select_change)

            voice_vals = [x for x in (p.get("voice_models") or []) if isinstance(x, str)]
            ui.select(
                label="Voice models (TTS/STT)",
                options=self._voice_select_options,
                multiple=True,
                value=voice_vals,
            ).classes("w-full").props("outlined dense use-chips").on_value_change(self._on_voice_select_change)

            extras = ui.textarea(label="extras (JSON object)", value=p.get("extras_json", "")).classes(
                "w-full font-mono text-sm"
            ).props("outlined rows=4")
            extras.on_value_change(lambda e: _payload_str_field(p, "extras_json", self._mark_dirty, e))

            emo = ui.checkbox("Emotions enabled (reserved)", value=p.get("emotions_enabled", False))
            emo.on_value_change(self._on_emotions_change)

            if self._detail_character_id:
                ui.upload(
                    label="Photo — choose image to crop (square)",
                    auto_upload=True,
                    on_upload=self._on_pick_photo,
                ).props("accept=image/* outlined dense").classes("w-full max-w-md")

    async def mount(self) -> None:
        await ui.context.client.connected()
        register_character_admin_styles()

        self._delete_confirm = confirm_dialog(
            title="Delete character?",
            message="This removes the character folder and index row.",
            confirm_label="Delete",
            confirm_icon="delete",
            on_confirm=self._do_delete_confirmed,
        )

        self._crop_dialog = ui.dialog()
        with self._crop_dialog:
            self._crop_holder = ui.column().classes("w-full min-w-80")

        self._init_tab_state()
        initial_tab = app.storage.tab[STORAGE_KEY]
        self._prev_tab = initial_tab

        with ui.column().classes("w-full gap-0 p-6"):
            with ui.row().classes("w-full items-center justify-between gap-4 mb-2"):
                ui.label("Characters").classes("text-2xl font-semibold")
                ui.button("New character", icon="add", on_click=lambda: self.switch_to_tab("detail", mode="edit")).props(
                    "color=primary"
                )

            with ui.tabs(value=initial_tab).bind_value(app.storage.tab, STORAGE_KEY) as tabs:
                self._tabs_element = tabs
                ui.tab("browse", label="Browse", icon="grid_view")
                self._detail_tab = ui.tab(
                    "detail",
                    label=_truncate_tab_label(self._detail_tab_label),
                    icon="person",
                )

            # Pass async handler directly — asyncio.create_task() runs outside NiceGUI's client slot and breaks .refresh().
            tabs.on_value_change(self._on_tab_switch)

            with ui.tab_panels(tabs, value=initial_tab).bind_value(app.storage.tab, STORAGE_KEY).classes("w-full"):
                with ui.tab_panel("browse"):
                    await self._render_browse()
                with ui.tab_panel("detail"):
                    await self._render_detail()

        self._update_detail_tab_chrome()
        self._sync_url(app.storage.tab[STORAGE_KEY])
