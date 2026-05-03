"""
Inspect a newline-separated list of relative paths and emit a Markdown report.

Used to validate embeddable/code indexes: binaries and suspicious text are flagged.
"""

from __future__ import annotations

import argparse
import logging
import mimetypes
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# --- Tunables ---------------------------------------------------------------

DEFAULT_BASE = Path("d:/projects")

# Extensions we treat as binary without reading content (index lists shouldn't contain these).
BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".bmp",
        ".tif",
        ".tiff",
        ".svgz",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".pdf",
        ".zip",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".mp3",
        ".mp4",
        ".wav",
        ".avi",
        ".mov",
        ".mkv",
        ".sqlite",
        ".db",
        ".bin",
        ".dat",
        ".pak",
        ".wasm",
    }
)

SNIFF_BYTES = 65536
MAX_READ_BYTES = 50 * 1024 * 1024

# Lines longer than this (characters, excluding newline) are treated as likely minified bundles.
LONG_LINE_CHAR_THRESHOLD = 8192

# Prose / docs: we do not compute "excluding comments" (not meaningful the same way as for code).
TEXT_LIKE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".md",
        ".mdx",
        ".txt",
        ".markdown",
        ".rst",
        ".adoc",
        ".csv",
        ".json",
        ".xml",
        ".svg",
    }
)

HASH_COMMENT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".pyi",
        ".pyw",
        ".toml",
        ".yaml",
        ".yml",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".ini",
        ".cfg",
        ".properties",
        ".rb",
        ".rake",
        ".ps1",
        ".psm1",
    }
)

CLIKE_COMMENT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".dart",
        ".css",
        ".scss",
        ".less",
        ".java",
        ".kt",
        ".kts",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cc",
        ".cxx",
        ".hh",
        ".rs",
        ".go",
        ".swift",
        ".cs",
        ".vue",
        ".svelte",
        ".astro",
    }
)

HTML_COMMENT_EXTENSIONS: frozenset[str] = frozenset({".html", ".htm"})

SQL_COMMENT_EXTENSIONS: frozenset[str] = frozenset({".sql"})

# Python's stdlib maps `.ts` to MPEG TS video — force sane labels for web/code extensions.
FILETYPE_BY_EXTENSION: dict[str, str] = {
    ".ts": "text/typescript",
    ".tsx": "text/typescript+react",
    ".mts": "text/typescript",
    ".cts": "text/typescript",
    ".js": "text/javascript",
    ".jsx": "text/javascript+react",
    ".mjs": "text/javascript",
    ".cjs": "text/javascript",
    ".dart": "text/x-dart",
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexRow:
    rel_display: str
    filename: str
    extension: str
    filetype: str
    size_bytes: int
    lines: int
    lines_nonempty: int
    # None for prose / unknown: not shown as a code-only comment metric.
    lines_exc_comments: int | None


@dataclass(frozen=True)
class FlagRow:
    rel_display: str
    filename: str
    reason: str


@dataclass(frozen=True)
class ExtensionRollup:
    extension: str
    file_count: int
    type_label: str
    lines: int
    lines_nonempty: int
    lines_exc_comments: int | None
    size_bytes: int


@dataclass(frozen=True)
class RootRollup:
    root: str
    file_count: int
    lines: int
    lines_nonempty: int
    lines_exc_comments: int | None
    size_bytes: int


_C_BLOCK_COMMENT_RE = re.compile(r"/\*[\s\S]*?\*/")
_HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _fmt_int(n: int) -> str:
    """Thousands separators only — never K/M abbreviations."""
    return f"{n:,}"


def _fmt_kb_approx(size_bytes: int) -> str:
    """Nearest KiB with comma grouping (editor-facing approximation)."""
    if size_bytes <= 0:
        return "0 KB"
    kb = (size_bytes + 512) // 1024
    if kb == 0:
        return "<1 KB"
    return f"{kb:,} KB"


def _fmt_exc_cell(val: int | None) -> str:
    return "—" if val is None else _fmt_int(val)


def _filetype_label(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in FILETYPE_BY_EXTENSION:
        return FILETYPE_BY_EXTENSION[suffix]
    mime, _encoding = mimetypes.guess_type(path.name)
    if mime:
        return mime
    return suffix if suffix else "(no extension)"


def _sniff_binary_nul(sample: bytes) -> bool:
    return b"\x00" in sample


def _strip_hash_comment_line(line: str) -> str:
    """Drop `# ...` tails outside simple '...' and \"...\" spans (heuristic; not a full lexer)."""
    i = 0
    n = len(line)
    in_single = False
    in_double = False
    escape = False
    while i < n:
        ch = line[i]
        if escape:
            escape = False
            i += 1
            continue
        if ch == "\\" and (in_single or in_double):
            escape = True
            i += 1
            continue
        if not in_double and ch == "'":
            in_single = not in_single
            i += 1
            continue
        if not in_single and ch == '"':
            in_double = not in_double
            i += 1
            continue
        if not in_single and not in_double and ch == "#":
            return line[:i]
        i += 1
    return line


def _strip_two_slash_comment_line(line: str, marker: tuple[str, str]) -> str:
    """Drop `//` or `--`-style tails outside simple quoted spans."""
    m0, m1 = marker
    i = 0
    n = len(line)
    in_single = False
    in_double = False
    escape = False
    while i < n - 1:
        ch = line[i]
        nxt = line[i + 1]
        if escape:
            escape = False
            i += 1
            continue
        if ch == "\\" and (in_single or in_double):
            escape = True
            i += 1
            continue
        if not in_double and ch == "'":
            in_single = not in_single
            i += 1
            continue
        if not in_single and ch == '"':
            in_double = not in_double
            i += 1
            continue
        if not in_single and not in_double and ch == m0 and nxt == m1:
            return line[:i]
        i += 1
    return line


def _count_nonempty_after_hash_comments(text: str) -> int:
    total = 0
    for raw_line in text.splitlines():
        if _strip_hash_comment_line(raw_line).strip():
            total += 1
    return total


def _count_nonempty_after_clike_comments(text: str) -> int:
    stripped_blocks = _C_BLOCK_COMMENT_RE.sub("", text)
    total = 0
    for raw_line in stripped_blocks.splitlines():
        if _strip_two_slash_comment_line(raw_line, ("/", "/")).strip():
            total += 1
    return total


def _count_nonempty_after_html_comments(text: str) -> int:
    stripped = _HTML_COMMENT_RE.sub("", text)
    return sum(1 for raw_line in stripped.splitlines() if raw_line.strip())


def _count_nonempty_after_sql_comments(text: str) -> int:
    stripped_blocks = _C_BLOCK_COMMENT_RE.sub("", text)
    total = 0
    for raw_line in stripped_blocks.splitlines():
        if _strip_two_slash_comment_line(raw_line, ("-", "-")).strip():
            total += 1
    return total


def _approx_lines_exc_comments(text: str, extension: str) -> int | None:
    """
    Approximate lines that still contain non-comment payload after stripping.
    None when we intentionally skip comment stripping for prose/markup buckets.
    """
    ext = extension.lower()
    if ext in TEXT_LIKE_EXTENSIONS or ext == "(none)":
        return None
    if ext in HASH_COMMENT_EXTENSIONS:
        return _count_nonempty_after_hash_comments(text)
    if ext in CLIKE_COMMENT_EXTENSIONS:
        return _count_nonempty_after_clike_comments(text)
    if ext in HTML_COMMENT_EXTENSIONS:
        return _count_nonempty_after_html_comments(text)
    if ext in SQL_COMMENT_EXTENSIONS:
        return _count_nonempty_after_sql_comments(text)
    return _count_nonempty_after_clike_comments(text)


def _utf8_content_metrics(
    content: bytes, extension_normalized: str
) -> tuple[int, int, int, int | None]:
    """Returns (physical_lines, max_physical_line_chars, nonempty_lines, lines_exc_comments_or_none)."""
    text = content.decode("utf-8")
    split = text.splitlines()
    line_count = len(split)
    max_chars = max((len(line) for line in split), default=0)
    nonempty = sum(1 for line in split if line.strip())
    exc = _approx_lines_exc_comments(text, extension_normalized)
    return line_count, max_chars, nonempty, exc


def _rollup_exc_comment_sum(rows: list[IndexRow]) -> int | None:
    vals = [row.lines_exc_comments for row in rows if row.lines_exc_comments is not None]
    if not vals:
        return None
    return sum(vals)


def _top_level_root(rel_display: str) -> str:
    normalized = rel_display.replace("\\", "/").strip().strip("/")
    if not normalized:
        return "(unknown)"
    return normalized.split("/", 1)[0]


def _aggregate_type_label(types: set[str]) -> str:
    """Single MIME/extension label for an extension bucket, or a compact mixed summary."""
    if not types:
        return "(unknown)"
    if len(types) == 1:
        return next(iter(types))
    sorted_types = sorted(types)
    if len(sorted_types) <= 5:
        return "mixed: " + "; ".join(sorted_types)
    return f"mixed ({len(sorted_types)} distinct types)"


def _aggregate_by_extension(rows: list[IndexRow]) -> list[ExtensionRollup]:
    lines_by_ext: dict[str, int] = defaultdict(int)
    nonempty_by_ext: dict[str, int] = defaultdict(int)
    size_by_ext: dict[str, int] = defaultdict(int)
    count_by_ext: dict[str, int] = defaultdict(int)
    types_by_ext: dict[str, set[str]] = defaultdict(set)
    bucket_rows: dict[str, list[IndexRow]] = defaultdict(list)

    for row in rows:
        ext = row.extension
        count_by_ext[ext] += 1
        lines_by_ext[ext] += row.lines
        nonempty_by_ext[ext] += row.lines_nonempty
        size_by_ext[ext] += row.size_bytes
        types_by_ext[ext].add(row.filetype)
        bucket_rows[ext].append(row)

    result: list[ExtensionRollup] = []
    for ext, lines_total in lines_by_ext.items():
        result.append(
            ExtensionRollup(
                extension=ext,
                file_count=count_by_ext[ext],
                type_label=_aggregate_type_label(types_by_ext[ext]),
                lines=lines_total,
                lines_nonempty=nonempty_by_ext[ext],
                lines_exc_comments=_rollup_exc_comment_sum(bucket_rows[ext]),
                size_bytes=size_by_ext[ext],
            )
        )

    result.sort(key=lambda item: item.lines, reverse=True)
    return result


def _aggregate_by_top_level_root(rows: list[IndexRow]) -> list[RootRollup]:
    lines_by_root: dict[str, int] = defaultdict(int)
    nonempty_by_root: dict[str, int] = defaultdict(int)
    size_by_root: dict[str, int] = defaultdict(int)
    count_by_root: dict[str, int] = defaultdict(int)
    bucket_rows: dict[str, list[IndexRow]] = defaultdict(list)

    for row in rows:
        root = _top_level_root(row.rel_display)
        count_by_root[root] += 1
        lines_by_root[root] += row.lines
        nonempty_by_root[root] += row.lines_nonempty
        size_by_root[root] += row.size_bytes
        bucket_rows[root].append(row)

    result: list[RootRollup] = []
    for root, lines_total in lines_by_root.items():
        result.append(
            RootRollup(
                root=root,
                file_count=count_by_root[root],
                lines=lines_total,
                lines_nonempty=nonempty_by_root[root],
                lines_exc_comments=_rollup_exc_comment_sum(bucket_rows[root]),
                size_bytes=size_by_root[root],
            )
        )

    result.sort(key=lambda item: item.lines, reverse=True)
    return result


def _read_paths_from_input(input_path: Path) -> list[str]:
    raw = input_path.read_text(encoding="utf-8", errors="replace")
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


def _resolve_entry(base: Path, entry: str) -> Path:
    normalized = entry.replace("\\", "/")
    return (base / normalized).resolve()


def inspect_paths(base: Path, rel_entries: list[str]) -> tuple[list[IndexRow], list[FlagRow]]:
    index_rows: list[IndexRow] = []
    flags: list[FlagRow] = []

    for entry in rel_entries:
        display = entry.replace("\\", "/")
        filename = Path(display).name

        try:
            target = _resolve_entry(base, entry)
        except OSError as exc:
            flags.append(
                FlagRow(rel_display=display, filename=filename, reason=f"resolve error: {exc}")
            )
            continue

        if not target.exists():
            flags.append(FlagRow(rel_display=display, filename=filename, reason="missing path"))
            continue

        if not target.is_file():
            flags.append(FlagRow(rel_display=display, filename=filename, reason="not a regular file"))
            continue

        try:
            size_bytes = target.stat().st_size
        except OSError as exc:
            flags.append(
                FlagRow(rel_display=display, filename=filename, reason=f"stat error: {exc}")
            )
            continue

        ext = target.suffix.lower()
        if ext in BINARY_EXTENSIONS:
            flags.append(
                FlagRow(
                    rel_display=display,
                    filename=filename,
                    reason=f"binary extension `{ext}`",
                )
            )
            continue

        if size_bytes > MAX_READ_BYTES:
            flags.append(
                FlagRow(
                    rel_display=display,
                    filename=filename,
                    reason=f"file too large to analyze (> {MAX_READ_BYTES} bytes)",
                )
            )
            continue

        try:
            with target.open("rb") as handle:
                sniff = handle.read(SNIFF_BYTES)
        except OSError as exc:
            flags.append(
                FlagRow(rel_display=display, filename=filename, reason=f"read error: {exc}")
            )
            continue

        if _sniff_binary_nul(sniff):
            flags.append(
                FlagRow(rel_display=display, filename=filename, reason="binary content (NUL byte in sample)")
            )
            continue

        try:
            content = target.read_bytes()
        except OSError as exc:
            flags.append(
                FlagRow(rel_display=display, filename=filename, reason=f"read error: {exc}")
            )
            continue

        ext_normalized = ext if ext else "(none)"
        try:
            line_count, max_line_chars, lines_nonempty, lines_exc_comments = _utf8_content_metrics(
                content, ext_normalized
            )
        except UnicodeDecodeError:
            flags.append(
                FlagRow(
                    rel_display=display,
                    filename=filename,
                    reason="not strict UTF-8 text",
                )
            )
            continue

        if max_line_chars > LONG_LINE_CHAR_THRESHOLD:
            flags.append(
                FlagRow(
                    rel_display=display,
                    filename=filename,
                    reason=(
                        f"very long line ({max_line_chars} chars > {LONG_LINE_CHAR_THRESHOLD}); "
                        "likely minified or generated single-line blob"
                    ),
                )
            )
            continue

        index_rows.append(
            IndexRow(
                rel_display=display,
                filename=filename,
                extension=ext_normalized,
                filetype=_filetype_label(target),
                size_bytes=size_bytes,
                lines=line_count,
                lines_nonempty=lines_nonempty,
                lines_exc_comments=lines_exc_comments,
            )
        )

    index_rows.sort(key=lambda r: r.lines, reverse=True)
    # Stable ordering for flags: by reason then path
    flags.sort(key=lambda r: (r.reason, r.rel_display))
    return index_rows, flags


def _rollup_numeric_totals(rows: list[IndexRow]) -> tuple[int, int, int | None, int, int]:
    """Sums for footer rows: lines, nonempty, exc-comment sum or None, bytes, file count."""
    if not rows:
        return 0, 0, None, 0, 0
    lines_sum = sum(r.lines for r in rows)
    nonempty_sum = sum(r.lines_nonempty for r in rows)
    exc_sum = _rollup_exc_comment_sum(rows)
    bytes_sum = sum(r.size_bytes for r in rows)
    return lines_sum, nonempty_sum, exc_sum, bytes_sum, len(rows)


def write_markdown_report(
    *,
    output_path: Path,
    base: Path,
    input_path: Path,
    index_rows: list[IndexRow],
    flags: list[FlagRow],
    detail_max_lines: int | None,
) -> None:
    generated_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines_out: list[str] = []
    lines_out.append("# Codebase index inspector report")
    lines_out.append("")
    lines_out.append(f"- Generated: `{generated_at}`")
    lines_out.append(f"- Base: `{base}`")
    lines_out.append(f"- Input list: `{input_path}`")
    lines_out.append(f"- Long-line threshold: `{LONG_LINE_CHAR_THRESHOLD}` characters per line")
    lines_out.append(
        "- Comment-aware counts use quick heuristics (hash / `//` / `/* */` / HTML / SQL); "
        "they can diverge from a full parser."
    )
    lines_out.append("")
    lines_out.append("## Summary")
    lines_out.append("")
    lines_out.append(f"- Indexed text files: **{_fmt_int(len(index_rows))}**")
    lines_out.append(f"- Flagged entries: **{_fmt_int(len(flags))}**")
    sum_lines = sum(r.lines for r in index_rows)
    sum_nonempty = sum(r.lines_nonempty for r in index_rows)
    sum_bytes = sum(r.size_bytes for r in index_rows)
    sum_exc_global = _rollup_exc_comment_sum(index_rows)
    lines_out.append(f"- Total lines (indexed files): **{_fmt_int(sum_lines)}**")
    lines_out.append(f"- Total non-empty lines (indexed files): **{_fmt_int(sum_nonempty)}**")
    if sum_exc_global is None:
        lines_out.append("- Total lines excluding comments (indexed code files only): **—**")
    else:
        lines_out.append(
            f"- Total lines excluding comments (indexed code files only): **{_fmt_int(sum_exc_global)}**"
        )
    lines_out.append(
        f"- Total size (indexed files): **{_fmt_kb_approx(sum_bytes)}** (~{_fmt_int(sum_bytes)} bytes)"
    )
    if detail_max_lines is not None:
        above_cutoff = sum(1 for r in index_rows if r.lines > detail_max_lines)
        at_or_below = sum(1 for r in index_rows if r.lines <= detail_max_lines)
        lines_out.append(
            f"- Per-file detail table cutoff: **`{_fmt_int(detail_max_lines)}`** physical lines "
            "(files **above** this are omitted from the file-by-file table only; rollups unchanged)."
        )
        lines_out.append(
            f"- Indexed files **above** cutoff (hidden from detail table): **{_fmt_int(above_cutoff)}**"
        )
        lines_out.append(
            f"- Indexed files **at or below** cutoff (shown in detail table): **{_fmt_int(at_or_below)}**"
        )
    lines_out.append("")
    lines_out.append("## Totals by top-level folder (first path segment under base)")
    lines_out.append("")
    root_agg = _aggregate_by_top_level_root(index_rows)
    if not root_agg:
        lines_out.append("_No indexed rows to aggregate._")
    else:
        lines_out.append(
            "| Folder | Files | Lines | Non-empty | Exc. comments | Size (approx. KB) |"
        )
        lines_out.append("| --- | ---:| ---:| ---:| --- | ---:|")
        for rollup in root_agg:
            lines_out.append(
                "| "
                + " | ".join(
                    [
                        _md_cell(rollup.root),
                        _fmt_int(rollup.file_count),
                        _fmt_int(rollup.lines),
                        _fmt_int(rollup.lines_nonempty),
                        _fmt_exc_cell(rollup.lines_exc_comments),
                        _fmt_kb_approx(rollup.size_bytes),
                    ]
                )
                + " |"
            )
        tl, tn, te, tb, tf = _rollup_numeric_totals(index_rows)
        lines_out.append(
            "| "
            + " | ".join(
                [
                    "**Total**",
                    _fmt_int(tf),
                    _fmt_int(tl),
                    _fmt_int(tn),
                    _fmt_exc_cell(te),
                    _fmt_kb_approx(tb),
                ]
            )
            + " |"
        )
    lines_out.append("")
    lines_out.append("## Totals by extension (indexed files only)")
    lines_out.append("")
    ext_agg = _aggregate_by_extension(index_rows)
    if not ext_agg:
        lines_out.append("_No indexed rows to aggregate._")
    else:
        lines_out.append(
            "| Extension | Files | Type | Lines | Non-empty | Exc. comments | Size (approx. KB) |"
        )
        lines_out.append("| --- | ---:| --- | ---:| ---:| --- | ---:|")
        for rollup in ext_agg:
            lines_out.append(
                "| "
                + " | ".join(
                    [
                        _md_cell(rollup.extension),
                        _fmt_int(rollup.file_count),
                        _md_cell(rollup.type_label),
                        _fmt_int(rollup.lines),
                        _fmt_int(rollup.lines_nonempty),
                        _fmt_exc_cell(rollup.lines_exc_comments),
                        _fmt_kb_approx(rollup.size_bytes),
                    ]
                )
                + " |"
            )
        tl, tn, te, tb, tf = _rollup_numeric_totals(index_rows)
        lines_out.append(
            "| "
            + " | ".join(
                [
                    "**Total**",
                    _fmt_int(tf),
                    "—",
                    _fmt_int(tl),
                    _fmt_int(tn),
                    _fmt_exc_cell(te),
                    _fmt_kb_approx(tb),
                ]
            )
            + " |"
        )
    lines_out.append("")
    lines_out.append("## Index (sorted by line count, descending)")
    lines_out.append("")
    if detail_max_lines is not None:
        lines_out.append(
            f"_Rows omitted when physical lines exceed **`{_fmt_int(detail_max_lines)}`**; "
            "the **Total** row still sums **all** indexed files._"
        )
        lines_out.append("")
    detail_rows = (
        index_rows
        if detail_max_lines is None
        else [r for r in index_rows if r.lines <= detail_max_lines]
    )
    lines_out.append(
        "| Lines | Non-empty | Exc. comments | Size (approx. KB) | Extension | "
        "File type | Filename | Path |"
    )
    lines_out.append("| ---:| ---:| --- | ---:| --- | --- | --- | --- |")
    for row in detail_rows:
        lines_out.append(
            "| "
            + " | ".join(
                [
                    _fmt_int(row.lines),
                    _fmt_int(row.lines_nonempty),
                    _fmt_exc_cell(row.lines_exc_comments),
                    _fmt_kb_approx(row.size_bytes),
                    _md_cell(row.extension),
                    _md_cell(row.filetype),
                    _md_cell(row.filename),
                    _md_cell(row.rel_display),
                ]
            )
            + " |"
        )
    tl, tn, te, tb, tf = _rollup_numeric_totals(index_rows)
    lines_out.append(
        "| "
        + " | ".join(
            [
                _fmt_int(tl),
                _fmt_int(tn),
                _fmt_exc_cell(te),
                _fmt_kb_approx(tb),
                "—",
                "—",
                "**Total (all indexed)**",
                _fmt_int(tf) + " files",
            ]
        )
        + " |"
    )
    lines_out.append("")
    lines_out.append("## Flagged entries (should usually not appear in embeddable indexes)")
    lines_out.append("")
    if not flags:
        lines_out.append("_None — all entries passed text/binary/long-line checks._")
        lines_out.append("")
    else:
        lines_out.append("| Filename | Reason | Path |")
        lines_out.append("| --- | --- | --- |")
        for row in flags:
            lines_out.append(
                "| "
                + " | ".join(
                    [
                        _md_cell(row.filename),
                        _md_cell(row.reason),
                        _md_cell(row.rel_display),
                    ]
                )
                + " |"
            )
        lines_out.append(
            "| "
            + " | ".join(
                [
                    "**Total**",
                    _fmt_int(len(flags)) + " flagged",
                    "—",
                ]
            )
            + " |"
        )
        lines_out.append("")

    output_path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect a file list and emit a Markdown report with sizes, lines, and flags.",
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to a text file with one relative path per line",
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=DEFAULT_BASE,
        help=f"Directory paths in the input are resolved against this folder (default: {DEFAULT_BASE})",
    )
    parser.add_argument(
        "--detail-max-lines",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Omit rows from the per-file Index table when physical line count exceeds N "
            "(rollups and the Index Total row still include every indexed file)."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    input_path: Path = args.input.expanduser().resolve()
    base: Path = args.base.expanduser().resolve()

    if not input_path.is_file():
        logger.error("Input path is not a file: %s", input_path)
        return 2

    detail_max_lines: int | None = args.detail_max_lines
    if detail_max_lines is not None and detail_max_lines < 1:
        logger.error("--detail-max-lines must be >= 1 when set, got %s", detail_max_lines)
        return 2

    project_dir = Path(__file__).resolve().parent
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = project_dir / f"codebase_index_inspect_{stamp}.md"

    rel_entries = _read_paths_from_input(input_path)
    logger.info("Loaded %s paths from %s", len(rel_entries), input_path)

    index_rows, flags = inspect_paths(base, rel_entries)
    write_markdown_report(
        output_path=output_path,
        base=base,
        input_path=input_path,
        index_rows=index_rows,
        flags=flags,
        detail_max_lines=detail_max_lines,
    )

    logger.info("Wrote report: %s", output_path)
    logger.info("Indexed: %s | Flagged: %s", len(index_rows), len(flags))
    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
