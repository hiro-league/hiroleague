"""Read a fresh-install run's logs for problems: anything the run didn't cause on purpose fails its step.

    hiro logs problems --since 2h --json | python read_logs.py problems
    journalctl -u hiro --no-pager | python read_logs.py service

Runs inside the throwaway machine (run-linux.sh, run-windows.ps1), with the standard library only. It prints what it
found, the expected problems apart from the others, and exits 1 when anything else is there.
"""

from __future__ import annotations

import json
import sys

# The problems the run causes on purpose, each with why: a line holding one of these is expected
EXPECTED = {
    "fails on purpose": "Hello 0.1.2's migration fails on purpose (the upgrade that stays)",
    "trial step failed": "Hello 0.1.2's migration fails on purpose (the upgrade that stays)",
    "didn't answer": "Hello 0.1.3 doesn't answer on purpose (the upgrade that goes back)",
    "No chat LLM configured": "a fresh machine has no AI keys yet",
    "Memory service disabled": "a fresh machine has no AI keys yet",
    "no extraction model available": "a fresh machine has no AI keys yet",
    "No STT providers": "a fresh machine has no AI keys yet",
    "macOS refused to delete it": "a Mac keeps a removed app's account unless the terminal has Full Disk Access (the "
                                  "removal says how to delete it)",
}
_TRACEBACK_SPAN = 60  # a traceback's own lines: the expected phrase is the exception's message at its end


def why_expected(line: str) -> str:
    return next((why for phrase, why in EXPECTED.items() if phrase.lower() in line.lower()), "")


def problems(text: str) -> list[str]:
    """The core's ``hiro logs problems --json``: the messages nobody caused on purpose."""
    found = json.loads(text)
    return [f"{g['level']} {g['area']}: {m}" for g in found.get("groups", []) for m in g.get("messages", [])
            if not why_expected(m)]


def service(text: str) -> list[str]:
    """The service's own log (journal or hiro.err.log): tracebacks and failed loads nobody caused on purpose."""
    lines = text.splitlines()
    bad = []
    for i, line in enumerate(lines):
        if "DLL load failed" in line:
            bad.append(line.strip())
        elif "Traceback (most recent call last)" in line:
            span = lines[i + 1:i + 1 + _TRACEBACK_SPAN]
            if not any(why_expected(s) for s in span):
                bad.append(f"{line.strip()} … {next((s.strip() for s in span if 'Error' in s), '')}")
    return bad


def main(argv: list[str]) -> int:
    kind = argv[0] if argv else ""
    read = {"problems": problems, "service": service}.get(kind)
    if read is None:
        print("usage: read_logs.py problems|service < the log")
        return 2
    text = sys.stdin.read()
    print(text)
    bad = read(text)
    print("--- not caused on purpose:" if bad else "--- nothing but what the run caused on purpose")
    for line in bad:
        print(f"  {line}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
