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
import shlex
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
    """Every copy list, from the repos under root (hiro-work: env0's, main's)."""
    return copylist.load_all(root, APPS)


def group_dir(data: Path, group: str) -> Path:
    """A group's data folder inside an environment's data folder (env1..env5; the core's is its workspace)."""
    return data / "core" / "default" if group == CORE else data / group


def settings_db(group: str) -> str:
    return appfile.BY_REPO[group].settings_db


# ------------------------------------------------------------------------------------------- env1..env5: safe


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}


def make_safe(data: Path, real: list[str], lists: Lists, store: dict[str, str] | None = None) -> list[str]:
    """Turn real systems off in an env1..env5 copy (its data folder), as the lists say, then give it the secrets of
    the systems its task asked for from the PC's store (give_secrets): what it did, in words."""
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
    if store is not None:
        did += give_secrets(data, real, lists, store)[0]
    return did


def env_overrides(app: str, real: list[str], lists: Lists) -> dict[str, str | None]:
    """An app's .env.dev lines in env1..env5 besides OUTPUTS, HA_AUTO_WRITES and AUTH: a value is written, None
    drops env0's line (the app's default is then off)."""
    lst = lists.get(app)
    if lst is None:
        return {}
    return {e.name: (None if e.drop else e.value) for e in lst.env if e.name and e.applies(real)}


def core_env(environ: dict[str, str], real: list[str], lists: Lists,
             store: dict[str, str] | None = None) -> dict[str, str]:
    """Extra environment for an env1..env5 core: the variables the core's list matches (provider keys in the PC's
    environment) blanked, an empty value removing the variable in the server's PowerShell runner; then, while the task
    has real AI, the AI keys from the PC's store (the core's env secrets)."""
    out: dict[str, str] = {}
    for e in lists[CORE].env:
        if not e.applies(real):
            continue
        if e.match:
            out.update({k: ("" if e.drop else e.value or "") for k in environ if re.search(e.match, k)})
        elif e.name:
            out[e.name] = "" if e.drop else e.value or ""
    for x in lists[CORE].secrets:  # the store's keys, set above, win over the blanking
        if x.env and x.when and x.when in real and store and x.name in store:
            out[x.env] = store[x.name]
    return out


def link_pictures(src: Path, dst: Path, app: str, lists: Lists) -> list[str]:
    """An env1..env5 app folder gets env0's folders its list links (`envs = "link"`) as hard links: same drive, so
    instant and no extra space. A file a task adds stays in its environment and deleting one there removes only its
    link. A change there replaces only its link too: the apps write through the backend kit's `files`, which writes a
    new file and renames it over the old one, never into it."""
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


def live_file_count(folder: str) -> int | None:
    """The files in a live folder, or None when Simone has no such folder (nothing uploaded there yet)."""
    if ssh(["test", "-d", folder, "&&", "echo", "yes", "||", "echo", "no"], timeout=60).strip() != "yes":
        return None
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
            live = live_file_count(f"{lst.live}/{folder}")
            if live is None:
                lines.append(f"{group}/{folder}: not on Simone, env0's left as it is")
                continue
            if stage.exists():
                shutil.rmtree(stage)
            stage.mkdir(parents=True)
            with hw.step(None, 0, "files", f"{group}/{folder}"):
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


def unknown_keys(meta: dict, lists: Lists) -> list[str]:
    """A live copy's databases that no copy list names as a database (a copy from before the lists named the core's
    without their db/ folder)."""
    out = []
    for key in meta:
        group, _, path = key.partition("/")
        item = lists[group].item(path) if group in lists else None
        if item is None or item.kind != "database":
            out.append(key)
    return out


def apply(hw: ModuleType, src: Path, lists: Lists) -> None:
    """Put a live copy into env0: servers stopped, env0's databases moved to the archive, the copies in their place
    with env0's own settings, servers started again, row counts reported."""
    meta = json.loads((src / "counts.json").read_text(encoding="utf-8"))
    # Live copies from before the copy lists name the core's databases without their db/ folder; no shim for them,
    # the code is young: fetch a new copy instead (working-rules.md, "No backward compatibility")
    unknown = unknown_keys(meta, lists)
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
    write_source(hw, 0, "live", stamp=src.name, live_at=stamp_time(src.name))
    (archive / "report.txt").write_text(f"Live copy {src.name} into env0\n{text}\n", encoding="utf-8")
    hw.say(text)
    hw.say(f"\nenv0's databases before the refresh: {archive} (put them back by moving them in, servers stopped).")
    pruned = prune(hw)
    if pruned:
        hw.say(f"Older live copies pruned: {', '.join(pruned)}")
    if up:
        hw.cmd_up(type("A", (), {"env": 0, "servers": up, "wait": 120})())


def cmd_refresh_data(a, hw: ModuleType) -> None:
    """hiro-work refresh-data [--apply STAMP|latest] [--now] [--files]: fetch a live copy and show the plan; --apply
    puts it in env0; --now fetches and applies in one go; --files copies only the folders the lists fetch (the
    pictures), env0's servers down."""
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
    if getattr(a, "now", False):  # Refresh from live: a new copy, then into env0, in one go
        apply(hw, fetch(hw, lists), lists)
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


PLACES = ("env0", "live")


def tree_bytes(path: Path) -> int:
    """A file's or folder's size on disk, in bytes (a hard-linked file counts in each folder that has it)."""
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            with contextlib.suppress(OSError):  # a file that went while it was counted
                total += os.stat(os.path.join(root, f)).st_size
    return total


def live_bytes(lst: CopyList, names: list[str]) -> dict[str, int]:
    """Each name's size in a live data folder, in bytes (du on Simone, one call)."""
    if not names:
        return {}
    # The live folder as live_listing names it (a ~ path of the lists' own, so the remote shell expands it)
    out = ssh(["cd", lst.live, "&&", "du", "-sb", "--",
               *[shlex.quote(n) for n in names]], timeout=600)
    sizes = {}
    for line in out.splitlines():
        size, _, name = line.partition("	")
        if size.isdigit():
            sizes[name] = int(size)
    return sizes


def survey(hw: ModuleType, lists: Lists, place: str, measure: bool = True) -> dict:
    """One place's data folders (env0's or live's) against the copy lists: what no list covers (`unlisted`, copied
    nowhere until it is listed: [{group, names}]) and, when measured, each listed item's size there (`sizes`:
    {group: {path: bytes}}, a pattern's files added up)."""
    unlisted, sizes = [], {}
    for group, lst in lists.items():
        folder = env0_group(hw, group)
        names = listing(folder, group) if place == "env0" else live_listing(lst, group)
        left = copylist.unlisted(lst, names)
        if left:
            unlisted.append({"group": group, "names": left})
        if not measure:
            continue
        measured = ({n: tree_bytes(folder / n) for n in names} if place == "env0" else live_bytes(lst, names))
        per: dict[str, int] = {}
        for name, size in measured.items():
            item = lst.item(re.sub(r"-(wal|shm|journal)$", "", name)) or lst.item(name)
            if item:
                per[item.path] = per.get(item.path, 0) + size
        sizes[group] = per
    return {"unlisted": unlisted, "sizes": sizes}


def drift(hw: ModuleType, lists: Lists, places: tuple[str, ...] = PLACES) -> list[dict]:
    """What env0's or live's data folders hold that no copy list covers: [{group, place, names}], unmeasured."""
    return [{**u, "place": place} for place in places for u in survey(hw, lists, place, measure=False)["unlisted"]]


def report_drift(hw: ModuleType, lists: Lists, places: tuple[str, ...] = PLACES) -> list[dict]:
    """Each place surveyed and measured, and a "copy-lists" event per place: CodeHiro's Work › Sweep and Work › Data
    show the latest of each (run by copy-list --check, the PC's helper for env0, the deploy for live). What no
    list covers, as drift() says it."""
    found = []
    for place in places:
        s = survey(hw, lists, place)
        hw.event(task=None, env=None, step="copy-lists", phase="end", ok=True, place=place, **s)
        found += [{**u, "place": place} for u in s["unlisted"]]
    return found


def said_drift(found: list[dict]) -> list[str]:
    return [f"  {f['group']} in {f['place']}: {', '.join(f['names'])}" for f in found] or [
        "  nothing: every file in the data folders looked at is listed."]


def cmd_copy_list(a, hw: ModuleType) -> None:
    """hiro-work copy-list [--check]: every copy list; --check also names what env0's and live's data folders hold that
    no list covers, and tells CodeHiro."""
    lists = load(hw.env_dir(0))
    hw.say(show(lists))
    if not a.check:
        return
    hw.say("\nNot in a copy list (copied nowhere until it is listed):")
    for line in said_drift(report_drift(hw, lists)):
        hw.say(line)


# ------------------------------------------------------------------------- each environment's data source

SOURCE_FILE = "source.json"  # in an environment's data folder: where its data came from, and when
SOURCES = ("env0", "vanilla", "live")  # what a task's environment starts from (live: a live copy, by its stamp)
FRESH_FOR_S = 3600  # a live copy younger than this is used as it is; an older one is fetched again first
STAMP = "%Y-%m-%d_%H%M"


def stamp_time(stamp: str) -> str:
    """A live copy's stamp (its folder's name) as the ISO time it was fetched."""
    return datetime.strptime(stamp, STAMP).astimezone().isoformat(timespec="seconds")


def parse_source(text: str) -> tuple[str, str | None]:
    """"env0", "vanilla", "live" (the latest live copy, fetched again when older than an hour) or "live:<stamp>"."""
    source, _, stamp = text.partition(":")
    if source not in SOURCES or (stamp and source != "live"):
        raise ValueError(f"no data source {text!r}: env0, vanilla, live or live:<stamp>")
    if stamp:
        stamp_time(stamp)  # a stamp that isn't one stops here
    return source, stamp or None


def write_source(hw: ModuleType, env: int, source: str, stamp: str | None = None,
                 live_at: str | None = None) -> dict:
    """Record where an environment's data came from: source (env0's "live" is a refresh from live), when it was made,
    when it left live (None: vanilla), and the live copy's stamp. The PC's helper tells CodeHiro (relay.py)."""
    rec = {"source": source, "made_at": datetime.now().astimezone().isoformat(timespec="seconds"),
           "live_at": live_at, "stamp": stamp}
    path = hw.data_dir(env) / SOURCE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


def read_source(hw: ModuleType, env: int) -> dict | None:
    """An environment's recorded data source; None when it has none. env0 before its first record: worked out from
    the last refresh's report in the archive (its first line names the live copy)."""
    path = hw.data_dir(env) / SOURCE_FILE
    if path.exists():
        with contextlib.suppress(OSError, ValueError):
            return json.loads(path.read_text(encoding="utf-8"))
    if env != 0:
        return None
    reports = sorted((hw.ROOT / "archive").glob("env0-before-refresh-*/report.txt"))
    for report in reversed(reports):
        m = re.match(r"Live copy (\S+) into env0", report.read_text(encoding="utf-8").splitlines()[0])
        if m:
            made = report.parent.name.removeprefix("env0-before-refresh-")[:15]
            with contextlib.suppress(ValueError):
                return {"source": "live", "made_at": stamp_time(made), "live_at": stamp_time(m.group(1)),
                        "stamp": m.group(1)}
    return None


def describe_source(rec: dict | None) -> str:
    """The work card's line about where the data came from."""
    if not rec:
        return "data: not recorded yet"
    left = f", which left live {rec['live_at'][:16].replace('T', ' ')}" if rec.get("live_at") else ""
    return {"env0": f"data: env0's copy{left}", "vanilla": "data: vanilla (a fresh install, no family data)",
            "live": f"data: a live copy{left}"}.get(rec["source"], f"data: {rec['source']}")


def live_copy_list(hw: ModuleType) -> list[dict]:
    """The live copies on the PC, the newest first: stamp, when fetched, size, databases, rows, and whether env0 holds
    it now (its recorded source)."""
    held = (read_source(hw, 0) or {}).get("stamp")
    out = []
    if not live_copies(hw).exists():
        return out
    for d in sorted(live_copies(hw).iterdir(), reverse=True):
        meta_file = d / "counts.json"
        if not meta_file.exists():
            continue
        with contextlib.suppress(OSError, ValueError):
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            dbs = [m for m in meta.values() if not m.get("missing")]
            out.append({"stamp": d.name, "fetched_at": stamp_time(d.name),
                        "bytes": sum(p.stat().st_size for p in d.rglob("*") if p.is_file()),
                        "databases": len(dbs), "rows": sum(sum(m.get("copy", {}).values()) for m in dbs),
                        "in_env0": d.name == held})
    return out


def fresh_copy(hw: ModuleType, lists: Lists, stamp: str | None = None) -> Path:
    """A live copy for an environment: the one named, else the latest when younger than an hour, else a new fetch."""
    if stamp:
        src = live_copies(hw) / stamp
        if not (src / "counts.json").exists():
            raise hw.Stop(f"No live copy '{stamp}' in {live_copies(hw)}.")
        return src
    src = latest(hw)
    if src is not None and (datetime.now().astimezone() - datetime.fromisoformat(stamp_time(src.name))
                            ).total_seconds() < FRESH_FOR_S:
        return src
    return fetch(hw, lists)


def copy_live_into(hw: ModuleType, env: int, src: Path, lists: Lists) -> list[str]:
    """A live copy's databases into an environment whose data was just copied from env0: each database is rebuilt
    from the live copy with the environment's own per-place rows (env0's, just copied) put back, as an apply does in
    env0. The files (pictures, keys) stay env0's. What it did, in words."""
    meta = json.loads((src / "counts.json").read_text(encoding="utf-8"))
    unknown = unknown_keys(meta, lists)
    if unknown:
        raise hw.Stop(f"{src.name} holds {', '.join(unknown)}, which no copy list names: use a newer copy (hiro-work "
                      "data <env> live fetches one). Nothing was changed.")
    lines = []
    for key, m in meta.items():
        if m.get("missing"):
            continue
        group, path = key.split("/", 1)
        target = group_dir(hw.data_dir(env), group) / path
        tmp = target.with_name(target.name + ".live")
        target.parent.mkdir(parents=True, exist_ok=True)
        build(src / key, target if target.exists() else None, tmp, key, lists)
        for suffix in ("", "-wal", "-shm"):
            target.with_name(target.name + suffix).unlink(missing_ok=True)
        tmp.rename(target)
        lines.append(f"{key}: from live copy {src.name}")
    return lines


# ------------------------------------------------------------------------- the PC's dev secrets

def store_path(hw: ModuleType) -> Path:
    """The PC's dev secrets: one JSON file of name -> value, out of git (C:\\hiro\\secrets\\dev); never printed."""
    return hw.ROOT / "secrets" / "dev" / "secrets.json"


def read_store(hw: ModuleType) -> dict[str, str]:
    path = store_path(hw)
    if not path.exists():
        return {}
    return {str(k): str(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}


def write_store(hw: ModuleType, store: dict[str, str]) -> None:
    path = store_path(hw)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(dict(sorted(store.items())), indent=2), encoding="utf-8")
    tmp.replace(path)


def secrets_of(lists: Lists) -> dict[str, list[tuple[str, copylist.Secret]]]:
    """Each secret's name, and the groups that use it (one name may serve two apps: HomeHiro's and NetHiro's HA
    token)."""
    out: dict[str, list[tuple[str, copylist.Secret]]] = {}
    for group, lst in lists.items():
        for x in lst.secrets:
            out.setdefault(x.name, []).append((group, x))
    return out


def fill_store(hw: ModuleType, lists: Lists, environ: dict[str, str]) -> list[str]:
    """The store's first fill: each secret it lacks, from env0's settings (a setting secret) or the PC's environment
    (an env secret). A folder secret is never taken. The names it took, never the values."""
    store = read_store(hw)
    took = []
    for name, uses in secrets_of(lists).items():
        if name in store:
            continue
        for group, x in uses:
            value = None
            if x.env:
                value = environ.get(x.env)
            elif x.setting and group != CORE:
                db = env0_group(hw, group) / settings_db(group)
                if db.exists():
                    with contextlib.closing(sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)) as con:
                        if "setting" in _tables(con):
                            row = con.execute("select value from setting where key = ?", (x.setting,)).fetchone()
                            value = row[0] if row else None
            if value:
                store[name] = value
                took.append(name)
                break
    if took:
        write_store(hw, store)
    return took


def give_secrets(data: Path, real: list[str], lists: Lists, store: dict[str, str]) -> tuple[list[str], list[str]]:
    """An env1..env5 copy's secrets: a secret's setting row is always taken out of the copy (env0's value never
    stays), and put back from the store only while the task has its real system. (what it did, in words; the names
    the store lacks for a system the task asked for, which then stays off)."""
    did: list[str] = []
    missing: list[str] = []
    for group, lst in lists.items():
        given = 0
        for x in lst.secrets:
            wanted = x.when is not None and x.when in real
            if wanted and x.name not in store and x.name not in missing:
                missing.append(x.name)
            if not x.setting or group == CORE:
                continue
            db = group_dir(data, group) / settings_db(group)
            if not db.exists():
                continue
            with contextlib.closing(sqlite3.connect(db)) as con, con:
                if "setting" not in _tables(con):
                    continue
                con.execute("delete from setting where key = ?", (x.setting,))
                if wanted and x.name in store:
                    con.execute("insert into setting(key, value) values (?, ?)", (x.setting, store[x.name]))
                    given += 1
        if given:
            did.append(f"{group}: {given} secret(s) from the PC's store")
    if missing:
        did.append(f"! not in the PC's store, so their systems stay off: {', '.join(missing)} "
                   "(hiro-work secret set <name>)")
    record_missing(data, missing)
    return did, missing


def record_missing(data: Path, missing: list[str]) -> None:
    """The missing secrets, beside the environment's data source (source.json), for its card."""
    path = data / SOURCE_FILE
    rec = {}
    if path.exists():
        with contextlib.suppress(OSError, ValueError):
            rec = json.loads(path.read_text(encoding="utf-8"))
    if rec.get("missing_secrets", []) == missing and path.exists():
        return
    rec["missing_secrets"] = missing
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=2), encoding="utf-8")


def secret_states(hw: ModuleType, lists: Lists) -> dict[str, str]:
    """Each secret's state, by name: set (the store holds it), missing (a copy may need it, the store lacks it) or
    never (never given to a copy). Names only."""
    store = read_store(hw)
    out = {}
    for name, uses in secrets_of(lists).items():
        given = any(x.when for _, x in uses)
        out[name] = "never" if not given else "set" if name in store else "missing"
    return out


def cmd_secret(a, hw: ModuleType) -> None:
    """hiro-work secret list | fill | set <name>: the PC's dev secrets, by name only (workflow.md, "Data and real
    systems"). fill takes what the store lacks from env0's settings and the PC's environment; set asks for one value,
    typed, never on the command line."""
    import getpass

    lists = load(hw.env_dir(0))
    known = secrets_of(lists)
    if a.what == "fill":
        took = fill_store(hw, lists, dict(os.environ))
        hw.say("Took from env0 and the PC: " + (", ".join(took) or "nothing (the store has all it can take)"))
    elif a.what == "set":
        if a.name not in known:
            raise hw.Stop(f"No secret {a.name!r} in any copy list: {', '.join(sorted(known))}.")
        if not any(x.when for _, x in known[a.name]):
            raise hw.Stop(f"{a.name} is never given to a copy: nothing to set.")
        value = getpass.getpass(f"{a.name} ({known[a.name][0][1].what}), not shown: ").strip()
        if not value:
            raise hw.Stop("Nothing typed: the store is unchanged.")
        store = read_store(hw)
        store[a.name] = value
        write_store(hw, store)
        hw.say(f"{a.name} is in the store. It reaches an environment at its next copy (start, resume, real, data).")
    states = secret_states(hw, lists)
    hw.say(f"\nThe PC's dev secrets ({store_path(hw).parent}), names only:")
    for name, uses in known.items():
        x = uses[0][1]
        when = f"with real {x.when}" if x.when else "never given"
        hw.say(f"  {name:20} {states[name]:8} {when:18} {', '.join(g for g, _ in uses)}: {x.what}")
