"""The table of the AI's log (Logs → LLM requests): only in apps that use llm/. An app that does imports this module in
its models.py, so the table is on its metadata and its migrations made it (NetHiro, HomeHiro; TrainHiro asks no AI)."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class LlmRequest(SQLModel, table=True):
    """One question sent to an LLM (Logs → LLM requests), whatever asked it: its words in labelled parts and exactly
    as sent, its pictures (DATA_DIR/llm-requests/<id>/<n>.jpg, kept fewer days than the row), the answer's schema,
    the reply as it came, each model asked (a fallback adds one), and what the app did with the answer
    (llm/recorder.py)."""

    id: str = Field(primary_key=True)  # uuid hex; also its pictures' folder
    at: datetime = Field(index=True)
    source: str  # what asked: "Ask a camera", "Ask now", "Write text", "Try it", "Other"
    task: str  # the question's or the automation's name
    link: str | None = None  # where it is in the app ("/streams")
    camera: str | None = None
    status: str  # "ok" | "fell back" | "failed"
    error: str | None = None
    provider: str | None = None  # who answered, or was asked last
    model: str | None = None
    profile: str | None = None
    detail: str | None = None  # how much of each picture the model reads
    thinking: str | None = None
    prompt: str = ""  # the words exactly as sent
    parts: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))  # {label, link, text}
    answer_schema: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    reply: str | None = None  # as it came
    outcome: str | None = None
    tries: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    pictures: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))  # {label, width, height, size}
    pictures_kept: bool = False  # their files are still there
    ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float | None = None  # USD; None on a plan or without a price
    warning: str | None = None
