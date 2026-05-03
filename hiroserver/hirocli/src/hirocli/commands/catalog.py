"""LLM catalog subcommands — thin CLI over tools/llm_catalog.py."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ..domain.model_catalog import get_model_catalog, reload_model_catalog
from ..tools.llm_catalog import (
    LlmCatalogGetModelTool,
    LlmCatalogListModelsTool,
    LlmCatalogListProvidersTool,
)


def register(catalog_app: typer.Typer, console: Console) -> None:
    """Register catalog browsing commands."""

    @catalog_app.command("providers")
    def catalog_providers(
        hosting: Optional[str] = typer.Option(
            None,
            "--hosting",
            help="Filter: cloud or local",
        ),
    ) -> None:
        """List providers from the bundled LLM catalog."""
        result = LlmCatalogListProvidersTool().execute(hosting=hosting)
        if not result.providers:
            console.print("[dim]No providers match the filter.[/dim]")
            return
        table = Table(title=f"LLM providers (catalog v{result.catalog_version})")
        table.add_column("id", style="bold")
        table.add_column("display_name")
        table.add_column("hosting")
        table.add_column("env keys")
        table.add_column("updated")
        for p in result.providers:
            keys = ", ".join(p.get("credential_env_keys") or []) or "—"
            table.add_row(
                p["id"],
                p["display_name"],
                p["hosting"],
                keys,
                p.get("metadata_updated_at", "—"),
            )
        console.print(table)

    @catalog_app.command("models")
    def catalog_models(
        provider: Optional[str] = typer.Option(
            None, "--provider", "-p", help="Filter by provider id"
        ),
        kind: Optional[str] = typer.Option(
            None, "--kind", "-k", help="chat, tts, stt, embedding, image_gen"
        ),
        model_class: Optional[str] = typer.Option(
            None, "--class", "-c", help="e.g. agentic, fast, balanced"
        ),
        hosting: Optional[str] = typer.Option(
            None, "--hosting", help="cloud or local"
        ),
    ) -> None:
        """List models from the bundled LLM catalog."""
        result = LlmCatalogListModelsTool().execute(
            provider_id=provider,
            model_kind=kind,
            model_class=model_class,
            hosting=hosting,
        )
        if not result.models:
            console.print("[dim]No models match the filter.[/dim]")
            return
        table = Table(title=f"LLM models (catalog v{result.catalog_version})")
        table.add_column("id", style="bold")
        table.add_column("kind")
        table.add_column("class")
        table.add_column("hosting")
        table.add_column("display_name")
        for m in result.models:
            table.add_row(
                m["id"],
                m["model_kind"],
                m.get("model_class") or "—",
                m.get("hosting") or "—",
                m["display_name"],
            )
        console.print(table)

    @catalog_app.command("model")
    def catalog_model(
        model_id: str = typer.Argument(..., help="Canonical id, e.g. openai:gpt-5.4"),
    ) -> None:
        """Show one model and its provider from the catalog."""
        try:
            result = LlmCatalogGetModelTool().execute(model_id=model_id)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        console.print(f"[bold]Catalog v{result.catalog_version}[/bold]")
        console.print("[bold]Model[/bold]")
        console.print_json(data=result.model)
        console.print("[bold]Provider[/bold]")
        console.print_json(data=result.provider)

    @catalog_app.command("reload")
    def catalog_reload() -> None:
        """Reload bundled catalog.yaml in this process (clears the in-memory cache)."""
        try:
            cat = reload_model_catalog()
        except Exception as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        n_prov = len(cat.list_providers())
        n_mod = len(cat.list_models())
        console.print(
            f"[bold]Catalog v{cat.catalog_version}[/bold] reloaded "
            f"({n_prov} providers, {n_mod} models)."
        )

    @catalog_app.command("env-keys")
    def catalog_env_keys(
        provider: Optional[str] = typer.Option(
            None, "--provider", "-p", help="Only keys for this provider id"
        ),
    ) -> None:
        """List credential env var names declared in the catalog (for setup checks)."""
        cat = get_model_catalog()
        keys = cat.list_credential_env_keys(
            provider_id=provider.strip() if provider else None
        )
        if not keys:
            console.print("[dim]No credential env keys for this filter.[/dim]")
            return
        for k in keys:
            console.print(k)
