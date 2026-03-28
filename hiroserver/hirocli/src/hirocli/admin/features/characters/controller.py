"""Characters page — cards, editor dialog, photo upload (guidelines §2.3)."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Callable
from functools import partial
from pathlib import Path

from nicegui import run, ui

from hirocli.admin.context import get_selected_workspace
from hirocli.admin.features.characters.components import character_avatar_thumbnail
from hirocli.admin.features.characters.service import CharacterService
from hirocli.admin.shared.ui.confirm_dialog import ConfirmDialogHandles, confirm_dialog
from hirocli.admin.shared.ui.empty_state import empty_state
from hirocli.admin.shared.ui.error_banner import error_banner
from hirocli.admin.shared.ui.loading_state import loading_state


class CharactersPageController:
    """List characters as cards; create/edit in a dialog; tools-only mutations."""

    def __init__(self) -> None:
        self._service = CharacterService()
        self._refresh_list: Callable[[], None] | None = None
        self._create_mode = True
        self._editing_character_id = ""
        self._pending_delete_id = ""
        self._editor_title: ui.label | None = None
        self._id_row: ui.row | None = None
        self._inp_id: ui.input | None = None
        self._inp_name: ui.input | None = None
        self._inp_description: ui.textarea | None = None
        self._inp_prompt: ui.textarea | None = None
        self._inp_backstory: ui.textarea | None = None
        self._inp_llm_json: ui.textarea | None = None
        self._inp_voice_json: ui.textarea | None = None
        self._inp_extras_json: ui.textarea | None = None
        self._chk_emotions: ui.checkbox | None = None
        self._editor_photo: ui.image | None = None
        self._delete_btn: ui.button | None = None
        self._upload_widget: ui.upload | None = None
        self._editor_dialog: ui.dialog | None = None
        self._delete_confirm: ConfirmDialogHandles | None = None

    def _refresh(self) -> None:
        if self._refresh_list:
            self._refresh_list()

    def _set_editor_photo(self, data_url: str | None) -> None:
        if self._editor_photo is None:
            return
        if data_url:
            self._editor_photo.source = data_url
            self._editor_photo.visible = True
        else:
            self._editor_photo.visible = False

    async def _open_create(self) -> None:
        self._create_mode = True
        self._editing_character_id = ""
        assert self._editor_title is not None
        assert self._id_row is not None
        assert self._inp_id is not None
        self._editor_title.set_text("New character")
        self._id_row.visible = True
        self._inp_id.value = ""
        self._inp_name.value = ""
        self._inp_description.value = ""
        self._inp_prompt.value = ""
        self._inp_backstory.value = ""
        self._inp_llm_json.value = ""
        self._inp_voice_json.value = ""
        self._inp_extras_json.value = ""
        assert self._chk_emotions is not None
        self._chk_emotions.value = False
        self._set_editor_photo(None)
        assert self._delete_btn is not None
        self._delete_btn.visible = False
        assert self._upload_widget is not None
        self._upload_widget.visible = False
        assert self._editor_dialog is not None
        self._editor_dialog.open()

    async def _open_edit(self, character_id: str) -> None:
        ws = get_selected_workspace()
        self._create_mode = False
        self._editing_character_id = character_id
        assert self._editor_title is not None
        assert self._id_row is not None
        assert self._inp_id is not None
        self._editor_title.set_text(f"Edit — {character_id}")
        self._id_row.visible = False
        self._inp_id.value = character_id

        res = await run.io_bound(self._service.get_character, ws, character_id)
        if not res.ok or not res.data:
            ui.notify(res.error or "Failed to load character", color="negative")
            return

        ch = res.data
        assert self._inp_name is not None
        self._inp_name.value = str(ch.get("name", ""))
        assert self._inp_description is not None
        self._inp_description.value = str(ch.get("description", ""))
        assert self._inp_prompt is not None
        self._inp_prompt.value = str(ch.get("prompt", ""))
        assert self._inp_backstory is not None
        self._inp_backstory.value = str(ch.get("backstory", ""))
        assert self._inp_llm_json is not None
        self._inp_llm_json.value = self._json_pretty(ch.get("llm_models"))
        assert self._inp_voice_json is not None
        self._inp_voice_json.value = self._json_pretty(ch.get("voice_models"))
        assert self._inp_extras_json is not None
        self._inp_extras_json.value = self._json_pretty(ch.get("extras"))
        assert self._chk_emotions is not None
        self._chk_emotions.value = bool(ch.get("emotions_enabled"))

        pres = await run.io_bound(
            self._service.character_detail_photo_data_url,
            ws,
            character_id,
        )
        self._set_editor_photo(pres.data if pres.ok else None)

        assert self._delete_btn is not None
        self._delete_btn.visible = not bool(ch.get("is_default"))
        assert self._upload_widget is not None
        self._upload_widget.visible = True
        assert self._editor_dialog is not None
        self._editor_dialog.open()

    @staticmethod
    def _json_pretty(value: object) -> str:
        import json

        if value is None:
            return ""
        try:
            return json.dumps(value, indent=2)
        except TypeError:
            return str(value)

    async def _save_character(self) -> None:
        ws = get_selected_workspace()
        assert self._inp_name is not None
        assert self._inp_description is not None
        assert self._inp_prompt is not None
        assert self._inp_backstory is not None
        assert self._inp_llm_json is not None
        assert self._inp_voice_json is not None
        assert self._inp_extras_json is not None
        assert self._chk_emotions is not None

        llm_raw = self._inp_llm_json.value or ""
        voice_raw = self._inp_voice_json.value or ""
        extras_raw = self._inp_extras_json.value or ""

        v1 = CharacterService.validate_optional_json_array("LLM models", llm_raw)
        if not v1.ok:
            ui.notify(v1.error or "Validation failed", color="negative")
            return
        v2 = CharacterService.validate_optional_json_array("Voice models", voice_raw)
        if not v2.ok:
            ui.notify(v2.error or "Validation failed", color="negative")
            return
        v3 = CharacterService.validate_optional_json_object("Extras", extras_raw)
        if not v3.ok:
            ui.notify(v3.error or "Validation failed", color="negative")
            return

        prompt_raw = self._inp_prompt.value
        prompt_for_create = None if not (prompt_raw or "").strip() else prompt_raw

        if self._create_mode:
            assert self._inp_id is not None
            cid = self._inp_id.value.strip()
            res = await run.io_bound(
                partial(
                    self._service.create_character,
                    ws,
                    character_id=cid,
                    name=self._inp_name.value.strip(),
                    description=self._inp_description.value,
                    prompt=prompt_for_create,
                    backstory=self._inp_backstory.value,
                    llm_models_json=llm_raw,
                    voice_models_json=voice_raw,
                    emotions_enabled=bool(self._chk_emotions.value),
                    extras_json=extras_raw,
                ),
            )
        else:
            res = await run.io_bound(
                partial(
                    self._service.update_character,
                    ws,
                    self._editing_character_id,
                    name=self._inp_name.value.strip(),
                    description=self._inp_description.value,
                    prompt=self._inp_prompt.value,
                    backstory=self._inp_backstory.value,
                    llm_models_json=llm_raw,
                    voice_models_json=voice_raw,
                    emotions_enabled=bool(self._chk_emotions.value),
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
        assert self._editor_dialog is not None
        self._editor_dialog.close()
        self._refresh()

    async def _on_upload_photo(self, e) -> None:
        ws = get_selected_workspace()
        cid = self._editing_character_id
        if not cid:
            ui.notify("Save the character before uploading a photo.", color="warning")
            return
        suffix = Path(e.name).suffix if getattr(e, "name", None) else ".png"
        if not suffix:
            suffix = ".png"
        data = e.content.read() if hasattr(e, "content") else b""
        if not data:
            ui.notify("Empty upload.", color="warning")
            return
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            res = await run.io_bound(self._service.upload_photo, ws, cid, tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        if not res.ok:
            ui.notify(res.error or "Upload failed", color="negative")
            return
        ui.notify(f"Photo updated ({res.data}).", color="positive")
        pres = await run.io_bound(
            self._service.character_detail_photo_data_url,
            ws,
            cid,
        )
        self._set_editor_photo(pres.data if pres.ok else None)
        self._refresh()

    async def _do_delete_confirmed(self) -> None:
        ws = get_selected_workspace()
        res = await run.io_bound(
            self._service.delete_character,
            ws,
            self._pending_delete_id,
        )
        if not res.ok:
            ui.notify(res.error or "Delete failed", color="negative")
            return False
        ui.notify("Character deleted.", color="positive")
        assert self._editor_dialog is not None
        self._editor_dialog.close()
        self._refresh()
        return None

    def _open_delete_confirm(self) -> None:
        cid = self._editing_character_id
        self._pending_delete_id = cid
        handles = self._delete_confirm
        assert handles is not None
        handles.title_label.set_text(f"Delete '{cid}'?")
        handles.dialog.open()

    async def mount(self) -> None:
        self._delete_confirm = confirm_dialog(
            title="Delete character?",
            message="This removes the character folder and index row.",
            confirm_label="Delete",
            confirm_icon="delete",
            on_confirm=self._do_delete_confirmed,
        )

        self._editor_dialog = ui.dialog()

        with self._editor_dialog, ui.card().classes("w-full max-w-3xl max-h-[90vh] overflow-y-auto"):
            self._editor_title = ui.label("").classes("text-lg font-semibold mb-2")
            self._editor_photo = ui.image("").classes("w-24 h-24 rounded object-cover mb-2")
            self._editor_photo.visible = False

            self._id_row = ui.row().classes("w-full items-center gap-2")
            with self._id_row:
                self._inp_id = ui.input(label="Character id").classes("flex-grow").props("dense outlined")

            self._inp_name = ui.input(label="Display name").classes("w-full").props("dense outlined")
            self._inp_description = ui.textarea(label="Description").classes("w-full").props("dense outlined rows=2")
            self._inp_prompt = ui.textarea(label="Prompt (system / persona)").classes("w-full").props(
                "dense outlined rows=6"
            )
            self._inp_backstory = ui.textarea(label="Backstory").classes("w-full").props(
                "dense outlined rows=4"
            )
            ui.label("Model / voice preferences (JSON arrays of string ids; leave empty for workspace defaults)").classes(
                "text-xs opacity-60"
            )
            self._inp_llm_json = ui.textarea(label="llm_models").classes("w-full font-mono text-sm").props(
                "dense outlined rows=3"
            )
            self._inp_voice_json = ui.textarea(label="voice_models").classes("w-full font-mono text-sm").props(
                "dense outlined rows=3"
            )
            self._inp_extras_json = ui.textarea(label="extras (JSON object)").classes("w-full font-mono text-sm").props(
                "dense outlined rows=3"
            )
            self._chk_emotions = ui.checkbox("Emotions enabled (reserved for future use)")

            self._upload_widget = ui.upload(
                label="Upload photo",
                auto_upload=True,
                on_upload=self._on_upload_photo,
            ).props("accept=image/* dense outlined").classes("w-full")
            self._upload_widget.visible = False

            with ui.row().classes("w-full justify-end gap-2 flex-wrap mt-4"):
                self._delete_btn = ui.button(
                    "Delete",
                    icon="delete",
                    on_click=self._open_delete_confirm,
                ).props("flat color=negative")
                self._delete_btn.visible = False
                ui.button("Cancel", on_click=self._editor_dialog.close).props("flat")
                ui.button("Save", icon="save", on_click=self._save_character).props("color=primary")

        @ui.refreshable
        async def character_cards() -> None:
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
                            on_retry=self._refresh,
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
                            with ui.card().classes("w-full max-w-sm"):
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
                                with ui.row().classes("justify-end gap-2 mt-3"):
                                    ui.button(
                                        "Edit",
                                        icon="edit",
                                        on_click=lambda c=cid: asyncio.create_task(self._open_edit(c)),
                                    ).props("flat dense size=sm")

        self._refresh_list = character_cards.refresh

        with ui.column().classes("w-full gap-6 p-6"):
            with ui.row().classes("w-full items-center justify-between gap-4"):
                ui.label("Characters").classes("text-2xl font-semibold")
                ui.button("New character", icon="add", on_click=self._open_create).props(
                    "color=primary"
                )
            await character_cards()
