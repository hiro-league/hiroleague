#!/usr/bin/env python3
"""Dump a public LangSmith trace to a JSON file for offline / AI-agent inspection.

A public trace share URL looks like:
    https://smith.langchain.com/public/<share-token>/r

The page is backed by an auth-free JSON API. The root run carries `child_run_ids`,
but the public `runs/query` endpoint returns descendants only when you ask for them
by id. This script walks the whole tree and writes both a flat list and a nested
tree of runs (with inputs/outputs resolved) to a JSON file.

Usage:
    python scripts/dump_langsmith_trace.py <share-url-or-token> [-o out.json]

Stdlib only -- no langsmith SDK or API key required.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

API_BASE = "https://api.smith.langchain.com/public"
BATCH = 50  # ids per runs/query request


def extract_token(url_or_token: str) -> str:
    """Accept a full /public/<token>/r URL or a bare token."""
    m = re.search(r"/public/([0-9a-fA-F-]{36})", url_or_token)
    if m:
        return m.group(1)
    if re.fullmatch(r"[0-9a-fA-F-]{36}", url_or_token.strip()):
        return url_or_token.strip()
    sys.exit(f"Could not find a share token in: {url_or_token!r}")


def _get(token: str) -> dict:
    req = urllib.request.Request(f"{API_BASE}/{token}/run")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _query_ids(token: str, ids: list[str]) -> list[dict]:
    body = json.dumps({"id": ids}).encode()
    req = urllib.request.Request(
        f"{API_BASE}/{token}/runs/query",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r).get("runs", [])


def _fetch_url(url: str):
    """GET a presigned S3 URL; return parsed JSON, or raw text if not JSON."""
    with urllib.request.urlopen(url, timeout=120) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _urls_in(field) -> list[tuple[str | None, str]]:
    """Normalize an *_s3_urls field into a list of (key, url) pairs.

    LangSmith offloads large payloads to presigned URLs. The field is usually a
    dict like {"inputs": "https://..."} but can be a bare URL string; handle both.
    """
    if not field:
        return []
    if isinstance(field, str) and field.startswith("http"):
        return [(None, field)]
    if isinstance(field, dict):
        return [(k, v) for k, v in field.items() if isinstance(v, str) and v.startswith("http")]
    return []


def resolve_offloaded(runs: list[dict]) -> int:
    """For runs whose inline inputs/outputs are empty, fetch the S3-offloaded
    payload via presigned URLs and inline it. Returns the number of fetches.

    Mutates runs in place, so a tree built afterward sees the resolved data.
    """
    fetched = 0
    for run in runs:
        for kind in ("inputs", "outputs"):
            if run.get(kind):  # already inline and non-empty
                continue
            pairs = _urls_in(run.get(f"{kind}_s3_urls"))
            if not pairs:
                continue
            # Prefer a url keyed exactly by the kind (e.g. {"inputs": url});
            # otherwise merge all fetched url contents into one dict.
            keyed = [u for (k, u) in pairs if k == kind]
            try:
                if keyed:
                    run[kind] = _fetch_url(keyed[0])
                    fetched += 1
                elif len(pairs) == 1 and pairs[0][0] is None:
                    run[kind] = _fetch_url(pairs[0][1])
                    fetched += 1
                else:
                    merged = {}
                    for k, u in pairs:
                        merged[k] = _fetch_url(u)
                        fetched += 1
                    run[kind] = merged
            except (urllib.error.URLError, urllib.error.HTTPError) as e:
                run[f"{kind}_s3_error"] = str(e)
            if fetched and fetched % 25 == 0:
                print(f"  resolved {fetched} S3 payloads...", file=sys.stderr)
    return fetched


def fetch_all_runs(token: str) -> tuple[dict, list[dict]]:
    """Return (root_run, all_runs_including_root)."""
    root = _get(token)
    all_runs = {root["id"]: root}
    frontier = list(root.get("child_run_ids") or [])
    seen = set(all_runs)

    while frontier:
        # de-dup while preserving discovery order
        todo = [i for i in frontier if i not in seen]
        frontier = []
        for start in range(0, len(todo), BATCH):
            chunk = todo[start : start + BATCH]
            runs = _query_ids(token, chunk)
            for run in runs:
                rid = run["id"]
                if rid in seen:
                    continue
                seen.add(rid)
                all_runs[rid] = run
                frontier.extend(run.get("child_run_ids") or [])
            print(f"  fetched {len(seen)} runs so far...", file=sys.stderr)

    return root, list(all_runs.values())


def build_tree(root_id: str, runs: list[dict]) -> dict:
    """Nest runs under their parents, ordered by start_time."""
    by_id = {r["id"]: r for r in runs}
    children: dict[str, list[str]] = {}
    for r in runs:
        pid = r.get("parent_run_id")
        if pid in by_id:
            children.setdefault(pid, []).append(r["id"])

    def node(rid: str) -> dict:
        r = by_id[rid]
        kids = sorted(children.get(rid, []), key=lambda i: by_id[i].get("start_time") or "")
        return {
            "id": rid,
            "name": r.get("name"),
            "run_type": r.get("run_type"),
            "status": r.get("status"),
            "start_time": r.get("start_time"),
            "end_time": r.get("end_time"),
            "total_tokens": r.get("total_tokens"),
            "total_cost": r.get("total_cost"),
            "error": r.get("error"),
            "tags": r.get("tags"),
            "metadata": (r.get("extra") or {}).get("metadata"),
            "inputs": r.get("inputs"),
            "outputs": r.get("outputs"),
            "children": [node(k) for k in kids],
        }

    return node(root_id)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url", help="Public trace URL (.../public/<token>/r) or bare token")
    ap.add_argument("-o", "--out", help="Output JSON path (default: trace_<token8>.json)")
    ap.add_argument(
        "--no-s3",
        action="store_true",
        help="Skip fetching S3-offloaded inputs/outputs (faster, but large payloads stay as URLs)",
    )
    args = ap.parse_args()

    token = extract_token(args.url)
    print(f"Share token: {token}", file=sys.stderr)

    root, runs = fetch_all_runs(token)
    if not args.no_s3:
        n = resolve_offloaded(runs)
        print(f"  resolved {n} S3-offloaded payloads", file=sys.stderr)
    tree = build_tree(root["id"], runs)

    out = args.out or f"trace_{token[:8]}.json"
    payload = {
        "share_token": token,
        "source_url": f"https://smith.langchain.com/public/{token}/r",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "root_run_id": root["id"],
        "run_count": len(runs),
        "tree": tree,       # nested, trimmed-but-complete view for inspection
        "runs_flat": runs,  # every run, full raw payload
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)

    print(f"\nWrote {len(runs)} runs to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
