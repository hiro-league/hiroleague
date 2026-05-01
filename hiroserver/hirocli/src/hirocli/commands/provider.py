"""Provider credential subcommands — workspace-scoped API keys and local endpoints."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from ..domain.available_models import AvailableModelsService
from ..domain.credential_store import CredentialStore
from ..domain.model_catalog import Provider, get_model_catalog
from ..domain.onboarding_defaults import (
    DefaultSuggestion,
    apply_onboarding_defaults_to_preferences,
    apply_suggested_defaults,
    compute_suggested_defaults,
)
from ..domain.preferences import load_preferences, save_preferences
from ..domain.workspace import WorkspaceError, resolve_workspace

logger = logging.getLogger(__name__)
from ..tools.provider import (
    AvailableModelsListTool,
    ProviderAddApiKeyTool,
    ProviderListConfiguredTool,
    ProviderRemoveTool,
)


def _mask_env_value(value: str, tail: int = 4) -> str:
    if len(value) <= tail + 3:
        return "***"
    return f"{value[:3]}...{value[-tail:]}"


def print_provider_summary_table(console: Console, *, workspace: str | None) -> None:
    """Print the same configured-provider table as ``hiro provider list``."""
    result = ProviderListConfiguredTool().execute(workspace=workspace)
    if not result.providers:
        console.print("[dim]No providers configured for this workspace.[/dim]")
        return
    table = Table(title=f"Configured providers — {result.workspace}")
    table.add_column("id", style="bold")
    table.add_column("display")
    table.add_column("hosting")
    table.add_column("auth")
    table.add_column("models")
    for p in result.providers:
        kinds = []
        if p.get("has_chat"):
            kinds.append("chat")
        if p.get("has_tts"):
            kinds.append("tts")
        if p.get("has_stt"):
            kinds.append("stt")
        kind_str = ", ".join(kinds) if kinds else "—"
        table.add_row(
            p["provider_id"],
            p["display_name"],
            p["hosting"],
            p["auth_method"],
            f"{p['available_model_count']} ({kind_str})",
        )
    console.print(table)


def discovered_env_keys_rows() -> list[tuple[Provider, str, str]]:
    """One row per catalog cloud provider: first credential env var that is set in the process.

    Avoids duplicate rows when a provider lists several env keys (e.g. GOOGLE_API_KEY and GEMINI_API_KEY).
    """
    cat = get_model_catalog()
    rows: list[tuple[Provider, str, str]] = []
    for prov in cat.list_providers():
        for env_name in prov.credential_env_keys:
            val = os.environ.get(env_name)
            if val:
                rows.append((prov, env_name, val))
                break
    return rows


def parse_index_selection(raw: str, upper: int) -> set[int] | None:
    """Parse 'all', 'none', or comma-separated 1-based indices. Returns None if invalid."""
    s = raw.strip().lower()
    if s in ("", "none", "n"):
        return set()
    if s in ("all", "a", "*"):
        return set(range(upper))
    out: set[int] = set()
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        try:
            i = int(part)
        except ValueError:
            return None
        if i < 1 or i > upper:
            return None
        out.add(i - 1)
    return out


def _print_default_suggestions_block(
    console: Console, suggestions: list[DefaultSuggestion],
) -> None:
    console.print("\n[bold]Suggested default models[/bold] (from catalog recommendations)")
    for s in suggestions:
        console.print(
            f"  [bold]{s.catalog_kind}[/bold]:  {s.model_id}  ({s.display_name})"
            f"  [dim]← {s.provider_display_name}[/dim]"
        )


def _pick_defaults_interactive(
    workspace_path: Path,
    workspace_id: str,
    console: Console,
    initial: list[DefaultSuggestion],
) -> list[DefaultSuggestion]:
    """Replace suggestions with user-picked models per kind (from available list)."""
    cat = get_model_catalog()
    store = CredentialStore(workspace_path, workspace_id)
    ams = AvailableModelsService(cat, store)
    picked: list[DefaultSuggestion] = []
    seen_kinds: set[str] = set()
    for s in initial:
        if s.catalog_kind in seen_kinds:
            continue
        seen_kinds.add(s.catalog_kind)
        models = ams.list_available_models(model_kind=s.catalog_kind)
        if not models:
            console.print(f"[yellow]No available {s.catalog_kind} models — skip.[/yellow]")
            continue
        console.print(f"\n[bold]{s.catalog_kind}[/bold] — pick a model (0 = skip)")
        for i, m in enumerate(models, start=1):
            mark = " *" if m.id == s.model_id else ""
            console.print(
                f"  [bold]{i}[/bold]  {m.id}  ({m.display_name}){mark}"
            )
        raw = Prompt.ask("Choice", default="1", console=console)
        try:
            num = int(raw.strip())
        except ValueError:
            console.print("[dim]Skipped.[/dim]")
            continue
        if num == 0:
            continue
        if num < 1 or num > len(models):
            console.print("[yellow]Out of range — skipped.[/yellow]")
            continue
        chosen = models[num - 1]
        prov = cat.get_provider(chosen.provider_id)
        picked.append(
            DefaultSuggestion(
                catalog_kind=s.catalog_kind,
                model_id=chosen.id,
                display_name=chosen.display_name,
                provider_id=chosen.provider_id,
                provider_display_name=prov.display_name if prov else chosen.provider_id,
            )
        )
    return picked


def run_onboarding_defaults_flow(
    workspace_path: Path,
    workspace_id: str,
    console: Console,
    *,
    provider_ids_ordered: list[str],
    interactive: bool,
) -> list[DefaultSuggestion]:
    """Compute catalog defaults, optionally prompt, apply to preferences, return what applied."""
    if not provider_ids_ordered:
        return []

    prefs = load_preferences(workspace_path)
    cat = get_model_catalog()
    store = CredentialStore(workspace_path, workspace_id)
    ams = AvailableModelsService(cat, store)
    suggestions = compute_suggested_defaults(
        provider_ids_ordered, cat, ams, prefs.llm,
    )
    if not suggestions:
        return []

    if interactive:
        _print_default_suggestions_block(console, suggestions)
        choice = Prompt.ask(
            "Accept these defaults?",
            default="Y",
            console=console,
        ).strip().lower()
        if choice in ("n", "no"):
            console.print("[dim]Skipped default model setup.[/dim]")
            return []
        if choice in ("p", "pick"):
            suggestions = _pick_defaults_interactive(
                workspace_path, workspace_id, console, suggestions,
            )
            if not suggestions:
                console.print("[dim]No defaults selected.[/dim]")
                return []

    applied = apply_suggested_defaults(prefs, suggestions)
    if applied:
        save_preferences(workspace_path, prefs)
        if not interactive:
            logger.info(
                "✅ Applied catalog default models — HiroServer · onboarding defaults · %s",
                ", ".join(f"{s.catalog_kind}={s.model_id}" for s in applied),
            )
        if interactive:
            console.print("\n[green]Default models (saved to preferences):[/green]")
            for s in applied:
                label = {"chat": "Chat", "tts": "TTS", "stt": "STT"}.get(
                    s.catalog_kind, s.catalog_kind,
                )
                extra = ""
                if s.catalog_kind == "chat" and prefs.llm.default_summarization == s.model_id:
                    extra = "  [dim](summarization same as chat)[/dim]"
                console.print(
                    f"  [bold]{label}[/bold]:  {s.model_id}  ({s.display_name}){extra}"
                )
    return applied


def run_onboarding_defaults_non_interactive(
    workspace_path: Path,
    workspace_id: str,
) -> list[DefaultSuggestion]:
    """Apply catalog defaults for empty preference slots; log at INFO. No console output."""
    store = CredentialStore(workspace_path, workspace_id)
    ordered = [m.provider_id for m in store.list_configured()]
    applied = apply_onboarding_defaults_to_preferences(
        workspace_path, workspace_id, ordered,
    )
    if applied:
        logger.info(
            "✅ Applied catalog default models — HiroServer · onboarding defaults · %s",
            ", ".join(f"{s.catalog_kind}={s.model_id}" for s in applied),
        )
    return applied


def interactive_credential_provisioning(
    workspace_path: Path,
    workspace_id: str,
    workspace_name: str,
    console: Console,
) -> int:
    """Interactive import from environment + manual API key entry; prints provider summary.

    Uses one ``CredentialStore`` for this flow. When ``hiro workspaces setup`` runs interactively,
    ``SetupTool`` skips ``import_detected_env_keys`` so the same keys are not imported twice.

    Returns the number of configured providers in the store after the flow.
    """
    store = CredentialStore(workspace_path, workspace_id)
    cat = get_model_catalog()
    session_order: list[str] = []

    discovered = discovered_env_keys_rows()
    if discovered and Confirm.ask(
        "Would you like to import API keys from your environment?",
        default=True,
        console=console,
    ):
        console.print(
            "[dim]Discovered keys (masked). Enter indices to import (e.g. 1,3), "
            "'all', or 'none':[/dim]"
        )
        for i, (prov, env_name, val) in enumerate(discovered, start=1):
            console.print(
                f"  [bold]{i}[/bold]  {prov.display_name} ({prov.id})  "
                f"{env_name} = {_mask_env_value(val)}"
            )
        choice = Prompt.ask(
            "Import which",
            default="all",
            console=console,
        )
        picked = parse_index_selection(choice, len(discovered))
        if picked is None:
            console.print("[yellow]Invalid selection — skipping env import.[/yellow]")
        else:
            for idx in sorted(picked):
                prov, _env_name, val = discovered[idx]
                if store.is_configured(prov.id):
                    console.print(f"[dim]Skip {prov.id} (already configured).[/dim]")
                    continue
                try:
                    store.set_api_key(prov.id, val)
                    session_order.append(prov.id)
                    console.print(f"[green]Imported[/green] API key for [bold]{prov.id}[/bold]")
                except RuntimeError as exc:
                    console.print(f"[red]Could not store key for {prov.id}: {exc}[/red]")

    while Confirm.ask(
        "Would you like to add an API key for another provider?",
        default=False,
        console=console,
    ):
        candidates = [
            p
            for p in cat.list_providers()
            if p.hosting == "cloud"
            and p.credential_env_keys
            and not store.is_configured(p.id)
        ]
        if not candidates:
            console.print("[dim]No unconfigured cloud providers left in the catalog.[/dim]")
            break
        console.print("[dim]Unconfigured cloud providers:[/dim]")
        for i, p in enumerate(candidates, start=1):
            console.print(f"  [bold]{i}[/bold]  {p.display_name} ({p.id})")
        raw = Prompt.ask("Choose provider number (or 0 to cancel)", console=console)
        try:
            num = int(raw.strip())
        except ValueError:
            console.print("[yellow]Invalid number.[/yellow]")
            continue
        if num == 0:
            break
        if num < 1 or num > len(candidates):
            console.print("[yellow]Out of range.[/yellow]")
            continue
        chosen = candidates[num - 1]
        key = Prompt.ask("API key", password=True, console=console)
        if not key.strip():
            console.print("[yellow]Empty key — skipped.[/yellow]")
            continue
        try:
            store.set_api_key(chosen.id, key.strip())
            session_order.append(chosen.id)
            console.print(f"[green]Stored[/green] API key for [bold]{chosen.id}[/bold]")
        except RuntimeError as exc:
            console.print(f"[red]Could not store key: {exc}[/red]")

    print_provider_summary_table(console, workspace=workspace_name)
    if session_order:
        run_onboarding_defaults_flow(
            workspace_path,
            workspace_id,
            console,
            provider_ids_ordered=session_order,
            interactive=True,
        )
    return len(store.list_configured())


def register(provider_app: typer.Typer, console: Console) -> None:
    """Register provider commands."""

    @provider_app.command("add")
    def provider_add(
        provider_id: str = typer.Argument(..., help="Catalog provider id, e.g. openai"),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name or id"
        ),
    ) -> None:
        """Store an API key for a provider (interactive password prompt)."""
        cat = get_model_catalog()
        if cat.get_provider(provider_id.strip()) is None:
            console.print(f"[red]Unknown provider id: {provider_id}[/red]")
            raise typer.Exit(1)
        key = Prompt.ask("API key", password=True, console=console)
        if not key.strip():
            console.print("[red]Empty key — aborted.[/red]")
            raise typer.Exit(1)
        try:
            result = ProviderAddApiKeyTool().execute(
                provider_id=provider_id,
                api_key=key,
                workspace=workspace,
            )
        except (WorkspaceError, ValueError, RuntimeError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        console.print(
            f"[green]Stored API key for[/green] [bold]{result.provider_id}[/bold] "
            f"in workspace [bold]{result.workspace}[/bold]."
        )
        try:
            entry, _ = resolve_workspace(workspace)
            run_onboarding_defaults_flow(
                Path(entry.path),
                entry.id,
                console,
                provider_ids_ordered=[result.provider_id.strip()],
                interactive=sys.stdin.isatty(),
            )
        except WorkspaceError:
            pass

    @provider_app.command("remove")
    def provider_remove(
        provider_id: str = typer.Argument(..., help="Catalog provider id"),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name or id"
        ),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    ) -> None:
        """Remove stored credentials for a provider."""
        if not yes and not Confirm.ask(
            f"Remove credentials for provider [bold]{provider_id}[/bold]?",
            default=False,
            console=console,
        ):
            console.print("Aborted.")
            raise typer.Exit(0)
        try:
            result = ProviderRemoveTool().execute(
                provider_id=provider_id, workspace=workspace
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        if result.removed:
            console.print(f"[green]Removed[/green] provider [bold]{provider_id}[/bold].")
        else:
            console.print(f"[yellow]No entry for[/yellow] {provider_id!r}.")

    @provider_app.command("list")
    def provider_list(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name or id"
        ),
    ) -> None:
        """List configured providers for the workspace."""
        try:
            print_provider_summary_table(console, workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

    @provider_app.command("scan-env")
    def provider_scan_env(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name or id"
        ),
        import_keys: bool = typer.Option(
            False,
            "--import-keys",
            help="Import detected keys into the credential store",
        ),
    ) -> None:
        """Show which catalog API keys are present in the environment."""
        cat = get_model_catalog()
        store: CredentialStore | None = None
        try:
            entry, _ = resolve_workspace(workspace)
            store = CredentialStore(Path(entry.path), entry.id)
        except WorkspaceError:
            pass

        table = Table(title="Environment vs catalog providers")
        table.add_column("provider")
        table.add_column("env keys")
        table.add_column("env")
        table.add_column("workspace")
        for p in cat.list_providers():
            if not p.credential_env_keys:
                continue
            found = [k for k in p.credential_env_keys if os.environ.get(k)]
            env_status = "[green]set[/green]" if found else "[dim]missing[/dim]"
            if store is None:
                ws_status = "[dim]—[/dim]"
            elif store.is_configured(p.id):
                ws_status = (
                    "[green]configured[/green]"
                    if found
                    else "[cyan]configured[/cyan]"
                )
            elif found:
                ws_status = "[yellow]env only[/yellow]"
            else:
                ws_status = "[dim]not configured[/dim]"
            table.add_row(p.id, ", ".join(p.credential_env_keys), env_status, ws_status)
        console.print(table)

        if import_keys:
            if store is None:
                try:
                    entry, _ = resolve_workspace(workspace)
                    store = CredentialStore(Path(entry.path), entry.id)
                except WorkspaceError as exc:
                    console.print(f"[red]{exc}[/red]")
                    raise typer.Exit(1)
            before_ids = {p.provider_id for p in store.list_configured()}
            n = store.import_detected_env_keys()
            console.print(f"[green]Imported[/green] {n} provider credential(s) from the environment.")
            new_ordered = [
                p.id
                for p in cat.list_providers()
                if p.id not in before_ids and store.is_configured(p.id)
            ]
            if new_ordered:
                try:
                    entry, _ = resolve_workspace(workspace)
                    run_onboarding_defaults_flow(
                        Path(entry.path),
                        entry.id,
                        console,
                        provider_ids_ordered=new_ordered,
                        interactive=sys.stdin.isatty(),
                    )
                except WorkspaceError:
                    pass

    @provider_app.command("suggest-defaults")
    def provider_suggest_defaults(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name or id"
        ),
    ) -> None:
        """Offer catalog default models for empty preference slots (any configured providers)."""
        try:
            entry, _ = resolve_workspace(workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        store = CredentialStore(Path(entry.path), entry.id)
        ordered = [m.provider_id for m in store.list_configured()]
        if not ordered:
            console.print("[dim]No providers configured — add keys first.[/dim]")
            raise typer.Exit(0)
        prefs = load_preferences(Path(entry.path))
        cat = get_model_catalog()
        ams = AvailableModelsService(cat, store)
        preview = compute_suggested_defaults(ordered, cat, ams, prefs.llm)
        if not preview:
            console.print(
                "[dim]Nothing to suggest — empty slots already filled or "
                "recommended models unavailable for this workspace.[/dim]"
            )
            raise typer.Exit(0)
        run_onboarding_defaults_flow(
            Path(entry.path),
            entry.id,
            console,
            provider_ids_ordered=ordered,
            interactive=sys.stdin.isatty(),
        )

    @provider_app.command("endpoint")
    def provider_endpoint(
        provider_id: str = typer.Argument(..., help="Catalog provider id (usually local, e.g. ollama)"),
        base_url: str = typer.Argument(..., help="Base URL, e.g. http://localhost:11434"),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name or id"
        ),
    ) -> None:
        """Set a local provider HTTP endpoint (no API key)."""
        try:
            entry, _ = resolve_workspace(workspace)
            store = CredentialStore(Path(entry.path), entry.id)
            store.set_local_endpoint(provider_id.strip(), base_url.strip())
        except (WorkspaceError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        console.print(
            f"[green]Set endpoint[/green] for [bold]{provider_id}[/bold] → {base_url.strip()}"
        )


def register_models_command(app: typer.Typer, console: Console) -> None:
    """Register top-level ``hiro models`` (available models in current workspace)."""

    @app.command("models")
    def models_command(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name or id"
        ),
        kind: Optional[str] = typer.Option(
            None, "--kind", "-k", help="model_kind filter"
        ),
        model_class: Optional[str] = typer.Option(
            None, "--class", "-c", help="model_class filter"
        ),
    ) -> None:
        """List models available in this workspace (configured providers only)."""
        try:
            result = AvailableModelsListTool().execute(
                workspace=workspace,
                model_kind=kind,
                model_class=model_class,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        if not result.models:
            console.print("[dim]No available models match the filter.[/dim]")
            return
        table = Table(title=f"Available models — {result.workspace}")
        table.add_column("id", style="bold")
        table.add_column("kind")
        table.add_column("class")
        table.add_column("display_name")
        for m in result.models:
            table.add_row(
                m["id"],
                m["model_kind"],
                m.get("model_class") or "—",
                m["display_name"],
            )
        console.print(table)
