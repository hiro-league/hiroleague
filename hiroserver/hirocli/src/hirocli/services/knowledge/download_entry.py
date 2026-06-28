"""Isolated entrypoint for downloading a local model (reranker or embedder) in a killable subprocess.

Run as ``python -m hirocli.services.knowledge.download_entry <kind> <model_id> <cache_dir>`` where
``kind`` is ``reranker`` or ``embedder``. The knowledge service spawns this as a child process so a
multi-GB fetch can be **terminated** (an ``asyncio.to_thread`` cannot be killed). A subprocess
(vs. ``multiprocessing.Process``) avoids re-importing the server's ``__main__`` on Windows spawn.
Exit code 0 = success (the download marker is written); non-zero = failure.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3:
        print("usage: download_entry <kind> <model_id> <cache_dir>", file=sys.stderr)
        return 2
    kind, model_id, cache_dir = args[0], args[1], Path(args[2])

    if kind == "reranker":
        from hirocli.services.knowledge.reranker_registry import download, get_local_reranker

        spec = get_local_reranker(model_id)
        if spec is None:
            print(f"unknown local reranker: {model_id}", file=sys.stderr)
            return 2
        download(spec, cache_dir)  # writes the marker on success; raises (→ non-zero exit) on failure
        return 0

    if kind == "embedder":
        from hirocli.services.knowledge.embedder_registry import download, get_local_embedder

        spec = get_local_embedder(model_id)
        if spec is None:
            print(f"unknown local embedder: {model_id}", file=sys.stderr)
            return 2
        download(spec, cache_dir)
        return 0

    print(f"unknown kind: {kind!r} (expected 'reranker' or 'embedder')", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
