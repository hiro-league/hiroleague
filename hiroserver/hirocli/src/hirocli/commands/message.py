"""CLI: send synthetic user chat messages via the workspace Hiro server ``POST /invoke``."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from hirocli.domain.workspace import WorkspaceError, resolve_workspace
from hirocli.domain.workspace_server_client import post_invoke_sync


def register(app: typer.Typer, console: Console) -> None:
    """Register ``hiro message …``."""

    @app.command("send")
    def send(
        channel_id: Annotated[int, typer.Option("--channel", "-c", help="Conversation channel id.")],
        *,
        workspace: Annotated[
            Optional[str],
            typer.Option("--workspace", "-W", help="Workspace id or display name (default: registry default)."),
        ] = None,
        voice_reply: Annotated[bool, typer.Option("--voice-reply", "-V")] = False,
        text: Annotated[Optional[str], typer.Option("--text", "-t", help="Text body.")] = None,
        audio: Annotated[
            Optional[Path],
            typer.Option("--audio", "-a", help="Audio path on THIS machine (read by Hiro server process)."),
        ] = None,
        duration_ms: Annotated[
            Optional[int],
            typer.Option("--duration-ms", help="Recording length for --audio (ms). Required with --audio."),
        ] = None,
        mime_type: Annotated[
            Optional[str],
            typer.Option("--mime-type", help="MIME for --audio, e.g. audio/webm. Required with --audio."),
        ] = None,
    ) -> None:
        """Send a workspace-owner chat message; requires Hiro server running for this workspace."""

        try:
            entry, _ = resolve_workspace(workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc

        wp = Path(entry.path)
        params: dict[str, object] = {
            "channel_id": channel_id,
            "request_voice_reply": voice_reply,
            "workspace": entry.id,
        }

        use_text = bool(text and text.strip())
        audio_set = audio is not None
        if int(use_text) + int(audio_set) != 1:
            console.print("[red]Provide exactly one of --text or --audio.[/red]")
            raise typer.Exit(code=1)

        if audio_set:
            if duration_ms is None or duration_ms < 0:
                console.print("[red]--duration-ms is required with --audio (non-negative).[/red]")
                raise typer.Exit(code=1)
            if not mime_type or not mime_type.strip():
                console.print("[red]--mime-type is required with --audio (e.g. audio/webm).[/red]")
                raise typer.Exit(code=1)
            path = audio.expanduser().resolve()
            if not path.is_file():
                console.print(f"[red]Audio file not found:[/red] {path}")
                raise typer.Exit(code=1)
            params["audio_path"] = str(path)
            params["audio_mime_type"] = mime_type.strip()
            params["audio_duration_ms"] = int(duration_ms)
        else:
            params["text"] = text.strip()  # type: ignore[union-attr]

        try:
            out = post_invoke_sync(wp, "message_send", params)
        except Exception as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc

        console.print(
            f"[green]Sent[/green] message id [cyan]{out.get('message_id')}[/cyan] "
            f"→ channel [cyan]{out.get('channel_id')}[/cyan]",
        )

