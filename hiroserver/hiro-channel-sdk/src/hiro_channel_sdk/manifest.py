"""An extension's package manifest, ``hiro-extension.toml``, and the grammar of an extension's key.

Every package the core installs carries one manifest at its top. The build kit writes it from the app's declaration
(``build-kit/package.py``), and the core reads it before it installs anything: the key, the core versions the package
works with, the port it asks for, the program its service runs, and the commands an upgrade runs.

The key is the extension's one name (README rule 6: rights, AI picks and asks are kept under it). It is ``name`` or
``publisher.name``; each part is lowercase letters, digits and dashes, starting with a letter. Where a system takes no
dot (a service account, an address's label) the dot becomes a dash (``dashed``): ``acme.weather`` is the account
``hiro-acme-weather`` and the address ``acme-weather.hiro.local``. Which keys a core accepts (a bare key only for
Hiro League's own extensions, no ``hiro*`` publisher) is the core's rule, on top of this grammar.

Usage::

    manifest = parse_manifest(Path("hiro-extension.toml").read_text(encoding="utf-8"))
    manifest.key, manifest.port, manifest.core     # "acme.weather", 8170, ">=0.2,<0.4"
    text = render_manifest(manifest)               # the same file again
"""

from __future__ import annotations

import json
import re
import tomllib
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

MANIFEST_FILE = "hiro-extension.toml"

KIND_APP = "app"
KIND_CHANNEL = "channel"

# Its service account is hiro-<key, dashed>, and an account's name on Linux stops at 32 characters (useradd)
KEY_MAX = 27
# A part ends with a letter or a digit, as an address's label must (the dashed key is the label of its address)
_PART = r"[a-z](?:[a-z0-9-]*[a-z0-9])?"
_KEY = re.compile(rf"{_PART}(?:\.{_PART})?")
# A version as the build writes it (PEP 440's release segment, with an optional pre-release or local part)
_VERSION = re.compile(r"\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?(?:\.dev\d+)?(?:\+[a-z0-9.]+)?")
# The core versions a package works with: one or more comma-separated clauses, e.g. ">=0.2,<0.4"
_CLAUSE = re.compile(r"(?:>=|<=|==|!=|~=|<|>)\s*\d+(?:\.\d+)*")


class ManifestError(ValueError):
    """A manifest the core can't use; the message is for people."""


def key_problem(key: str) -> str | None:
    """What is wrong with ``key`` as an extension's key, in words, or None when its grammar is right."""
    if not key:
        return "The key is empty."
    if len(key) > KEY_MAX:
        return f"The key {key!r} is longer than {KEY_MAX} characters."
    if not _KEY.fullmatch(key):
        return (
            f"The key {key!r} isn't name or publisher.name: each part lowercase letters, digits and dashes, starting "
            "with a letter and ending with a letter or a digit."
        )
    return None


def publisher(key: str) -> str | None:
    """``acme`` for ``acme.weather``; None for a bare key."""
    head, dot, _ = key.partition(".")
    return head if dot else None


def dashed(key: str) -> str:
    """The key where a system takes no dot: ``acme.weather`` → ``acme-weather`` (a bare key stays as it is)."""
    return key.replace(".", "-")


class Manifest(BaseModel):
    """The manifest's fields. ``port`` is an app's; a channel has none (the core starts a channel itself)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    kind: Literal["app", "channel"]
    title: str
    version: str
    core: str  # the core versions it works with, e.g. ">=0.2,<0.4"
    command: str  # the program its service runs (a console script of its package)
    port: int | None = None
    predeploy: str = ""  # the command an upgrade runs for its copy and trial, e.g. "python -m homehiro.predeploy"
    health: str = "/api/health"  # the path an upgrade asks once the new release runs

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        problem = key_problem(value)
        if problem:
            raise ValueError(problem)
        return value

    @field_validator("title", "command")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("can't be empty")
        return value.strip()

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        if not _VERSION.fullmatch(value):
            raise ValueError(f"{value!r} isn't a version such as 0.1.0")
        return value

    @field_validator("core")
    @classmethod
    def _core(cls, value: str) -> str:
        clauses = [c.strip() for c in value.split(",")]
        if not clauses or not all(_CLAUSE.fullmatch(c) for c in clauses):
            raise ValueError(f"{value!r} isn't a range of core versions such as >=0.2,<0.4")
        return ",".join(clauses)

    @field_validator("health")
    @classmethod
    def _health(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError(f"{value!r} isn't a path such as /api/health")
        return value

    @model_validator(mode="after")
    def _port_for_an_app(self) -> Manifest:
        if self.kind == KIND_APP and self.port is None:
            raise ValueError("an app's manifest names the port it asks for")
        if self.kind == KIND_CHANNEL and self.port is not None:
            raise ValueError("a channel has no port: the core starts it itself")
        if self.port is not None and not 1024 <= self.port <= 65535:
            raise ValueError(f"the port {self.port} isn't between 1024 and 65535")
        return self


def parse_manifest(text: str) -> Manifest:
    """The manifest in ``text``; raises ManifestError with words for people."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(f"{MANIFEST_FILE} isn't valid TOML: {exc}.") from exc
    try:
        return Manifest.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(_problem(e) for e in exc.errors())
        raise ManifestError(f"{MANIFEST_FILE} can't be used: {problems}.") from exc


def _problem(error: dict) -> str:
    """One validation error as people read it: the field, then what is wrong (pydantic's own wording trimmed)."""
    where = ".".join(str(p) for p in error["loc"]) or "manifest"
    if error["type"] == "extra_forbidden":
        return f"{where} isn't a field of the manifest"
    if error["type"] == "missing":
        return f"{where} is missing"
    return f"{where}: {error['msg'].removeprefix('Value error, ')}"


def render_manifest(manifest: Manifest) -> str:
    """The manifest as TOML, its fields in the model's order (a JSON string is a valid TOML basic string)."""
    lines = []
    for field, value in manifest.model_dump(exclude_none=True).items():
        lines.append(f"{field} = {value}" if isinstance(value, int) else f"{field} = {json.dumps(value)}")
    return "\n".join(lines) + "\n"
