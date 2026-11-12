"""Pair the app with the HiroLeague core from the server's shell, at first setup.

Settings → HiroLeague pairs the app too, but only for someone signed in, and signing in goes through the core, which
needs the app paired first. So the first pairing is done from the shell, with nothing opened up meanwhile:

    docker exec nethiro python -m nethiro.pair ws://127.0.0.1:18082 <code>
    docker compose restart nethiro        # from ~/nethiro: the app connects with the saved key

(each app's `pair.py` runs `main()` here, after its package said which app it is). <code> is the pairing code from the
core's admin (Extensions → Add an extension). This saves the core's address (the `hiroleague_url` setting) and the
app's key (DATA_DIR/hiroleague, as the app keeps it), connects once to pair, and stops. The running app is restarted
after it, so its own connection doesn't race this one.
"""

import asyncio

from hiro_channel_sdk import ExtensionClient, ExtensionCredentials
from hiro_channel_sdk.extension import STATUS_CONNECTED
from sqlmodel import Session

from . import identity, settings
from .db import engine
from .hiroleague import URL_KEY, info_for, site_url_default

WAIT = 30.0  # seconds to wait for the core to take the code


def _save_url(url: str) -> None:
    with Session(engine) as session:
        settings.put(session, URL_KEY, url)
        session.commit()


async def pair(url: str, code: str) -> bool:
    """Connect once with the code; True once the core took it (the key is saved by the SDK)."""
    client = ExtensionClient(url, info_for(site_url_default()), ExtensionCredentials(identity.app().data_dir / "hiroleague"))
    client.pair(code)
    runner = asyncio.create_task(client.run())
    try:
        for _ in range(int(WAIT * 10)):
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
    app = identity.app()
    if len(argv) != 2:
        print(f"Usage: python -m {app.name}.pair <the core's extension address, e.g. ws://127.0.0.1:18082> <pairing code>")
        return 2
    url, code = argv[0].strip(), argv[1].strip()
    if not url.startswith(("ws://", "wss://")) or not code:
        print("The core's address starts with ws:// (e.g. ws://127.0.0.1:18082), and the code is the one its admin shows.")
        return 2
    _save_url(url)
    try:
        ok = asyncio.run(pair(url, code))
    except Exception as exc:  # anything: said in one line, nothing half-done but the saved address
        print(f"Pairing failed: {type(exc).__name__}: {exc}")
        return 1
    if not ok:
        print(f"The core didn't take the code within {WAIT:.0f} s (wrong or expired code, or the core isn't at {url}).")
        return 1
    print(f"Paired. Restart {app.title} (docker compose restart {app.name}) so it connects with its new key.")
    return 0
