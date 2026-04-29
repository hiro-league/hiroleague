"""Character subcommands — thin CLI over tools/character.py."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from hiro_commons.log import Logger
from rich.console import Console
from rich.table import Table

from ..domain.workspace import WorkspaceError
from ..tools.character import (
    CharacterCreateTool,
    CharacterDeleteTool,
    CharacterGetTool,
    CharacterListTool,
    CharacterUpdateTool,
    CharacterUploadPhotoTool,
)

log = Logger.get("CLI.CHARACTER")


def register(character_app: typer.Typer, console: Console) -> None:
    """Register character management commands."""

    @character_app.command("list")
    def character_list(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """List characters in the workspace."""
        try:
            result = CharacterListTool().execute(workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if not result.characters:
            console.print("[dim]No characters in the index.[/dim]")
            return

        table = Table(title="Characters", show_header=True)
        table.add_column("Id", style="bold")
        table.add_column("Name")
        table.add_column("Default")
        table.add_column("Photo")
        table.add_column("Description", max_width=40)

        for c in result.characters:
            err = c.get("error")
            desc = (c.get("description") or "")[:40]
            if err:
                desc = f"[red]{err}[/red]"
            table.add_row(
                c["id"],
                c.get("name") or "—",
                "yes" if c.get("is_default") else "",
                "yes" if c.get("has_photo") else "",
                desc or "—",
            )
        console.print(table)

    @character_app.command("get")
    def character_get(
        character_id: str = typer.Argument(..., help="Character id (slug)."),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """Show one character (including prompt and backstory)."""
        try:
            result = CharacterGetTool().execute(character_id=character_id, workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        except FileNotFoundError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        ch = result.character
        console.print(f"[bold]{ch['id']}[/bold] — {ch['name']}")
        console.print(f"  default:     {ch['is_default']}")
        console.print(f"  folder:      {ch['folder_path']}")
        console.print(f"  photo:       {ch.get('photo_filename') or '—'}")
        console.print(f"  description: {ch.get('description') or '—'}")
        console.print(f"  llm_models:  {ch.get('llm_models')}")
        console.print(f"  voice_models:{ch.get('voice_models')}")
        console.print(f"  emotions:    {ch.get('emotions_enabled')}")
        console.print("[dim]prompt[/dim]")
        console.print(ch.get("prompt") or "—")
        console.print("[dim]backstory[/dim]")
        console.print(ch.get("backstory") or "—")

    @character_app.command("create")
    def character_create(
        character_id: str = typer.Argument(..., help="New character id (slug)."),
        name: str = typer.Argument(..., help="Display name."),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
        description: Optional[str] = typer.Option(None, "--description", "-d"),
        prompt: Optional[str] = typer.Option(None, "--prompt", "-p", help="System prompt text."),
        backstory: Optional[str] = typer.Option(None, "--backstory", "-b"),
        llm_models_json: Optional[str] = typer.Option(
            None, "--llm-models-json", help='JSON array, e.g. ["openai:gpt-5.4"]',
        ),
        voice_models_json: Optional[str] = typer.Option(
            None, "--voice-models-json", help="JSON array of voice ids.",
        ),
        emotions: Optional[bool] = typer.Option(
            None, "--emotions/--no-emotions", help="Set emotions_enabled (default: false).",
        ),
        extras_json: Optional[str] = typer.Option(None, "--extras-json", help="JSON object."),
    ) -> None:
        """Create a new character."""
        log.info("hiro character create", character_id=character_id)
        try:
            result = CharacterCreateTool().execute(
                character_id=character_id,
                name=name,
                workspace=workspace,
                description=description,
                prompt=prompt,
                backstory=backstory,
                llm_models_json=llm_models_json,
                voice_models_json=voice_models_json,
                emotions_enabled=emotions,
                extras_json=extras_json,
            )
        except (WorkspaceError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        console.print(f"[green]Created character[/green] [bold]{result.character['id']}[/bold]")
        for w in result.warnings:
            console.print(f"[yellow]Warning: {w}[/yellow]")

    @character_app.command("update")
    def character_update(
        character_id: str = typer.Argument(..., help="Character id to update."),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
        name: Optional[str] = typer.Option(None, "--name", "-n"),
        description: Optional[str] = typer.Option(None, "--description", "-d"),
        prompt: Optional[str] = typer.Option(None, "--prompt", "-p"),
        backstory: Optional[str] = typer.Option(None, "--backstory", "-b"),
        llm_models_json: Optional[str] = typer.Option(None, "--llm-models-json"),
        voice_models_json: Optional[str] = typer.Option(None, "--voice-models-json"),
        emotions: Optional[bool] = typer.Option(
            None, "--emotions/--no-emotions", help="Set emotions_enabled.",
        ),
        extras_json: Optional[str] = typer.Option(None, "--extras-json"),
    ) -> None:
        """Update character fields (only options you pass are applied)."""
        if all(
            x is None
            for x in (
                name,
                description,
                prompt,
                backstory,
                llm_models_json,
                voice_models_json,
                emotions,
                extras_json,
            )
        ):
            console.print("[yellow]No fields to update; pass at least one option.[/yellow]")
            raise typer.Exit(1)

        try:
            result = CharacterUpdateTool().execute(
                character_id=character_id,
                workspace=workspace,
                name=name,
                description=description,
                prompt=prompt,
                backstory=backstory,
                llm_models_json=llm_models_json,
                voice_models_json=voice_models_json,
                emotions_enabled=emotions,
                extras_json=extras_json,
            )
        except (WorkspaceError, ValueError, FileNotFoundError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        console.print(f"[green]Updated character[/green] [bold]{result.character['id']}[/bold]")
        for w in result.warnings:
            console.print(f"[yellow]Warning: {w}[/yellow]")

    @character_app.command("delete")
    def character_delete(
        character_id: str = typer.Argument(..., help="Character id to delete."),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """Delete a character (not allowed for the default)."""
        log.info("hiro character delete", character_id=character_id)
        try:
            result = CharacterDeleteTool().execute(character_id=character_id, workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if result.deleted:
            console.print(f"[green]Deleted character[/green] [bold]{result.character_id}[/bold].")
        else:
            console.print(f"[yellow]Character not found:[/yellow] {result.character_id}")
            raise typer.Exit(1)

    @character_app.command("upload-photo")
    def character_upload_photo(
        character_id: str = typer.Argument(..., help="Character id."),
        photo_file: Path = typer.Argument(..., help="Path to image file.", exists=True),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """Copy an image into the character folder as photo.<ext>."""
        try:
            result = CharacterUploadPhotoTool().execute(
                character_id=character_id,
                photo_path=str(photo_file.resolve()),
                workspace=workspace,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        except FileNotFoundError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        console.print(
            f"[green]Photo updated[/green] for [bold]{result.character_id}[/bold] "
            f"→ {result.photo_filename}"
        )
