"""Knowledge subcommands: markdown ingest and vector search.

NOTE: knowledge tools transitively import the langchain / sentence-transformers
/ torch stack (~10s cold). Each subcommand imports its tool inside the function
body so loading ``commands/knowledge.py`` (which happens on every ``hiro …``
invocation via ``commands/app.py``) stays cheap.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table


def _split_tags(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def register(knowledge_app: typer.Typer, console: Console) -> None:
    """Register knowledge commands."""

    @knowledge_app.command("scan")
    def scan(
        folder: Path = typer.Argument(..., help="Folder to scan for markdown files."),
        recursive: bool = typer.Option(True, "--recursive/--flat", help="Scan subfolders recursively."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help="Workspace to use."),
    ) -> None:
        """Scan a folder and show supported ingest candidates."""
        from ..tools.knowledge import KnowledgeScanFolderTool

        result = KnowledgeScanFolderTool().execute(
            folder=str(folder),
            recursive=recursive,
            workspace=workspace,
        )
        table = Table(title=f"Knowledge scan: {result.root}")
        table.add_column("file")
        table.add_column("ext")
        table.add_column("size", justify="right")
        table.add_column("state")
        for item in result.files:
            if item.supported:
                state = "indexed" if item.already_ingested else "ready"
            else:
                state = item.disabled_reason or "unsupported"
            table.add_row(item.relative_path, item.ext or "-", str(item.size_bytes), state)
        console.print(table)

    @knowledge_app.command("ingest")
    def ingest(
        paths: list[Path] = typer.Argument(..., help="Markdown files to ingest."),
        owner_kind: str = typer.Option("system", "--owner-kind", help="system, character, or user."),
        owner_id: str = typer.Option("0", "--owner-id", help="Owner id; use 0 for system."),
        category_id: Optional[int] = typer.Option(None, "--category-id", help="Knowledge category id."),
        subcategory_id: Optional[int] = typer.Option(None, "--subcategory-id", help="Knowledge subcategory id."),
        tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tags."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help="Workspace to use."),
    ) -> None:
        """Ingest markdown files and wait for completion."""
        from ..tools.knowledge import KnowledgeIngestTool

        result = KnowledgeIngestTool().execute(
            paths=[str(path) for path in paths],
            owner_kind=owner_kind,
            owner_id=owner_id,
            category_id=category_id,
            subcategory_id=subcategory_id,
            tags=_split_tags(tags),
            wait=True,
            workspace=workspace,
        )
        console.print(
            f"[bold]{result.status}[/bold] "
            f"ingested={result.totals.get('ingested', 0)} "
            f"skipped={result.totals.get('skipped', 0)} "
            f"failed={result.totals.get('failed', 0)} "
            f"chunks={result.totals.get('chunks', 0)}"
        )
        if result.errors:
            console.print_json(data=result.errors)

    @knowledge_app.command("job")
    def job(
        job_id: str = typer.Argument(..., help="Knowledge ingestion job id."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help="Workspace to use."),
    ) -> None:
        """Show one persisted ingestion job."""
        from ..tools.knowledge import KnowledgeJobStatusTool

        result = KnowledgeJobStatusTool().execute(job_id=job_id, workspace=workspace)
        console.print_json(
            data={
                "job_id": result.job_id,
                "status": result.status,
                "totals": result.totals,
                "errors": result.errors,
            }
        )

    @knowledge_app.command("search")
    def search(
        query: str = typer.Argument(..., help="Search query."),
        top_k: int = typer.Option(10, "--top-k", help="Maximum chunks to return."),
        min_score: float = typer.Option(0.0, "--min-score", help="Minimum vector score."),
        owner_kind: Optional[str] = typer.Option(None, "--owner-kind", help="Owner kind filter."),
        owner_id: Optional[str] = typer.Option(None, "--owner-id", help="Owner id filter."),
        document_id: Optional[str] = typer.Option(None, "--document-id", help="Document id filter."),
        tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tag filters."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help="Workspace to use."),
    ) -> None:
        """Search ingested knowledge chunks."""
        from ..tools.knowledge import KnowledgeSearchTool

        filters = {
            "owner_kind": owner_kind,
            "owner_id": owner_id,
            "document_id": document_id,
            "tags": _split_tags(tags),
        }
        result = KnowledgeSearchTool().execute(
            query=query,
            top_k=top_k,
            min_score=min_score,
            filters=filters,
            workspace=workspace,
        )
        table = Table(title=f"Knowledge search: {result.query}")
        table.add_column("score", justify="right")
        table.add_column("title")
        table.add_column("heading")
        table.add_column("text")
        for hit in result.hits:
            table.add_row(
                f"{hit.score:.3f}",
                hit.title,
                hit.heading_path or "-",
                hit.text.replace("\n", " ")[:160],
            )
        console.print(table)

    @knowledge_app.command("documents")
    def documents(
        status: Optional[str] = typer.Option(None, "--status", help="Document status filter."),
        owner_kind: Optional[str] = typer.Option(None, "--owner-kind", help="Owner kind filter."),
        owner_id: Optional[str] = typer.Option(None, "--owner-id", help="Owner id filter."),
        title: Optional[str] = typer.Option(None, "--title", help="Title substring filter."),
        limit: int = typer.Option(50, "--limit", help="Maximum rows."),
        workspace: Optional[str] = typer.Option(None, "--workspace", "-W", help="Workspace to use."),
    ) -> None:
        """List ingested knowledge documents."""
        from ..tools.knowledge import KnowledgeListDocumentsTool

        result = KnowledgeListDocumentsTool().execute(
            status=status,
            owner_kind=owner_kind,
            owner_id=owner_id,
            title=title,
            limit=limit,
            offset=0,
            workspace=workspace,
        )
        table = Table(title=f"Knowledge documents ({result.total})")
        table.add_column("title")
        table.add_column("owner")
        table.add_column("chunks", justify="right")
        table.add_column("status")
        table.add_column("source")
        for doc in result.documents:
            table.add_row(
                doc.title,
                f"{doc.owner_kind}/{doc.owner_id}",
                str(doc.chunk_count),
                doc.status,
                doc.source_uri,
            )
        console.print(table)
