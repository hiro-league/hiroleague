"""Workspace-scoped graph ledger file IO."""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Any, Iterable

from hiro_commons.log import Logger

from ....domain.model_catalog import get_model_catalog
from .context import current_run, current_substep
from .helpers import blank_zero_float, format_cost, preview, row_kind, slug, to_float
from .identity import resolve_ledger_identity
from .pricing import price_row
from .schema import GRAPH_LEDGER_COLUMNS, LEDGER_LOGGER_PREFIX, LedgerEntry, RunAccumulator

log = Logger.get("AGENT.GRAPH.LEDGER")


class LedgerSink:
    """Workspace-scoped writer for ``logs/graph.log``."""

    _open_lock = Lock()
    _opened: dict[Path, str] = {}
    _max_tracked_runs = 2048

    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = Path(workspace_path)
        self.path = self.workspace_path / "logs" / "graph.log"
        digest = hashlib.blake2s(str(self.path).encode("utf-8"), digest_size=4).hexdigest()
        self._module = f"{LEDGER_LOGGER_PREFIX}.{digest}"
        self._logger = Logger.get(self._module)
        self._lock = Lock()
        self._step_indexes: OrderedDict[str, int] = OrderedDict()
        self._attempt_indexes: OrderedDict[tuple[str, str], int] = OrderedDict()
        self._sub_step_indexes: OrderedDict[tuple[str, int], int] = OrderedDict()
        self._catalog: Any | None = None
        with self._open_lock:
            if self.path not in self._opened:
                Logger.add_file_sink(
                    str(self.path),
                    level="INFO",
                    use_csv=True,
                    csv_columns=GRAPH_LEDGER_COLUMNS,
                    include_prefix=self._module,
                )
                self._opened[self.path] = self._module

    @property
    def catalog(self) -> Any:
        if self._catalog is None:
            self._catalog = get_model_catalog()
        return self._catalog

    def next_step_index(self, run_id: str) -> int:
        key = run_id or ""
        with self._lock:
            self._touch_run(key)
            value = self._step_indexes.get(key, 0) + 1
            self._step_indexes[key] = value
            return value

    def next_sub_step(self, run_id: str, parent_step: int) -> int:
        run_key = run_id or ""
        key = (run_key, int(parent_step))
        with self._lock:
            self._touch_run(run_key)
            value = self._sub_step_indexes.get(key, 0) + 1
            self._sub_step_indexes[key] = value
            return value

    def next_node_attempt(self, run_id: str, node: str) -> int:
        run_key = run_id or ""
        key = (run_key, node or "")
        with self._lock:
            self._touch_run(run_key)
            value = self._attempt_indexes.get(key, 0) + 1
            self._attempt_indexes[key] = value
            return value

    def _touch_run(self, run_id: str) -> None:
        if run_id in self._step_indexes:
            self._step_indexes.move_to_end(run_id)
        else:
            self._step_indexes[run_id] = self._step_indexes.get(run_id, 0)
        while len(self._step_indexes) > self._max_tracked_runs:
            old_run_id, _ = self._step_indexes.popitem(last=False)
            for attempt_key in list(self._attempt_indexes):
                if attempt_key[0] == old_run_id:
                    self._attempt_indexes.pop(attempt_key, None)
            for sub_key in list(self._sub_step_indexes):
                if sub_key[0] == old_run_id:
                    self._sub_step_indexes.pop(sub_key, None)

    def open_entry(
        self,
        node: str,
        state: Any,
        config: Any = None,
        captures: frozenset[str] | None = None,
    ) -> LedgerEntry:
        identity = resolve_ledger_identity(state, config)
        run_id = str(identity.get("run_id") or "").strip()
        if not run_id:
            inbound_id = str(identity.get("inbound_id") or "")
            run_id = f"chat-{inbound_id}" if inbound_id else "chat-"
        parent_step = current_substep.get()
        if parent_step is not None:
            step_index: int = int(parent_step)
            sub_step: int | str = self.next_sub_step(run_id, parent_step)
        else:
            step_index = self.next_step_index(run_id)
            sub_step = ""
        return LedgerEntry(
            sink=self,
            node=node,
            run_id=run_id,
            step_index=step_index,
            sub_step=sub_step,
            node_attempt=self.next_node_attempt(run_id, node),
            captures=frozenset(captures or ()),
            branch_index=identity.get("branch_index"),
            inbound_id=str(identity.get("inbound_id") or ""),
            chat_channel_id=identity.get("chat_channel_id") or "",
            device_id=str(identity.get("device_id") or ""),
            user_id=str(identity.get("user_id") or ""),
            character_id=str(identity.get("character_id") or ""),
        )

    def write_rows(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            priced = price_row(row, self.catalog) if row_kind(row) == "node" else row
            accumulator = current_run.get()
            if accumulator is not None:
                accumulator.fold_row(priced)
            payload = {column: priced.get(column, "") for column in GRAPH_LEDGER_COLUMNS}
            self._logger.info("graph_ledger", **payload)

    def read_run_costs(self, run_ids: Iterable[str]) -> dict[str, float]:
        import csv

        wanted = {str(r) for r in run_ids if r}
        if not wanted or not self.path.exists():
            return {}
        out: dict[str, float] = {}
        try:
            with self.path.open(encoding="utf-8", errors="replace") as fh:
                for row in csv.DictReader(fh):
                    if row.get("row_kind") == "run" and row.get("run_id") in wanted:
                        out[str(row.get("run_id"))] = to_float(row.get("cost_usd"))
        except OSError:
            self._logger.warning("⚠️ ledger — read_run_costs failed · path=%s", self.path)
        return out

    def write_run_row(
        self,
        accumulator: RunAccumulator,
        *,
        status: str,
        error_code: str = "",
        decision_kind: str = "",
        decision_detail: str = "",
        input_preview: str = "",
        output_preview: str = "",
    ) -> None:
        self.write_rows(
            [
                {
                    "ts": time.time(),
                    "run_id": accumulator.run_id,
                    "step_index": "",
                    "sub_step": "",
                    "node": "@run",
                    "node_attempt": "",
                    "branch_index": "",
                    "status": slug(status),
                    "row_kind": "run",
                    "elapsed_ms": accumulator.elapsed_ms,
                    "inbound_id": accumulator.inbound_id,
                    "chat_channel_id": accumulator.chat_channel_id,
                    "device_id": accumulator.device_id,
                    "user_id": accumulator.user_id,
                    "character_id": accumulator.character_id,
                    "provider": accumulator.provider,
                    "model": accumulator.model,
                    "input_tokens": accumulator.input_tokens or "",
                    "output_tokens": accumulator.output_tokens or "",
                    "cached_input_tokens": accumulator.cached_input_tokens or "",
                    "reasoning_tokens": accumulator.reasoning_tokens or "",
                    "tts_chars": accumulator.tts_chars or "",
                    "tts_text_tokens": accumulator.tts_text_tokens or "",
                    "tts_audio_tokens": accumulator.tts_audio_tokens or "",
                    "stt_audio_seconds": blank_zero_float(accumulator.stt_audio_seconds),
                    "stt_audio_tokens": accumulator.stt_audio_tokens or "",
                    "tts_audio_seconds": blank_zero_float(accumulator.tts_audio_seconds),
                    "cost_usd": format_cost(accumulator.cost_usd)
                    if accumulator.cost_usd
                    else "",
                    "pricing_version": accumulator.pricing_version,
                    "decision_kind": slug(decision_kind or status),
                    "decision_detail": slug(decision_detail),
                    "input_preview": preview(input_preview),
                    "output_preview": preview(output_preview),
                    "error_code": slug(error_code),
                }
            ]
        )

    def evict_run(self, run_id: str) -> None:
        key = run_id or ""
        with self._lock:
            self._step_indexes.pop(key, None)
            for attempt_key in list(self._attempt_indexes):
                if attempt_key[0] == key:
                    self._attempt_indexes.pop(attempt_key, None)
            for sub_key in list(self._sub_step_indexes):
                if sub_key[0] == key:
                    self._sub_step_indexes.pop(sub_key, None)
