#!/usr/bin/env python3
"""Ablation: how much do correct retrieval / correct answers depend on each memory-element
kind (edge=fact, entity, episode)? Answers "is extracting entities/episodes earning its keep,
or do edges carry the load?"

Two content-based studies (the built-in evidence-recall metric is structurally edges-only —
only facts carry a source-turn id — so we measure on CONTENT, not that metric):

  STUDY 1 — Retrieval coverage. For every gold-evidence turn, which kinds recover it:
     edge    : a recalled fact whose chunk_id == the gold turn  (exact, by design)
     episode : a recalled episode whose raw text matches the gold turn body (token-recall)
     entity  : a recalled entity whose summary/memory matches the gold turn body (token-recall)
     → recall under {edges} / {edges+episodes} / {edges+episodes+entities} + unique contributions.

  STUDY 2 — Answer grounding. For correct/grounded answers (judge cited evidence), map each
     cited line back to the kinds that actually carry that content → what correct answers leaned
     on, and how often a kind was the SOLE carrier (i.e. edges-only would have lost it).

Run:  uv run python scripts/analyze_kind_dependence.py
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

DB = Path(r"C:\Users\augr\AppData\Local\hiro\workspaces\default\knowledge\eval_results.db")
CORPUS = Path(r"D:\projects\hiro-code-reports\eval-corpus")
THRESH = 0.6  # token-recall threshold for fuzzy text coverage (episode/entity)
PASS_MARKS = {"✓", "pass", "abstain", "~"}  # "correct or partially-correct/abstain" population

_WORD = re.compile(r"[a-z0-9]+")


def words(s: str) -> set[str]:
    return {w for w in _WORD.findall((s or "").lower()) if len(w) > 3}


def token_recall(probe: str, target: str) -> float:
    """Fraction of probe's content words present in target."""
    p = words(probe)
    if not p:
        return 0.0
    return len(p & words(target)) / len(p)


def find_corpus_files(corpus_id: str) -> tuple[Path | None, Path | None]:
    """(sidecar, episodes.jsonl) for a corpus id, searching beam/ and locomo/ layouts."""
    side = None
    for ext in (f"{corpus_id}.beam.yaml", f"{corpus_id}.locomo.yaml"):
        hits = list(CORPUS.rglob(ext))
        if hits:
            side = hits[0]
            break
    eps = None
    hits = list(CORPUS.rglob(f"{corpus_id}.episodes.jsonl"))
    if hits:
        eps = hits[0]
    return side, eps


def load_gold(side: Path) -> dict[str, list[str]]:
    import yaml

    y = yaml.safe_load(side.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for qid, meta in (y.get("questions") or {}).items():
        if not isinstance(meta, dict):
            continue
        ev = meta.get("evidence") if isinstance(meta.get("evidence"), dict) else {}
        ids = [str(v) for v in (ev.get("episode_ids") or []) if str(v).strip()]
        if ids:
            out[str(qid)] = ids
    return out


def load_bodies(eps: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in eps.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        eid = str(o.get("id") or o.get("chunk_id") or o.get("episode_id") or o.get("uuid") or "")
        body = o.get("body") or o.get("text") or o.get("content") or ""
        if eid:
            out[eid] = body
    return out


def gold_lookup(gold: dict[str, list[str]], qid: str) -> list[str] | None:
    """Resolve a db question_id against sidecar keys (full id or corpus-stripped)."""
    if qid in gold:
        return gold[qid]
    # strip corpus prefix: beam128k_14_sum_01 -> sum_01 ; locomo_conv_43_q5 -> q5
    parts = qid.split("_")
    for n in range(1, len(parts)):
        cand = "_".join(parts[n:])
        if cand in gold:
            return gold[cand]
    return None


def strip_evidence_line(line: str) -> str:
    """Reduce a rendered evidence line to its core claim text for matching."""
    s = line.strip().lstrip("-•").strip()
    s = re.sub(r"^\[[^\]]*\]\s*", "", s)  # leading [date]
    s = re.sub(r"\s*\[[^\]]*\]\s*$", "", s)  # trailing [REL · as of ...]
    s = re.sub(r"\s*\([A-Z][A-Za-z_ ]*\)\s*$", "", s)  # trailing (TYPE)
    return s.strip()


def study1(rows: dict[str, dict], corpora: dict[str, tuple]) -> None:
    """Exact id-based coverage (matches the official metric): a gold turn is recovered by an
    EDGE if a recalled fact's chunk_id == it, by an EPISODE if a recalled episode's uuid == it.
    Entities carry only a graph uuid (no corpus-turn link) so they cannot recover a turn at all."""
    print("\n" + "=" * 78)
    print("STUDY 1 — RETRIEVAL: which kinds recover the gold-evidence turns (exact id match)")
    print("=" * 78)
    agg: dict[str, dict] = {}
    for qid, r in rows.items():
        cid = next((c for c in corpora if qid.startswith(c)), None)
        if cid is None:
            continue
        gold_map, _bodies = corpora[cid]
        gold = gold_lookup(gold_map, qid)
        if not gold:
            continue
        rec = (r.get("legs", {}).get("recall", {}) or {}).get("recalled") or []
        fact_chunks = {str(it.get("chunk_id")) for it in rec if it.get("kind") == "fact"}
        epi_ids = {str(it.get("uuid")) for it in rec if it.get("kind") == "episode"}
        a = agg.setdefault(cid, dict(total=0, both=0, edge_only=0, epi_only=0, none=0))
        for g in gold:
            e = g in fact_chunks
            p = g in epi_ids
            a["total"] += 1
            if e and p:
                a["both"] += 1
            elif e:
                a["edge_only"] += 1
            elif p:
                a["epi_only"] += 1
            else:
                a["none"] += 1

    hdr = (f"{'corpus':<18}{'gold':>6}{'R(edge)':>9}{'R(+epi)':>9}"
           f"{'both':>7}{'edge-only':>11}{'epi-only':>10}{'missed':>8}")
    print(hdr)
    tot = dict(total=0, both=0, edge_only=0, epi_only=0, none=0)
    for cid, a in sorted(agg.items()):
        for k in tot:
            tot[k] += a[k]
        re_e = (a["both"] + a["edge_only"]) / a["total"]
        re_ep = (a["both"] + a["edge_only"] + a["epi_only"]) / a["total"]
        print(f"{cid:<18}{a['total']:>6}{re_e:>8.0%}{re_ep:>9.0%}"
              f"{a['both']:>7}{a['edge_only']:>11}{a['epi_only']:>10}{a['none']:>8}")
    if tot["total"]:
        re_e = (tot["both"] + tot["edge_only"]) / tot["total"]
        re_ep = (tot["both"] + tot["edge_only"] + tot["epi_only"]) / tot["total"]
        print("-" * 78)
        print(f"{'ALL':<18}{tot['total']:>6}{re_e:>8.0%}{re_ep:>9.0%}"
              f"{tot['both']:>7}{tot['edge_only']:>11}{tot['epi_only']:>10}{tot['none']:>8}")
        print(
            f"\n  edges recover {re_e:.0%} of gold turns; episodes lift to {re_ep:.0%} "
            f"(+{re_ep-re_e:.0%} via {tot['epi_only']} turns NO edge covered). "
            f"entities: 0 (no corpus-turn link). {tot['none']} turns recovered by nothing."
        )
        print(
            f"  redundancy: {tot['both']} turns covered by BOTH edge+episode; "
            f"only {tot['edge_only']} by edge alone."
        )


def study2(rows: dict[str, dict]) -> None:
    print("\n" + "=" * 78)
    print("STUDY 2 — ANSWERING: what kinds carry the evidence correct answers cited")
    print("=" * 78)
    buckets = {
        "beam": dict(lines=0, edge=0, epi=0, ent=0, edge_only=0, epi_only=0, ent_only=0, none=0, qs=0),
        "locomo": dict(lines=0, edge=0, epi=0, ent=0, edge_only=0, epi_only=0, ent_only=0, none=0, qs=0),
    }
    for qid, r in rows.items():
        leg = r.get("legs", {}).get("recall", {}) or {}
        ev = leg.get("evidence")
        mark = leg.get("mark")
        if not ev or mark not in PASS_MARKS:
            continue
        lines = ev if isinstance(ev, list) else [ln for ln in str(ev).splitlines() if ln.strip()]
        lines = [strip_evidence_line(str(ln)) for ln in lines]
        lines = [ln for ln in lines if len(ln) >= 12]
        if not lines:
            continue
        rec = leg.get("recalled") or []
        facts = [it.get("fact", "") for it in rec if it.get("kind") == "fact"]
        episodes = [it.get("memory", "") for it in rec if it.get("kind") == "episode"]
        entities = [
            f"{it.get('summary','')} {it.get('memory','')}" for it in rec if it.get("kind") == "entity"
        ]
        b = buckets["beam" if qid.startswith("beam") else "locomo"]
        b["qs"] += 1
        for ln in lines:
            in_e = any(token_recall(ln, f) >= THRESH for f in facts)
            in_p = any(token_recall(ln, e) >= THRESH for e in episodes)
            in_t = any(token_recall(ln, e) >= THRESH for e in entities)
            b["lines"] += 1
            b["edge"] += in_e
            b["epi"] += in_p
            b["ent"] += in_t
            if in_e and not in_p and not in_t:
                b["edge_only"] += 1
            if in_p and not in_e and not in_t:
                b["epi_only"] += 1
            if in_t and not in_e and not in_p:
                b["ent_only"] += 1
            if not (in_e or in_p or in_t):
                b["none"] += 1

    for name, b in buckets.items():
        n = b["lines"]
        if not n:
            continue
        print(f"\n[{name}]  {b['qs']} correct/grounded answers · {n} cited evidence lines")
        print(f"  carried by EDGES   : {b['edge']:>4}/{n}  ({b['edge']/n:.0%})   sole carrier: {b['edge_only']} ({b['edge_only']/n:.0%})")
        print(f"  carried by EPISODES: {b['epi']:>4}/{n}  ({b['epi']/n:.0%})   sole carrier: {b['epi_only']} ({b['epi_only']/n:.0%})")
        print(f"  carried by ENTITIES: {b['ent']:>4}/{n}  ({b['ent']/n:.0%})   sole carrier: {b['ent_only']} ({b['ent_only']/n:.0%})")
        print(f"  matched no kind    : {b['none']} ({b['none']/n:.0%})  (judge paraphrase / world knowledge)")


def main() -> None:
    if not DB.exists():
        sys.exit(f"DB not found: {DB}")
    con = sqlite3.connect(str(DB))
    rows = {
        q: json.loads(rj)
        for q, rj in con.execute("select question_id,row_json from memory_eval_results")
    }
    # corpora present
    corpus_ids = sorted({q.rsplit("_", 2)[0] for q in rows})
    corpora: dict[str, tuple] = {}
    for cid in corpus_ids:
        side, eps = find_corpus_files(cid)
        if side and eps:
            corpora[cid] = (load_gold(side), load_bodies(eps))
        else:
            print(f"  (skip {cid}: sidecar/episodes not found)", file=sys.stderr)
    print(f"Loaded {len(rows)} eval rows across corpora: {sorted(corpora)}")
    study1(rows, corpora)
    study2(rows)


if __name__ == "__main__":
    main()
