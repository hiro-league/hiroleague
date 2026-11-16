"""Pair apps with one environment's core, for `hiro-work up` (workflow.md, "See your change running").

Run in the core's own environment (it needs the SDK and the core's package), with the core running:

    uv run python pair_apps.py <workspace folder> <ws://127.0.0.1:7N01> <name>=<key folder> ...

<name> is the app's extension name (home, net, train, study, reports), <key folder> where the app keeps its key
(DATA_DIR/hiroleague). An app whose key the core already knows is left alone. Any other gets a fresh pairing code
(the core's own, written to its workspace as `hiro extension add` does) and pairs with it, one app at a time, since
the core keeps one code at a time. The app declares itself fully when it next connects; pairing only needs its name.
Prints one line per app; exits 1 when one didn't pair.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

from hiro_channel_sdk import ExtensionClient, ExtensionCredentials, ExtensionInfo
from hiro_channel_sdk.extension import STATUS_CONNECTED
from hirocli.domain.extensions import start_extension_pairing

WAIT_S = 30  # for the core to take a code
CODE_TTL_S = 120


def known(workspace: Path, extension_id: str) -> bool:
    """Whether the core has this app's key (its paired apps in workspace.db)."""
    db = workspace / "db" / "workspace.db"
    if not db.exists():
        return False
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        return con.execute("select 1 from extensions where extension_id = ?", (extension_id,)).fetchone() is not None
    finally:
        con.close()


async def pair(url: str, name: str, folder: Path, code: str) -> bool:
    """Connect once with the code; True once the core took it (the SDK saves the key and the id in *folder*)."""
    client = ExtensionClient(url, ExtensionInfo(name=name), ExtensionCredentials(folder))
    client.pair(code)
    runner = asyncio.create_task(client.run())
    try:
        for _ in range(WAIT_S * 10):
            if client.status == STATUS_CONNECTED:
                return True
            if runner.done():
                break
            await asyncio.sleep(0.1)
        return False
    finally:
        await client.stop()
        runner.cancel()


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    workspace, url, apps = Path(argv[0]), argv[1], argv[2:]
    failed = 0
    for item in apps:
        name, _, folder_text = item.partition("=")
        folder = Path(folder_text)
        current = ExtensionCredentials(folder).extension_id()
        if current and known(workspace, current):
            print(f"{name}: paired already")
            continue
        folder.mkdir(parents=True, exist_ok=True)
        code = start_extension_pairing(workspace, code_length=6, ttl_seconds=CODE_TTL_S).code
        try:
            asyncio.run(pair(url, name, folder, code))
        except Exception as exc:  # one app's failure is said and the others still pair
            print(f"{name}: pairing failed: {type(exc).__name__}: {exc}")
            failed += 1
            continue
        # Judged by the outcome, not the client's status: the SDK's client may end its run right after the core
        # took the code, before "connected" is seen. Paired = a key saved here that the core now knows.
        new_id = ExtensionCredentials(folder).extension_id()
        ok = bool(new_id) and known(workspace, new_id)
        print(f"{name}: paired" if ok else f"{name}: the core didn't take the code within {WAIT_S} s")
        failed += not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
