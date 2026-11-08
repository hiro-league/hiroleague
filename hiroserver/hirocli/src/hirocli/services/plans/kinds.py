"""The command-line AI tools the core can ask on the owner's own plans (ported from HomeHiro's agents/tools.py).

One ``PlanKind`` per tool, in PLAN_KINDS, keyed by its catalog provider id (``claude_code`` / ``codex``):
how to ask it who is signed in, how it signs in and out, a short test question, and how an AI ask's
question and answer look. What each one prints was read from the real tools by HomeHiro (Claude Code
2.1.284–2.1.285, Codex 0.159.0–0.159.1, 2026-09-29/30); the parsers are pure, with tests. A new tool is
one more ``PlanKind``: nothing else branches on a tool's name.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import strict

TEST_QUESTION = "Reply with exactly: Hiro test OK."
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_VERSION = re.compile(r"\d+\.\d+\.\d+")
PICTURE = "picture.jpg"  # one picture; several are picture-1.jpg, picture-2.jpg…


def plain(text: str) -> str:
    """Without the colour codes the tools print."""
    return _ANSI.sub("", text)


def picture_names(n: int) -> list[str]:
    """The files a tool reads an ask's ``n`` pictures from, in order."""
    return [PICTURE] if n == 1 else [f"picture-{i}.jpg" for i in range(1, n + 1)]


def picture_note(names: list[str]) -> str:
    """The line telling a tool which files to read, after the question's words ("" without pictures)."""
    if not names:
        return ""
    if len(names) == 1:
        return f"\n\nThe picture is the file {names[0]} in this folder."
    return f"\n\nThe pictures are the files {', '.join(names[:-1])} and {names[-1]} in this folder, in that order: read each."


@dataclass(frozen=True)
class SignInStatus:
    signed_in: bool
    account: str | None = None  # the account's email, when the tool says it
    plan: str | None = None  # e.g. "Max"
    method: str | None = None  # how it signed in: "Claude account", "ChatGPT", "API key"


@dataclass(frozen=True)
class SignInText:
    """What a running sign-in has printed so far."""

    link: str | None = None  # the page to open
    code: str | None = None  # a code to type on that page (Codex); Claude instead shows one to paste back
    blocked: str | None = None  # why it can't go on, in the tool's words


@dataclass(frozen=True)
class TestAnswer:
    text: str
    model: str | None = None


@dataclass(frozen=True)
class Answered:
    """An AI ask's answer as the tool printed it."""

    text: str  # JSON text when a schema was given
    tokens_in: int  # all input, cache included (Codex says only a total: in 0, out 0)
    tokens_out: int
    tokens_total: int
    model: str  # the model that answered, as the tool names it
    cache_fresh: int = 0  # Claude: input tokens not from the cache, for the API-price estimate
    cache_read: int = 0
    cache_written: int = 0


class AnswerUnreadable(ValueError):
    """The tool ran but printed no answer the core can read."""


class PlanKind(ABC):
    id: str  # catalog provider id
    name: str
    program: str  # its command's name
    package: str  # its npm package (updates.py installs and updates it)
    home_var: str  # the environment variable that points the tool at its own folder
    takes_code: bool  # the sign-in waits for a code pasted back (Claude)
    status_args: tuple[str, ...]
    signin_args: tuple[str, ...]
    signout_args: tuple[str, ...]
    signin_days: int | None = None  # days a sign-in lasts however much it is used, when it ends by itself

    @staticmethod
    def version(out: str) -> str | None:
        m = _VERSION.search(out)
        return m.group(0) if m else None

    @abstractmethod
    def status(self, code: int, out: str, err: str) -> SignInStatus:
        """Who is signed in, from the status command's exit code and what it printed. ValueError when unreadable."""

    @abstractmethod
    def signin_text(self, out: str) -> SignInText:
        """The link, the code or the reason to stop, from what the sign-in printed so far."""

    @abstractmethod
    def test_args(self, question: str) -> tuple[str, ...]:
        """Ask one question, with no tools, connectors or saved session."""

    @abstractmethod
    def test_answer(self, out: str, err: str) -> TestAnswer:
        """The answer to the test question. Raises ValueError when there is none to read."""

    @abstractmethod
    def question(
        self, folder: Path, model: str, effort: str | None, prompt: str, pictures: list[str], schema: dict[str, Any] | None
    ) -> tuple[tuple[str, ...], str]:
        """An AI ask's arguments and the text for its input. ``pictures``: files written in ``folder``, in order."""

    @abstractmethod
    def answered(self, code: int, out: str, err: str, model: str, schema: dict[str, Any] | None) -> Answered:
        """The ask's answer from what the tool printed, held to ``schema``. AnswerUnreadable when there is none."""


class ClaudeCode(PlanKind):
    id, name, home_var, takes_code = "claude_code", "Claude Code", "CLAUDE_CONFIG_DIR", True
    program, package = "claude", "@anthropic-ai/claude-code"
    status_args = ("auth", "status")
    signin_args = ("auth", "login", "--claudeai")
    signout_args = ("auth", "logout")
    # HomeHiro's server sign-in of 2026-09-30 ended 30 days later to the minute ("OAuth session expired").
    signin_days = 30

    def status(self, code: int, out: str, err: str) -> SignInStatus:
        try:
            d = json.loads(out)  # JSON on stdout
        except ValueError:
            d = None
        if not isinstance(d, dict):
            raise ValueError(f"not the JSON `claude auth status` prints (exit code {code})")
        if not d.get("loggedIn"):
            return SignInStatus(False)
        method = {"claude.ai": "Claude account"}.get(str(d.get("authMethod")), "API key")
        plan = d.get("subscriptionType")
        return SignInStatus(True, d.get("email") or d.get("orgName"), str(plan).capitalize() if plan else None, method)

    def signin_text(self, out: str) -> SignInText:
        m = re.search(r"https://\S+/oauth/authorize\?\S+", plain(out))
        return SignInText(link=m.group(0) if m else None)

    def test_args(self, question: str) -> tuple[str, ...]:
        return ("-p", question, "--output-format", "json", "--tools", "", "--strict-mcp-config", "--no-session-persistence")

    def test_answer(self, out: str, err: str) -> TestAnswer:
        d = json.loads(out)  # ValueError when it isn't JSON
        if d.get("is_error") or not isinstance(d.get("result"), str):
            raise ValueError(str(d.get("result") or d.get("subtype") or "no answer"))
        models = list(d.get("modelUsage") or {})
        return TestAnswer(d["result"].strip(), models[0] if models else None)

    def question(
        self, folder: Path, model: str, effort: str | None, prompt: str, pictures: list[str], schema: dict[str, Any] | None
    ) -> tuple[tuple[str, ...], str]:
        args: list[str] = ["-p", "--model", model, "--output-format", "json"]
        if effort:
            args += ["--effort", effort]
        if schema is not None:
            args += ["--json-schema", json.dumps(schema)]
        # Only the Read tool, and only when there are pictures to read; no MCP servers, no saved session.
        args += ["--tools", "Read" if pictures else "", "--allowedTools", "Read", "--strict-mcp-config", "--no-session-persistence"]
        return tuple(args), prompt + picture_note(pictures)

    def answered(self, code: int, out: str, err: str, model: str, schema: dict[str, Any] | None) -> Answered:
        try:
            d = json.loads(out)
        except ValueError:
            raise AnswerUnreadable(f"Claude Code didn't answer (exit code {code}): {(err or out).strip()[-300:]}") from None
        if not isinstance(d, dict) or d.get("is_error"):
            said = d.get("result") if isinstance(d, dict) else None
            raise AnswerUnreadable(f"Claude Code: {str(said or 'no answer')[:300]}")
        answer = d.get("structured_output")
        text = json.dumps(answer, ensure_ascii=False) if answer is not None else str(d.get("result") or "")
        if not text.strip():
            raise AnswerUnreadable("Claude Code gave an empty answer")
        u = d.get("usage") or {}
        fresh, read, written = (int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        tokens_in, tokens_out = fresh + read + written, int(u.get("output_tokens") or 0)
        used = next(iter(d.get("modelUsage") or {}), model)
        return Answered(text, tokens_in, tokens_out, tokens_in + tokens_out, used, fresh, read, written)


class Codex(PlanKind):
    id, name, home_var, takes_code = "codex", "Codex", "CODEX_HOME", False
    program, package = "codex", "@openai/codex"
    status_args = ("login", "status")
    signin_args = ("login", "--device-auth")
    signout_args = ("logout",)

    def status(self, code: int, out: str, err: str) -> SignInStatus:
        text = plain(f"{out}\n{err}")  # `codex login status` says it on stderr (0.159.1, 2026-09-30)
        if code != 0 or "Logged in" not in text:
            return SignInStatus(False)
        return SignInStatus(True, method="API key" if "API key" in text else "ChatGPT")

    def signin_text(self, out: str) -> SignInText:
        text = plain(out)
        # ChatGPT accounts have device code sign-in off until it is turned on in their Security settings.
        blocked = next(
            (line.strip() for line in text.splitlines() if "device code" in line.lower() and "enable" in line.lower()), None
        )
        link = re.search(r"https://\S+", text)
        code = re.search(r"\b[A-Z0-9]{4}-[A-Z0-9]{4,6}\b", text)
        return SignInText(link.group(0) if link else None, code.group(0) if code else None, blocked)

    def test_args(self, question: str) -> tuple[str, ...]:
        return ("exec", "--skip-git-repo-check", "--sandbox", "read-only", "--ephemeral", question)

    def test_answer(self, out: str, err: str) -> TestAnswer:
        text = plain(out).strip()  # the final answer alone; the rest of the run goes to stderr
        if not text:
            raise ValueError("no answer")
        model = re.search(r"^model:\s*(\S+)", plain(err), re.MULTILINE)
        return TestAnswer(text, model.group(1) if model else None)

    def question(
        self, folder: Path, model: str, effort: str | None, prompt: str, pictures: list[str], schema: dict[str, Any] | None
    ) -> tuple[tuple[str, ...], str]:
        args: list[str] = ["exec", "--skip-git-repo-check", "--sandbox", "read-only", "--ephemeral", "-m", model]
        if effort:
            args += ["-c", f"model_reasoning_effort={effort}"]
        if schema is not None:
            # OpenAI's structured output wants every object closed, nested ones too (strict.py).
            (folder / "schema.json").write_text(json.dumps(strict.closed(schema)), encoding="utf-8")
            args += ["--output-schema", "schema.json"]
        for name in pictures:
            args += ["-i", name]
        args.append("-")  # "-": the prompt comes on the input
        return tuple(args), prompt

    def answered(self, code: int, out: str, err: str, model: str, schema: dict[str, Any] | None) -> Answered:
        text = plain(out).strip()
        if code != 0 or not text:
            said = " ".join(line.strip() for line in plain(err).splitlines() if "error" in line.lower())[-300:]
            raise AnswerUnreadable(f"Codex didn't answer (exit code {code}){': ' + said if said else ''}")
        tokens = re.search(r"tokens used\s*\n\s*([\d,]+)", plain(err))
        used = re.search(r"^model:\s*(\S+)", plain(err), re.MULTILINE)
        total = int(tokens.group(1).replace(",", "")) if tokens else 0
        answer = strict.opened(text, schema) if schema is not None else text
        return Answered(answer, 0, 0, total, used.group(1) if used else model)


PLAN_KINDS: dict[str, PlanKind] = {k.id: k for k in (ClaudeCode(), Codex())}
