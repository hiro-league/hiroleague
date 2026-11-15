r"""Data and real systems for hiro-work (hiro-docs standards/workflow.md, "Data and real systems").

Two jobs, both on copies of the family's data:

- **env1..env5 are safe by default** (`make_safe`, `env_overrides`, `core_env`): their copy of env0's data reads no
  real system (Home Assistant, Frigate through HA, MQTT, AdGuard, NetHiro's health checks of the house) and can start
  no AI call (the core's providers are left out), unless the task asks: `hiro-work start ... --real-reads` and/or
  `--real-ai`, or later `hiro-work real <task> --reads --ai`. Sends, HA writes and sign-in stay off either way
  (hiro_work.ENV_DEV_FORCED).
- **`hiro-work refresh-data`: live -> env0** (`cmd_refresh_data`). On Simone each live database is copied with
  SQLite's backup (as a deploy does) and scrubbed there of what is never copied (tokens and logins in settings,
  sign-in sessions, pairing keys); the copies come to C:\hiro\data\live-copies\<stamp>. `--apply <stamp>` then stops
  env0's servers, moves env0's databases to C:\hiro\archive (nothing is deleted), puts the live copies in their place
  with env0's own settings kept, starts the servers again, and reports row counts per table: live, copy, env0.

Standard library only: it runs on the system Python, beside hiro_work.py.
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from types import ModuleType

APPS = ["homehiro", "nethiro", "trainhiro", "studyhiro"]
READS, AI = "reads", "ai"  # what a task may ask for in env1..env5 (Task.real)

# ------------------------------------------------------------------------------------------- env1..env5: safe

# The setting rows that point an app at a real system (an address or a login): left out of an env1..env5 copy
# without "reads". With no address, HomeHiro's and NetHiro's HA connection doesn't start (ha/gateway.py), so
# neither does Frigate (its address comes from HA's Frigate integration); HomeHiro's MQTT doesn't connect
# (streams/sources/frigate.py); NetHiro has no AdGuard login; TrainHiro has no Frigate.
READ_KEYS = {
    "homehiro": ("ha_url", "ha_token", "mqtt_host", "mqtt_port", "mqtt_user", "mqtt_password"),
    "nethiro": ("ha_url", "ha_token", "adguard_login"),
    "trainhiro": ("frigate_url",),
}
# Provider keys the PC's environment may hold (GEMINI_API_KEY, OPENAI_API_KEY...): blanked for an env1..env5 core
# without "ai", besides its providers being left out
KEY_VAR = re.compile(r"(API_KEY|API_TOKEN)$")


def env_overrides(app: str, real: list[str]) -> dict[str, str | None]:
    """An app's .env.dev lines in env1..env5 besides OUTPUTS, HA_AUTO_WRITES and AUTH: a value is written, None
    drops env0's line (the app's default is then off)."""
    out: dict[str, str | None] = {}
    if app == "homehiro":
        out["TALKER_KEY"] = None  # nothing plays with OUTPUTS off: Talker's key stays in env0
        if AI not in real:
            out["AUTOMATION_BUDGET_USD"] = "0"  # automations' LLM lines and voices: nothing to spend
    if app == "trainhiro" and READS not in real:
        out["FRIGATE_URL"] = None
    return out


def core_env(environ: dict[str, str], real: list[str]) -> dict[str, str]:
    """Extra environment for an env1..env5 core: provider keys in the PC's environment blanked without "ai"
    (an empty value removes the variable in the server's PowerShell runner)."""
    if AI in real:
        return {}
    return {k: "" for k in environ if KEY_VAR.search(k)}


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}


def make_safe(data: Path, real: list[str]) -> list[str]:
    """Turn real systems off in an env1..env5 copy (its data folder): what it did, in words."""
    did: list[str] = []
    if READS not in real:
        for app, keys in READ_KEYS.items():
            db = data / app / f"{app}.db"
            if not db.exists():
                continue
            with contextlib.closing(sqlite3.connect(db)) as con, con:
                if "setting" in _tables(con):
                    gone = con.execute(f"delete from setting where key in ({','.join('?' * len(keys))})",
                                       keys).rowcount
                    if gone:
                        did.append(f"{app}: {gone} address/login setting(s) left out")
        # NetHiro's health checks ping and ask the house's devices, Frigate and HA every round: none is enabled
        db = data / "nethiro" / "nethiro.db"
        if db.exists():
            with contextlib.closing(sqlite3.connect(db)) as con, con:
                if "statusitem" in _tables(con):
                    n = con.execute("update statusitem set enabled = 0 where enabled").rowcount
                    if n:
                        did.append(f"nethiro: {n} health check(s) off")
    if AI not in real:
        # No provider set up = no AI call: every ask, the core's own jobs and voices check the providers first
        # (CredentialStore.is_configured). The plan tools' logins live in the workspace's plans/ folder, which an
        # environment never gets (hiro_work.CORE_SKIP).
        prov = data / "core" / "default" / "providers.json"
        if prov.exists():
            doc = json.loads(prov.read_text(encoding="utf-8-sig"))
            if doc.get("providers"):
                did.append(f"core: {len(doc['providers'])} AI provider(s) left out")
                doc["providers"] = []
                prov.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return did


def describe(real: list[str]) -> str:
    """The card's line about real systems."""
    reads = "real reads ON (HA, Frigate, MQTT, health checks)" if READS in real else "real reads off"
    ai = "AI ON (the copied providers)" if AI in real else "AI off"
    return f"{reads} | {ai} | sends, HA writes and sign-in off"


# ------------------------------------------------------------------------------------------- live -> env0

LIVE_HOST = "simone"
KEEP_COPIES = 3  # live copies kept on the PC; older ones are pruned
# Each live database: (its folder on Simone, the databases there). Old snapshots beside them are left out.
LIVE = {
    "homehiro": ("~/homehiro/data", ["homehiro.db", "streams.db"]),
    "nethiro": ("~/nethiro/data", ["nethiro.db"]),
    "trainhiro": ("~/trainhiro/data", ["trainhiro.db"]),
    "studyhiro": ("~/studyhiro/data", ["studyhiro.db"]),
    "core": ("~/.local/share/hiro/workspaces/default/db", ["workspace.db", "data.db", "knowledge.db"]),
}
# Per-place settings: never copied from live (scrubbed on Simone), and env0's own are kept. A key is per-place when
# it is named here or matches the pattern (a token, a password, a login, a key, an address).
PLACE_KEYS = (
    "hiroleague_url", "hiroleague_admin_url", "homehiro_url", "nethiro_url", "trainhiro_url", "studyhiro_url",
    "core_ai_profiles", "core_voice_profiles",  # the place's core's profiles, as last read
    "ha_url", "ha_token", "ha_link_url", "mqtt_host", "mqtt_port", "mqtt_user", "mqtt_password", "frigate_url",
    "adguard_login", "adguard_sync", "services_reader", "tv_key", "tv_cast",
    "last_sync_at", "last_sync_error", "status_last_round_at",
)
PLACE_KEY_PATTERN = r"token|password|secret|login|_key$|_url$"
# Per-place tables: emptied in the live copy, env0's own rows kept. Sign-in sessions; the core's paired apps and
# devices (their keys), its channel plugins (WhatsApp), LAN names, characters (their folders are the place's) and
# local model servers.
PLACE_TABLES = {
    "workspace.db": ["admin_sessions", "extensions", "devices", "channel_plugins", "site_names", "characters",
                     "local_models"],
    **{f"{a}.db": ["websession"] for a in APPS},
}
# Left out of a refresh, said in the report: files beside the databases, the core's memory graph and vector store
LEFT_OUT = [
    "files beside the databases (HomeHiro's people/, recognition/, streams/, llm-requests/; StudyHiro's files/)",
    "the core's memory graph (graphiti_kuzu.db, locked while the live core runs) and vector store (qdrant/)",
    "the core's preferences.json, providers.json, config.json, characters/ and plans/ (env0's own)",
    "the WhatsApp session, each app's pairing key (hiroleague/), sign-in sessions, tokens and logins in settings",
]


def is_place_key(key: str) -> bool:
    return key in PLACE_KEYS or re.search(PLACE_KEY_PATTERN, key) is not None


def counts(con: sqlite3.Connection, schema: str = "main") -> dict[str, int]:
    names = [r[0] for r in con.execute(
        f"select name from {schema}.sqlite_master where type = 'table' and name not like 'sqlite_%' order by name")]
    return {t: con.execute(f"select count(*) from {schema}.[{t}]").fetchone()[0] for t in names}


# Runs on Simone (python3 -, the spec filled in): copies, scrubs and counts. Nothing on Simone is changed but the
# copies in its own /tmp folder.
SCRUB = r'''
import json, os, re, sqlite3
spec = json.loads(__SPEC__)
pattern = re.compile(spec["pattern"])
place = set(spec["keys"])
out = {}

def counts(con):
    names = [r[0] for r in con.execute("select name from sqlite_master where type = 'table' and name not like 'sqlite_%' order by name")]
    return {t: con.execute("select count(*) from [%s]" % t).fetchone()[0] for t in names}

for group, (folder, dbs) in spec["live"].items():
    for name in dbs:
        src = os.path.join(os.path.expanduser(folder), name)
        if not os.path.exists(src):
            out[group + "/" + name] = {"missing": True}
            continue
        dst = os.path.join(spec["out"], group, name)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        a = sqlite3.connect("file:" + src + "?mode=ro", uri=True)
        b = sqlite3.connect(dst)
        live = counts(a)
        a.backup(b)
        a.close()
        b.execute("pragma secure_delete = on")  # what is scrubbed is overwritten, not only unlinked
        tables = {r[0] for r in b.execute("select name from sqlite_master where type = 'table'")}
        scrubbed = {}
        if "setting" in tables:
            gone = [k for (k,) in b.execute("select key from setting") if k in place or pattern.search(k)]
            b.executemany("delete from setting where key = ?", [(k,) for k in gone])
            scrubbed["setting"] = sorted(gone)
        for t in spec["tables"].get(name, []):
            if t in tables:
                scrubbed[t] = b.execute("delete from [%s]" % t).rowcount
        b.commit()
        b.execute("pragma wal_checkpoint(truncate)")
        b.execute("pragma journal_mode = delete")
        alembic = b.execute("select version_num from alembic_version").fetchone() if "alembic_version" in tables else None
        out[group + "/" + name] = {"live": live, "copy": counts(b), "scrubbed": scrubbed,
                                   "check": b.execute("pragma quick_check").fetchone()[0],
                                   "alembic": alembic[0] if alembic else None, "bytes": os.path.getsize(dst)}
        b.close()
print(json.dumps(out))
'''


def scrub_script(out: str) -> str:
    spec = {"out": out, "live": LIVE, "keys": list(PLACE_KEYS), "pattern": PLACE_KEY_PATTERN, "tables": PLACE_TABLES}
    return SCRUB.replace("__SPEC__", repr(json.dumps(spec)))


def live_copies(hw: ModuleType) -> Path:
    return hw.ROOT / "data" / "live-copies"


def env0_db(hw: ModuleType, group: str, name: str) -> Path:
    base = hw.data_dir(0) / "core" / "default" / "db" if group == "core" else hw.data_dir(0) / group
    return base / name


def ssh(args: list[str], stdin: str | None = None, timeout: int = 900) -> str:
    out = subprocess.run(["ssh", "-o", "BatchMode=yes", LIVE_HOST, *args], input=stdin, capture_output=True,
                         text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(f"ssh {LIVE_HOST} {' '.join(args)[:60]} failed: {(out.stderr or out.stdout).strip()[-800:]}")
    return out.stdout


def fetch(hw: ModuleType) -> Path:
    """Copy and scrub every live database on Simone, bring the copies here, check them: the copy's folder."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    remote = f"/tmp/hiro-live-copy-{stamp}"
    local = live_copies(hw) / stamp
    if local.exists():
        raise hw.Stop(f"{local} already exists: wait a minute and run again.")
    live_copies(hw).mkdir(parents=True, exist_ok=True)
    try:
        with hw.step(None, 0, "live copy on Simone"):
            meta = json.loads(ssh(["python3", "-"], stdin=scrub_script(remote)).strip().splitlines()[-1])
        with hw.step(None, 0, "bring the copies"):
            # Run from the copies' folder with a relative target: a Windows "C:" path reads as a host to scp
            hw.run(["scp", "-q", "-r", "-o", "BatchMode=yes", f"{LIVE_HOST}:{remote}", "."], cwd=live_copies(hw))
            (live_copies(hw) / Path(remote).name).rename(local)
    finally:
        ssh(["rm", "-rf", "--", remote], timeout=60)
    bad = []
    for key, m in meta.items():
        if m.get("missing"):
            continue
        path = local / key
        with contextlib.closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as con:
            here, check = counts(con), con.execute("pragma quick_check").fetchone()[0]
        if m["check"] != "ok" or check != "ok" or here != m["copy"]:
            bad.append(key)
    (local / "counts.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if bad:
        raise hw.Stop(f"The copies of {', '.join(bad)} don't check out here: nothing in env0 was changed ({local}).")
    return local


def place_restore(con: sqlite3.Connection, name: str) -> dict[str, int]:
    """In a new env0 database (main) with env0's old one attached (old): put back env0's per-place settings and
    tables. Rows put back, per table."""
    back: dict[str, int] = {}
    new, old = _tables(con), {r[0] for r in con.execute("select name from old.sqlite_master where type = 'table'")}
    if "setting" in new and "setting" in old:
        mine = [(k, v) for k, v in con.execute("select key, value from old.setting") if is_place_key(k)]
        con.executemany("delete from setting where key = ?",
                        [(r[0],) for r in con.execute("select key from setting").fetchall() if is_place_key(r[0])])
        con.executemany("insert into setting(key, value) values (?, ?)", mine)
        back["setting"] = len(mine)
    for t in PLACE_TABLES.get(name, []):
        if t in new and t in old:
            cols_new = [r[1] for r in con.execute(f"pragma main.table_info([{t}])")]
            cols_old = {r[1] for r in con.execute(f"pragma old.table_info([{t}])")}
            cols = ", ".join(f"[{c}]" for c in cols_new if c in cols_old)
            con.execute(f"delete from main.[{t}]")
            back[t] = con.execute(f"insert into main.[{t}] ({cols}) select {cols} from old.[{t}]").rowcount
    return back


def build(src: Path, old: Path | None, dst: Path, name: str) -> tuple[dict[str, int], dict[str, int]]:
    """dst = the live copy with env0's per-place rows from old (env0's database as it is): (counts, put back)."""
    dst.unlink(missing_ok=True)
    with contextlib.closing(sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)) as a, \
            contextlib.closing(sqlite3.connect(dst)) as b:
        a.backup(b)
    back: dict[str, int] = {}
    # Opened as a URI so the ATTACH below may be one too (env0's database read-only)
    with contextlib.closing(sqlite3.connect(f"file:{dst.as_posix()}", uri=True)) as con:
        if old is not None and old.exists():
            con.execute("attach database ? as old", (f"file:{old.as_posix()}?mode=ro",))
            with con:
                back = place_restore(con, name)
            con.execute("detach database old")
        if con.execute("pragma quick_check").fetchone()[0] != "ok":
            raise RuntimeError(f"{dst.name}: SQLite finds the new database unsound")
        return counts(con), back


def report(meta: dict, env0_now: dict[str, dict[str, int]], env0_after: dict[str, dict[str, int]] | None,
           backs: dict[str, dict[str, int]] | None = None) -> str:
    """Row counts per table: live, copy, env0 (now, or after the refresh)."""
    lines = []
    head = "env0 after" if env0_after is not None else "env0 now"
    for key, m in meta.items():
        if m.get("missing"):
            lines.append(f"\n{key}: not on Simone")
            continue
        lines.append(f"\n{key}  ({m['bytes'] / 2**20:.0f} MB, migrations at {m['alembic'] or '-'})")
        lines.append(f"  {'table':28} {'live':>9} {'copy':>9} {head:>11}  note")
        after = (env0_after or env0_now).get(key, {})
        for t in sorted(set(m["live"]) | set(m["copy"]) | set(after)):
            note = []
            s = m["scrubbed"].get(t)
            if isinstance(s, list) and s:
                note.append(f"not copied: {', '.join(s)}")
            elif isinstance(s, int):
                note.append(f"{s} row(s) not copied")
            if backs and t in backs.get(key, {}):
                note.append(f"env0's {backs[key][t]} kept")
            lv, cp, ev = m["live"].get(t, "-"), m["copy"].get(t, "-"), after.get(t, "-")
            if not note and isinstance(lv, int) and isinstance(cp, int) and lv != cp:
                note.append("live moved on during the copy" if cp > lv else "rows differ")
            lines.append(f"  {t:28} {lv:>9} {cp:>9} {ev:>11}  {'; '.join(note)}")
    return "\n".join(lines)


def env0_counts(hw: ModuleType, meta: dict) -> dict[str, dict[str, int]]:
    out = {}
    for key in meta:
        group, name = key.split("/")
        path = env0_db(hw, group, name)
        if path.exists():
            with contextlib.closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as con:
                out[key] = counts(con)
    return out


def latest(hw: ModuleType) -> Path | None:
    copies = sorted(p for p in live_copies(hw).glob("*") if (p / "counts.json").exists()) if live_copies(
        hw).exists() else []
    return copies[-1] if copies else None


def prune(hw: ModuleType) -> list[str]:
    copies = sorted(p for p in live_copies(hw).glob("*") if p.is_dir())
    old = copies[:-KEEP_COPIES]
    for p in old:
        shutil.rmtree(p)
    return [p.name for p in old]


def apply(hw: ModuleType, src: Path) -> None:
    """Put a live copy into env0: servers stopped, env0's databases moved to the archive, the copies in their place
    with env0's own settings, servers started again, row counts reported."""
    meta = json.loads((src / "counts.json").read_text(encoding="utf-8"))
    up = [n for n, s in hw.servers(0).items() if hw.listening(s.port)]
    archive = hw.ROOT / "archive" / f"env0-before-refresh-{datetime.now().strftime('%Y-%m-%d_%H%M')}"
    if up:
        with hw.step(None, 0, "env0 servers down"):
            hw.servers_down(0, up)
        still = [n for n, s in hw.servers(0).items() if hw.listening(s.port)]
        if still:
            raise hw.Stop(f"env0's {', '.join(still)} still run: stop them, then apply again. Nothing was changed.")
    # 1. Every new database beside env0's (".refresh"), env0's own rows put back; nothing replaced yet
    built: dict[str, tuple[Path, Path]] = {}
    backs: dict[str, dict[str, int]] = {}
    after: dict[str, dict[str, int]] = {}
    try:
        for key, m in meta.items():
            if m.get("missing"):
                continue
            group, name = key.split("/")
            target = env0_db(hw, group, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".refresh")
            with hw.step(None, 0, "build", key):
                after[key], backs[key] = build(src / group / name, target, tmp, name)
            built[key] = (tmp, target)
    except BaseException:
        for tmp, _ in built.values():
            tmp.unlink(missing_ok=True)
        raise
    # 2. Swap: env0's files (with their -wal and -shm) move to the archive, the new ones take their place
    with hw.step(None, 0, "swap"):
        for key, (tmp, target) in built.items():
            keep = archive / key
            keep.parent.mkdir(parents=True, exist_ok=True)
            for suffix in ("", "-wal", "-shm"):
                f = target.with_name(target.name + suffix)
                if f.exists():
                    shutil.move(str(f), str(keep.with_name(keep.name + suffix)))
            tmp.rename(target)
    text = report(meta, {}, after, backs)
    (archive / "report.txt").write_text(f"Live copy {src.name} into env0\n{text}\n", encoding="utf-8")
    hw.say(text)
    hw.say(f"\nenv0's databases before the refresh: {archive} (put them back by moving them in, servers stopped).")
    pruned = prune(hw)
    if pruned:
        hw.say(f"Older live copies pruned: {', '.join(pruned)}")
    if up:
        hw.cmd_up(type("A", (), {"env": 0, "servers": up, "wait": 120})())


def cmd_refresh_data(a, hw: ModuleType) -> None:
    """hiro-work refresh-data [--apply STAMP|latest]: fetch a live copy and show the plan; --apply puts it in env0."""
    if a.apply:
        src = latest(hw) if a.apply == "latest" else live_copies(hw) / a.apply
        if src is None or not (src / "counts.json").exists():
            raise hw.Stop(f"No live copy '{a.apply}' in {live_copies(hw)}.")
        apply(hw, src)
        return
    src = fetch(hw)
    meta = json.loads((src / "counts.json").read_text(encoding="utf-8"))
    hw.say(report(meta, env0_counts(hw, meta), None))
    up = [n for n, s in hw.servers(0).items() if hw.listening(s.port)]
    hw.say(f"\nLive copy ready: {src}")
    hw.say("Left out: " + "; ".join(LEFT_OUT) + ".")
    hw.say(f"env0's servers up now: {', '.join(up) or 'none'} (stopped and started again by --apply).")
    hw.say(f"Nothing in env0 changed. To put it in env0: hiro-work refresh-data --apply {src.name}")
