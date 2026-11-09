"""``hiro voice …`` (Phase 7b): voice profiles, Gemini's voices, voice uses, the clip cache, and the
one-time import of HomeHiro's TTS profiles. Each command runs a voice Tool (tools/voice.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from hiro_commons.log import Logger
from rich.console import Console
from rich.table import Table

from ..domain.workspace import WorkspaceError

log = Logger.get("CLI.VOICE")

_WORKSPACE_HELP = "Workspace name (default: registry default)."


def register(voice_app: typer.Typer, console: Console) -> None:
    from ..services.voice import VoiceError

    @voice_app.command("profiles")
    def voice_profiles(
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """List the voice profiles and what uses each."""
        from ..tools.voice import VoiceProfilesListTool

        try:
            result = VoiceProfilesListTool().execute(workspace=workspace)
        except (WorkspaceError, VoiceError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        if not result.profiles:
            console.print("[dim]No voice profiles yet.[/dim]")
            return
        table = Table("Id", "Name", "Speaks with", "Used by")
        for p in result.profiles:
            gone = " [red](voice gone)[/red]" if p["voice_ok"] is False else ""
            table.add_row(p["id"], p["label"], p["line"] + gone, ", ".join(p["used_by"]) or "—")
        console.print(table)

    @voice_app.command("voices")
    def voice_voices(
        source: Optional[str] = typer.Option(None, "--source", help="studio, library or mine."),
        language: Optional[str] = typer.Option(None, "--language", help="A language code, e.g. ar-EG."),
        query: Optional[str] = typer.Option(None, "--q", help="Words to look for."),
        limit: int = typer.Option(30, "--limit"),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """List Gemini's voices (studio, library, ours)."""
        from ..tools.voice import VoiceVoicesTool

        try:
            result = VoiceVoicesTool().execute(source=source, language=language, q=query, limit=limit, workspace=workspace)
        except (WorkspaceError, VoiceError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        table = Table("Id", "Name", "Source", "Language", "Gender", "About")
        for v in result.voices:
            table.add_row(v["id"], v["name"], v["source"], v["language"] or "", v["gender"] or "", (v["description"] or "")[:60])
        console.print(table)
        console.print(f"[dim]{len(result.voices)} of {result.total}[/dim]")

    @voice_app.command("use")
    def voice_use(
        key: str = typer.Argument(..., help="'<extension>:<use id>', e.g. home:speak."),
        profile_id: Optional[str] = typer.Argument(None, help="The voice profile id; leave out to clear."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Point an extension's voice use at a voice profile."""
        from ..tools.voice import VoiceUsesSetTool

        try:
            result = VoiceUsesSetTool().execute(key=key, profile_id=profile_id, workspace=workspace)
        except (WorkspaceError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        console.print(f"{result.key} → {result.profile_id or 'no profile'}")

    @voice_app.command("clip-cache")
    def voice_clip_cache(
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """What the spoken-clip cache holds and saved."""
        from ..tools.voice import VoiceClipCacheTool

        try:
            r = VoiceClipCacheTool().execute(workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        console.print(
            f"{r.clips} clips, {r.bytes / 1024 / 1024:.1f} of {r.max_mb} MB · said again {r.hits} times, "
            f"saved ${r.saved_usd:.4f}"
        )

    @voice_app.command("import-homehiro")
    def voice_import_homehiro(
        db_path: Path = typer.Argument(..., help="A copy of HomeHiro's homehiro.db."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Only show what would be written."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help=_WORKSPACE_HELP),
    ) -> None:
        """Import HomeHiro's TTS profiles as voice profiles hh-<HomeHiro id> (once)."""
        from ..services.voice.import_homehiro import VoiceImportError
        from ..tools.voice import VoiceImportHomeHiroTool

        log.info("hiro voice import-homehiro", dry_run=dry_run)
        try:
            result = VoiceImportHomeHiroTool().execute(db_path=str(db_path), dry_run=dry_run, workspace=workspace)
        except (WorkspaceError, VoiceImportError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        verb = "Would write" if dry_run else "Wrote"
        console.print(f"[bold]{verb}[/bold] {len(result.profiles)} voice profiles:")
        for pid, f in result.profiles.items():
            console.print(f"  [bold]{pid}[/bold] {f['label']}: {f['model']} · {f['voice_label'] or f['voice']}")
        for note in result.notes:
            console.print(f"[yellow]note:[/yellow] {note}")
