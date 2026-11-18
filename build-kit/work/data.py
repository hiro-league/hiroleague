r"""Data and real systems for hiro-work (hiro-docs standards/workflow.md, "Data and real systems").

What a copy holds, and how each piece comes along, is written in each repo's copy list (its data.toml, read by
copylist.py): the core's in the HiroLeague repo, each app's in its own. This module does what the lists say:

- **env1..env5 read, but don't write or spend, by default** (`make_safe`, `env_overrides`, `core_env`): their copy
  of env0's data reads the real systems as env0 does (Home Assistant, Frigate through HA, MQTT, NetHiro's health checks
  of the house), keeps no login that writes to one (the lists' `needs = "writes"` settings) and can start no AI call
  (the core's providers emptied), unless the task asks: `hiro-work start ... --no-real-reads`, `--real-writes`,
  `--real-ai`, or later `hiro-work real <task> --reads --writes --ai`. Sends and HA's automatic writes stay off either
  way, and sign-in is on, as in env0 (hiro_work.ENV_DEV_FORCED).
- **`hiro-work refresh-data`: live -> env0** (`cmd_refresh_data`). On Simone each live database the lists fetch
  (`live = "copy"`) is copied with SQLite's backup (as a deploy does) and scrubbed there of what is never copied (the
  lists' per-place settings and tables: tokens and logins, sign-in sessions, pairings); the copies come to
  C:\hiro\data\live-copies\<stamp>. `--apply <stamp>` then stops env0's servers, moves env0's databases to
  C:\hiro\archive (nothing is deleted), puts the live copies in their place with env0's own settings kept, starts the
  servers again, and reports row counts per table: live, copy, env0.
- **`hiro-work copy-list [--check]`** prints the lists; `--check` names what env0's and live's data folders hold that
  no list covers (copied nowhere until it is listed).

Standard library only: it runs on the system Python, beside hiro_work.py.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from types import ModuleType

import apps as appfile
import copylist
from copylist import CORE, CopyList

APPS = [a.repo for a in appfile.APPS if a.copy_data]  # the apps whose data an environment copies (apps.toml)
READS, WRITES, AI = "reads", "writes", "ai"  # what a task's copy in env1..env5 reaches (Task.real)
DEFAULT_REAL = [READS]  # a task started without flags, and an environment no task holds: reads, no writes, no AI

Lists = dict[str, CopyList]


def load(root: Path) -> Lists:
    """Every copy list, from the repos under root (hiro-work: env0's, the trunk's)."""
    return copylist.load_all(root, APPS)


def group_dir(data: Path, group: str) -> Path:
    """A group's data folder inside an environment's data folder (env1..env5; the core's is its workspace)."""
    return data / "core" / "default" if group == CORE else data / group


def settings_db(group: str) -> str:
    return appfile.BY_REPO[group].settings_db


# ------------------------------------------------------------------------------------------- env1..env5: safe


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}


def make_safe(data: Path, real: list[str], lists: Lists) -> list[str]:
    """Turn real systems off in an env1..env5 copy (its data folder), as the lists say: what it did, in words."""
    did: list[str] = []
    for group, lst in lists.items():
        base = group_dir(data, group)
        gone_keys = [s.key for s in lst.settings if s.needs and s.needs not in real]
        db = base / settings_db(group) if group != CORE else None
        if gone_keys and db is not None and db.exists():
            with contextlib.closing(sqlite3.connect(db)) as con, con:
                if "setting" in _tables(con):
                    for words in ("reads", "writes"):
                        keys = [s.key for s in lst.settings if s.needs == words and words not in real]
                        if not keys:
                            continue
                        n = con.execute(f"delete from setting where key in ({','.join('?' * len(keys))})",
                                        keys).rowcount
                        if n:
                            did.append(f"{group}: {n} setting(s) that {words} a real system left out")
        for sw in lst.switches:
            if sw.unless is not None and sw.unless in real:
                continue
            path = base / sw.path
            if not path.exists():
                continue
            if sw.table is not None:
                with contextlib.closing(sqlite3.connect(path)) as con, con:
                    if sw.table not in _tables(con):
                        continue
                    n = con.execute(f"update [{sw.table}] set [{sw.column}] = ? where [{sw.column}] is not ?",
                                    (sw.value, sw.value)).rowcount
                if n:
                    did.append(f"{group}: {n} {sw.table} row(s) off ({sw.why})")
            else:
                doc = json.loads(path.read_text(encoding="utf-8-sig"))
                if doc.get(sw.key) != sw.value:
                    before = doc.get(sw.key)
                    doc[sw.key] = sw.value
                    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
                    count = f"{len(before)} " if isinstance(before, (list, dict)) else ""
                    did.append(f"{group}: {sw.path}'s {count}{sw.key} left out ({sw.why})")
    return did


def env_overrides(app: str, real: list[str], lists: Lists) -> dict[str, str | None]:
    """An app's .env.dev lines in env1..env5 besides OUTPUTS, HA_AUTO_WRITES and AUTH: a value is written, None
    drops env0's line (the app's default is then off)."""
    lst = lists.get(app)
    if lst is None:
        return {}
    return {e.name: (None if e.drop else e.value) for e in lst.env if e.name and e.applies(real)}


def core_env(environ: dict[str, str], real: list[str], lists: Lists) -> dict[str, str]:
    """Extra environment for an env1..env5 core: the variables the core's list matches (provider keys in the PC's
    environment) blanked; an empty value removes the variable in the server's PowerShell runner."""
    out: dict[str, str] = {}
    for e in lists[CORE].env:
        if not e.applies(real):
            continue
        if e.match:
            out.update({k: ("" if e.drop else e.value or "") for k in environ if re.search(e.match, k)})
        elif e.name:
            out[e.name] = "" if e.drop else e.value or ""
    return out


def link_pictures(src: Path, dst: Path, app: str, lists: Lists) -> list[str]:
    """An env1..env5 app folder gets env0's folders its list links (`envs = "link"`) as hard links: same drive, so
    instant and no extra space. A file a task adds stays in its environment and deleting one there removes only its
    link; editing one in place would change env0's too (these apps write a picture once)."""
    lines = []
    lst = lists.get(app)
    for item in lst.folders("envs", "link") if lst else []:
        folder = item.path
        if not (src / folder).is_dir():
            continue
        linked = copied = 0
        for path in (src / folder).rglob("*"):
            target = dst / folder / path.relative_to(src / folder)
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.unlink(missing_ok=True)
            try:
                os.link(path, target)
                linked += 1
            except OSError:  # another drive, or a file system without hard links: a copy instead
                shutil.copy2(path, target)
                copied += 1
        lines.append(f"{app}/{folder}: {linked} file(s) linked" + (f", {copied} copied" if copied else ""))
    return lines


def copy_db(src: Path, dst: Path) -> None:
    """A consistent copy of a SQLite database, even while env0's server writes to it (what's in the WAL comes too)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    with contextlib.closing(sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)) as a, \
            contextlib.closing(sqlite3.connect(dst)) as b:
        a.backup(b)


def listing(folder: Path, group: str) -> list[str]:
    """A data folder's names as its list names them: top-level, and the core's db/ files as db/<name>."""
    if not folder.is_dir():
        return []
    names = sorted(p.name for p in folder.iterdir())
    if group == CORE and (folder / "db").is_dir():
        names = [n for n in names if n != "db"] + sorted(f"db/{p.name}" for p in (folder / "db").iterdir())
    return names


def copy_group(src: Path, dst: Path, group: str, lists: Lists) -> list[str]:
    """env0's data folder of a group into an environment's, as its list says (`envs`): databases with SQLite's backup,
    files and folders copied, picture folders hard-linked, the rest left out. What it did, in words: what was linked,
    what couldn't be read (an optional item), and what env0's folder holds that the list doesn't name."""
    lst = lists[group]
    lines: list[str] = []
    for item in lst.items:
        if item.envs != "copy" or item.pattern:
            continue
        s, d = src / item.path, dst / item.path
        if not s.exists():
            continue
        try:
            if item.kind == "database":
                copy_db(s, d)
            elif item.kind == "folder":
                shutil.copytree(s, d)
            else:
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, d)
        except OSError as exc:
            if not item.optional:
                raise
            lines.append(f"{group}/{item.path}: not copied ({exc.strerror or exc}); {item.why}")
    if group != CORE:
        lines += link_pictures(src, dst, group, lists)
    left = copylist.unlisted(lst, listing(src, group))
    if left:
        lines.append(f"! {group}: not in its copy list, so not copied: {', '.join(left)}")
    return lines


def describe(real: list[str]) -> str:
    """The card's line about real systems."""
    reads = "real reads (HA, Frigate, MQTT, health checks)" if READS in real else "real reads off"
    writes = "writes ON (TrainHiro's Frigate, AdGuard rules)" if WRITES in real else "writes off"
    ai = "AI ON (the copied providers)" if AI in real else "AI off"
    return f"{reads} | {writes} | {ai} | sends and HA's automatic writes off | sign-in on"


# ------------------------------------------------------------------------------------------- live -> env0

LIVE_HOST = "simone"
KEEP_COPIES = 3  # live copies kept on the PC; older ones are pruned


def live_spec(lists: Lists) -> dict:
    """What the scrub on Simone needs, from the lists: each group's live folder and the databases it fetches, the
    per-place setting keys (the kit's, every app's own) and pattern, and each database's per-place tables."""
    every = lists[CORE].every_app
    return {
        "live": {g: (lst.live, [i.path for i in lst.databases("live")]) for g, lst in lists.items()},
        "keys": {g: sorted({*every.place_keys, *(s.key for s in lst.settings)}) for g, lst in lists.items()},
        "pattern": every.place_key_pattern,
        "tables": {f"{g}/{i.path}": list(i.place_tables) for g, lst in lists.items() for i in lst.databases("live")},
    }


def is_place_key(key: str, group: str, lists: Lists) -> bool:
    every = lists[CORE].every_app
    return (key in every.place_keys or any(s.key == key for s in lists[group].settings)
            or re.search(every.place_key_pattern, key) is not None)


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
out = {}

def counts(con):
    names = [r[0] for r in con.execute("select name from sqlite_master where type = 'table' and name not like 'sqlite_%' order by name")]
    return {t: con.execute("select count(*) from [%s]" % t).fetchone()[0] for t in names}

for group, (folder, dbs) in spec["live"].items():
    place = set(spec["keys"][group])
    for name in dbs:
        key = group + "/" + name
        src = os.path.join(os.path.expanduser(folder), name)
        if not os.path.exists(src):
            out[key] = {"missing": True}
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
        for t in spec["tables"].get(key, []):
            if t in tables:
                scrubbed[t] = b.execute("delete from [%s]" % t).rowcount
        b.commit()
        b.execute("pragma wal_checkpoint(truncate)")
        b.execute("pragma journal_mode = delete")
        alembic = b.execute("select version_num from alembic_version").fetchone() if "alembic_version" in tables else None
        out[key] = {"live": live, "copy": counts(b), "scrubbed": scrubbed,
                    "check": b.execute("pragma quick_check").fetchone()[0],
                    "alembic": alembic[0] if alembic else None, "bytes": os.path.getsize(dst)}
        b.close()
print(json.dumps(out))
'''


def scrub_script(out: str, lists: Lists) -> str:
    return SCRUB.replace("__SPEC__", repr(json.dumps({"out": out, **live_spec(lists)})))


def live_copies(hw: ModuleType) -> Path:
    return hw.ROOT / "data" / "live-copies"


def env0_group(hw: ModuleType, group: str) -> Path:
    """A group's data folder in env0 (Code reports keeps env0's in its repo's data/)."""
    return hw.data_dir(0) / "core" / "default" if group == CORE else hw.app_data(0, appfile.BY_REPO[group])


def env0_db(hw: ModuleType, key: str) -> Path:
    group, path = key.split("/", 1)
    return env0_group(hw, group) / path


def ssh(args: list[str], stdin: str | None = None, timeout: int = 900) -> str:
    out = subprocess.run(["ssh", "-o", "BatchMode=yes", LIVE_HOST, *args], input=stdin, capture_output=True,
                         text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(f"ssh {LIVE_HOST} {' '.join(args)[:60]} failed: {(out.stderr or out.stdout).strip()[-800:]}")
    return out.stdout


def fetch(hw: ModuleType, lists: Lists) -> Path:
    """Copy and scrub every live database the lists fetch on Simone, bring the copies here, check them: the copy's
    folder."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    remote = f"/tmp/hiro-live-copy-{stamp}"
    local = live_copies(hw) / stamp
    if local.exists():
        raise hw.Stop(f"{local} already exists: wait a minute and run again.")
    live_copies(hw).mkdir(parents=True, exist_ok=True)
    try:
        with hw.step(None, 0, "live copy on Simone"):
            meta = json.loads(ssh(["python3", "-"], stdin=scrub_script(remote, lists)).strip().splitlines()[-1])
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


def place_restore(con: sqlite3.Connection, key: str, lists: Lists) -> dict[str, int]:
    """In a new env0 database (main) with env0's old one attached (old): put back env0's per-place settings and
    tables, as the database's list names them. Rows put back, per table."""
    group, path = key.split("/", 1)
    back: dict[str, int] = {}
    new, old = _tables(con), {r[0] for r in con.execute("select name from old.sqlite_master where type = 'table'")}
    if "setting" in new and "setting" in old:
        mine = [(k, v) for k, v in con.execute("select key, value from old.setting") if is_place_key(k, group, lists)]
        con.executemany("delete from setting where key = ?",
                        [(r[0],) for r in con.execute("select key from setting").fetchall()
                         if is_place_key(r[0], group, lists)])
        con.executemany("insert into setting(key, value) values (?, ?)", mine)
        back["setting"] = len(mine)
    item = lists[group].item(path)
    for t in item.place_tables if item else ():
        if t in new and t in old:
            cols_new = [r[1] for r in con.execute(f"pragma main.table_info([{t}])")]
            cols_old = {r[1] for r in con.execute(f"pragma old.table_info([{t}])")}
            cols = ", ".join(f"[{c}]" for c in cols_new if c in cols_old)
            con.execute(f"delete from main.[{t}]")
            back[t] = con.execute(f"insert into main.[{t}] ({cols}) select {cols} from old.[{t}]").rowcount
    return back


def build(src: Path, old: Path | None, dst: Path, key: str, lists: Lists) -> tuple[dict[str, int], dict[str, int]]:
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
                back = place_restore(con, key, lists)
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


def left_out(lists: Lists) -> list[str]:
    """What a refresh never fetches, per group, as the lists say: env0 keeps its own."""
    return [f"{g}: {', '.join(i.path for i in lst.items if i.live == 'own')}" for g, lst in lists.items()]


def env0_counts(hw: ModuleType, meta: dict) -> dict[str, dict[str, int]]:
    out = {}
    for key in meta:
        path = env0_db(hw, key)
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


def live_file_count(folder: str) -> int:
    return int(ssh(["find", folder, "-type", "f"], timeout=120).count("\n"))


def copy_files(hw: ModuleType, archive: Path, lists: Lists) -> list[str]:
    """The folders the lists fetch from live (`live = "copy"`: the pictures the databases point at) into env0, as a
    tar stream over ssh into a folder beside env0's; env0's own folder moves to the archive. One line per folder with
    its file counts, live and env0."""
    lines = []
    for group, lst in lists.items():
        for item in lst.folders("live", "copy"):
            folder = item.path
            target = env0_group(hw, group) / folder
            stage = env0_group(hw, group) / f".{folder}.refresh"
            if stage.exists():
                shutil.rmtree(stage)
            stage.mkdir(parents=True)
            with hw.step(None, 0, "files", f"{group}/{folder}"):
                live = live_file_count(f"{lst.live}/{folder}")
                sender = subprocess.Popen(["ssh", "-o", "BatchMode=yes", LIVE_HOST, "tar", "-C", lst.live,
                                           "-cf", "-", folder], stdout=subprocess.PIPE)
                # Windows' own tar (bsdtar): Git's GNU tar reads "C:" in a path as a remote host
                tar = str(Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "tar.exe")
                got = subprocess.run([tar, "-xf", "-", "-C", str(stage)], stdin=sender.stdout, capture_output=True)
                sender.stdout.close()
                if sender.wait() != 0 or got.returncode != 0:
                    shutil.rmtree(stage)
                    raise hw.Stop(f"Copying {group}/{folder} failed: {got.stderr.decode(errors='replace')[-500:]}")
                here = sum(1 for p in (stage / folder).rglob("*") if p.is_file())
                if here != live:
                    shutil.rmtree(stage)
                    raise hw.Stop(f"{group}/{folder}: {live} files on Simone, {here} arrived. env0 unchanged.")
                if target.exists():
                    keep = archive / group / folder
                    keep.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target), str(keep))
                (stage / folder).rename(target)
                stage.rmdir()
            lines.append(f"{group}/{folder}: {live} files on Simone, {here} in env0")
    return lines


def apply(hw: ModuleType, src: Path, lists: Lists) -> None:
    """Put a live copy into env0: servers stopped, env0's databases moved to the archive, the copies in their place
    with env0's own settings, servers started again, row counts reported."""
    meta = json.loads((src / "counts.json").read_text(encoding="utf-8"))
    # Live copies from before the copy lists name the core's databases without their db/ folder; no shim for them,
    # the code is young: fetch a new copy instead (working-rules.md, "No backward compatibility")
    unknown = [k for k in meta if k.split("/", 1)[0] not in lists
               or lists[k.split("/", 1)[0]].item(k.split("/", 1)[1]) is None]
    if unknown:
        raise hw.Stop(f"{src.name} holds {', '.join(unknown)}, which no copy list names: fetch a new copy "
                      "(hiro-work refresh-data). Nothing was changed.")
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
            target = env0_db(hw, key)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".refresh")
            with hw.step(None, 0, "build", key):
                after[key], backs[key] = build(src / key, target, tmp, key, lists)
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
    text = report(meta, {}, after, backs) + "\n\nFiles:\n" + "\n".join(copy_files(hw, archive, lists))
    (archive / "report.txt").write_text(f"Live copy {src.name} into env0\n{text}\n", encoding="utf-8")
    hw.say(text)
    hw.say(f"\nenv0's databases before the refresh: {archive} (put them back by moving them in, servers stopped).")
    pruned = prune(hw)
    if pruned:
        hw.say(f"Older live copies pruned: {', '.join(pruned)}")
    if up:
        hw.cmd_up(type("A", (), {"env": 0, "servers": up, "wait": 120})())


def cmd_refresh_data(a, hw: ModuleType) -> None:
    """hiro-work refresh-data [--apply STAMP|latest] [--files]: fetch a live copy and show the plan; --apply puts it
    in env0; --files copies only the folders the lists fetch (the pictures), env0's servers down."""
    lists = load(hw.env_dir(0))
    if getattr(a, "files", False):
        if [n for n, s in hw.servers(0).items() if hw.listening(s.port)]:
            raise hw.Stop("env0's servers are up: hiro-work down 0 first (or use --apply, which stops them).")
        archive = hw.ROOT / "archive" / f"env0-before-refresh-{datetime.now().strftime('%Y-%m-%d_%H%M')}-files"
        for line in copy_files(hw, archive, lists):
            hw.say(line)
        if archive.exists():
            hw.say(f"env0's folders before: {archive}")
        return
    if a.apply:
        src = latest(hw) if a.apply == "latest" else live_copies(hw) / a.apply
        if src is None or not (src / "counts.json").exists():
            raise hw.Stop(f"No live copy '{a.apply}' in {live_copies(hw)}.")
        apply(hw, src, lists)
        return
    src = fetch(hw, lists)
    meta = json.loads((src / "counts.json").read_text(encoding="utf-8"))
    hw.say(report(meta, env0_counts(hw, meta), None))
    up = [n for n, s in hw.servers(0).items() if hw.listening(s.port)]
    hw.say(f"\nLive copy ready: {src}")
    hw.say("Never fetched (env0 keeps its own), per the copy lists:\n  " + "\n  ".join(left_out(lists)))
    hw.say(f"env0's servers up now: {', '.join(up) or 'none'} (stopped and started again by --apply).")
    hw.say(f"Nothing in env0 changed. To put it in env0: hiro-work refresh-data --apply {src.name}")


# ------------------------------------------------------------------------------------------- the lists, shown


def show(lists: Lists) -> str:
    """Every list as text: each item's two copies and why, the per-place settings, the switches and .env lines."""
    out = []
    for group, lst in lists.items():
        out.append(f"\n{group}  (live: {lst.live}; list: {copylist.repo_of(group)}/{copylist.FILE})")
        for i in lst.items:
            extra = f"; per place (env0 keeps its own): {', '.join(i.place_tables)}" if i.place_tables else ""
            out.append(f"  {i.path:24} {i.kind:8} live: {i.live:4}  envs: {i.envs:4}  {i.why}{extra}")
        for s in lst.settings:
            out.append(f"  setting {s.key:16} per place{f', needs real {s.needs}' if s.needs else ''}: {s.why}")
        for sw in lst.switches:
            what = f"{sw.table}.{sw.column}" if sw.table else sw.key
            out.append(f"  switch  {sw.path}: {what} = {sw.value!r}{f' unless {sw.unless}' if sw.unless else ''}: "
                       f"{sw.why}")
        for e in lst.env:
            val = "dropped" if e.drop else repr(e.value)
            out.append(f"  env     {e.name or e.match} {val}{f' unless {e.unless}' if e.unless else ''}: {e.why}")
    return "\n".join(out)


def live_listing(lst: CopyList, group: str) -> list[str]:
    """A group's live data folder's names, as listing() gives env0's."""
    folder = lst.live
    names = ssh(["ls", "-1A", folder], timeout=60).split()
    if group == CORE and "db" in names:
        names = [n for n in names if n != "db"] + [f"db/{n}" for n in ssh(["ls", "-1A", f"{folder}/db"],
                                                                         timeout=60).split()]
    return sorted(names)


def cmd_copy_list(a, hw: ModuleType) -> None:
    """hiro-work copy-list [--check]: every copy list; --check also names what env0's and live's data folders hold that
    no list covers."""
    lists = load(hw.env_dir(0))
    hw.say(show(lists))
    if not a.check:
        return
    hw.say("\nNot in a copy list (copied nowhere until it is listed):")
    found = False
    for group, lst in lists.items():
        for place, names in (("env0", listing(env0_group(hw, group), group)), ("live", live_listing(lst, group))):
            left = copylist.unlisted(lst, names)
            if left:
                found = True
                hw.say(f"  {group} in {place}: {', '.join(left)}")
    if not found:
        hw.say("  nothing: every file in env0's and live's data folders is listed.")
