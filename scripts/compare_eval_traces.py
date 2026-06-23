#!/usr/bin/env python3
"""Compare memory-eval LangSmith trace dumps across runs.

Reads one or more trace JSON dumps produced by ``dump_langsmith_trace.py`` and
extracts, per ``eval_question``: the judge verdict, negative-control flag, the
model + ideal answers, the judge's reason, recall counts, the number of agentic
search turns, and the declared ``reduce.op``. Prints a per-question verdict
matrix across runs plus aggregates, regressions, and fixes.

Usage:
    python scripts/compare_eval_traces.py <trace1.json> <trace2.json> ...
    # bare names resolve under $HIRO_TRACE_DIR (default ../hiro-traces)

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


def trace_dir() -> Path:
    env = os.environ.get("HIRO_TRACE_DIR")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[1].parent / "hiro-traces"


def _msg_content(x) -> str | None:
    if isinstance(x, dict):
        if isinstance(x.get("content"), str):
            return x["content"]
        if "kwargs" in x and isinstance(x["kwargs"].get("content"), str):
            return x["kwargs"]["content"]
    return None


def _section(text: str, header: str) -> str | None:
    """Pull a '## Header' section body out of a judge prompt blob."""
    m = re.search(rf"##\s*{re.escape(header)}\s*\n(.*?)(?=\n##\s|\Z)", text, re.S)
    return m.group(1).strip() if m else None


def _judge_human_blob(eval_judge: dict) -> str | None:
    inp = eval_judge.get("inputs")
    msgs = inp.get("input") if isinstance(inp, dict) else inp
    if not isinstance(msgs, list):
        return None
    for m in msgs:
        c = _msg_content(m)
        if c and "## Question" in c:
            return c
    return None


def _answer_text(eval_answer: dict) -> str | None:
    out = eval_answer.get("outputs") or {}
    gens = out.get("generations")
    try:
        return gens[0][0].get("text")
    except (TypeError, IndexError, AttributeError):
        return None


def _find_child(node: dict, name: str) -> dict | None:
    for c in node.get("children") or []:
        if c.get("name") == name:
            return c
    return None


def _all_children(node: dict, name: str) -> list[dict]:
    return [c for c in node.get("children") or [] if c.get("name") == name]


def extract_question(q: dict) -> dict:
    md = q.get("metadata") or {}
    full_id = md.get("id") or ""
    set_name = md.get("set") or ""
    qid = full_id[len(set_name) + 1 :] if set_name and full_id.startswith(set_name) else full_id

    recall = _find_child(q, "recall")
    eval_answer = _find_child(q, "eval_answer")
    eval_judge = _find_child(q, "eval_judge")

    rec = {"recalled": None, "facts": None, "entities": None, "episodes": None}
    n_search = None
    reduce_op = None
    if recall:
        out = recall.get("outputs") or {}
        for k in rec:
            rec[k] = out.get(k)
        n_search = len(_all_children(recall, "search_memory"))
        rf = _find_child(recall, "retrieval_final")
        if rf:
            parsed = (rf.get("outputs") or {}).get("parsed") or {}
            reduce_op = (parsed.get("reduce") or {}).get("op")

    verdict = neg_ctrl = reason = grounded = recall_suff = None
    ideal = rubric = question = None
    if eval_judge:
        parsed = (eval_judge.get("outputs") or {}).get("parsed") or {}
        verdict = parsed.get("verdict")
        reason = parsed.get("reason")
        grounded = parsed.get("grounded")
        recall_suff = parsed.get("recall_sufficient")
        blob = _judge_human_blob(eval_judge)
        if blob:
            question = _section(blob, "Question")
            ideal = _section(blob, "Ideal Answer")
            rubric = _section(blob, "Rubric (required elements)") or _section(blob, "Rubric")
            nc = _section(blob, "Negative Control")
            neg_ctrl = bool(nc and nc.strip().lower().startswith("yes"))

    return {
        "id": qid,
        "verdict": verdict,
        "neg_control": neg_ctrl,
        "question": question,
        "ideal": ideal,
        "rubric": rubric,
        "model_answer": _answer_text(eval_answer),
        "judge_reason": reason,
        "grounded": grounded,
        "recall_sufficient": recall_suff,
        "n_search_turns": n_search,
        "reduce_op": reduce_op,
        "recall": rec,
        "status": q.get("status"),
    }


def load_trace(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    tree = d["tree"]
    questions = [extract_question(c) for c in tree.get("children") or [] if c.get("name") == "eval_question"]
    return {
        "file": path.name,
        "fetched_at": d.get("fetched_at"),
        "revision": (questions[0].get("revision") if questions else None),
        "set": (tree.get("metadata") or {}).get("set"),
        "questions": {qq["id"]: qq for qq in questions},
        "order": [qq["id"] for qq in questions],
    }


PASS_MARK = {"pass": "P", "partial": "~", "fail": "F", "abstain": "A", None: "?"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("traces", nargs="+", help="Trace JSON files (oldest first); bare names resolve under $HIRO_TRACE_DIR")
    ap.add_argument("-o", "--out", help="Write extracted comparison JSON here")
    args = ap.parse_args()

    paths = []
    for t in args.traces:
        p = Path(t)
        if not p.exists() and p.parent == Path("."):
            p = trace_dir() / t
        paths.append(p)

    runs = [load_trace(p) for p in paths]

    # union of question ids, ordered by the last run's order then any extras
    all_ids = list(runs[-1]["order"])
    for r in runs:
        for qid in r["order"]:
            if qid not in all_ids:
                all_ids.append(qid)

    labels = [f"R{i+1}" for i in range(len(runs))]
    print("=" * 100)
    print("RUN LEGEND (oldest -> newest)")
    for lab, r in zip(labels, runs):
        print(f"  {lab}: {r['file']:28s} fetched={r['fetched_at']}  set={r['set']}")
    print("  Verdict marks: P=pass  ~=partial  F=fail  A=abstain  ?=missing   * after mark = negative-control question")
    print("=" * 100)

    # verdict matrix
    hdr = f"{'question':<14}" + "".join(f"{lab:>5}" for lab in labels) + "   reduce_op(newest)  search(newest)  recalled(newest)"
    print(hdr)
    print("-" * len(hdr))
    counts = {lab: {"pass": 0, "partial": 0, "fail": 0, "abstain": 0, "missing": 0} for lab in labels}
    for qid in all_ids:
        row = f"{qid:<14}"
        for lab, r in zip(labels, runs):
            qq = r["questions"].get(qid)
            if not qq:
                row += f"{'-':>5}"
                counts[lab]["missing"] += 1
                continue
            mark = PASS_MARK.get(qq["verdict"], "?")
            if qq.get("neg_control"):
                mark += "*"
            row += f"{mark:>5}"
            v = qq["verdict"]
            counts[lab][v if v in counts[lab] else "missing"] += 1
        newest = runs[-1]["questions"].get(qid) or {}
        rop = newest.get("reduce_op")
        ns = newest.get("n_search_turns")
        rc = (newest.get("recall") or {}).get("recalled")
        row += f"   {str(rop):<16}  {str(ns):<13}  {rc}"
        print(row)

    print("-" * len(hdr))
    print("AGGREGATES")
    for lab, r in zip(labels, runs):
        c = counts[lab]
        tot = sum(c.values()) - c["missing"]
        print(f"  {lab} ({r['file']}): pass={c['pass']}  partial={c['partial']}  fail={c['fail']}  abstain={c['abstain']}  (n={tot})")

    # transitions newest-1 -> newest
    if len(runs) >= 2:
        prev, cur = runs[-2], runs[-1]
        print("=" * 100)
        print(f"TRANSITIONS  {labels[-2]} -> {labels[-1]}  ({prev['file']} -> {cur['file']})")
        regressions, fixes, other = [], [], []
        for qid in all_ids:
            a = (prev["questions"].get(qid) or {}).get("verdict")
            b = (cur["questions"].get(qid) or {}).get("verdict")
            if a == b:
                continue
            rank = {"pass": 3, "partial": 2, "abstain": 1, "fail": 0, None: -1}
            line = f"  {qid:<14} {a} -> {b}"
            if rank.get(b, -1) > rank.get(a, -1):
                fixes.append(line)
            elif rank.get(b, -1) < rank.get(a, -1):
                regressions.append(line)
            else:
                other.append(line)
        print(" FIXES (improved):")
        print("\n".join(fixes) or "   (none)")
        print(" REGRESSIONS (worsened):")
        print("\n".join(regressions) or "   (none)")
        if other:
            print(" OTHER changes:")
            print("\n".join(other))

    if args.out:
        outp = Path(args.out)
        if outp.parent == Path("."):
            outp = trace_dir() / args.out
        with open(outp, "w", encoding="utf-8") as f:
            json.dump({"runs": runs, "labels": labels}, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nWrote comparison JSON -> {outp}", file=sys.stderr)


if __name__ == "__main__":
    main()
