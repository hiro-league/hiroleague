r"""Each repo's copy list (its data.toml): what a copy of its data holds, and how each piece comes along.

hiro-work reads them for both copies (hiro-docs standards/workflow.md, "Data and real systems"):
- **live -> env0** (`hiro-work refresh-data`, data.py): an item with `live = "copy"` is fetched from Simone, scrubbed
  there; `live = "own"` is never fetched, and env0 keeps its own.
- **env0 -> env1..env5** (`hiro-work start`, `resume`, `real`, `configure`): `envs = "copy"` is copied (a database with
  SQLite's backup), `"link"` hard-linked (pictures), `"none"` left out.

A list is a TOML file at the repo's root. The core's (the HiroLeague repo's) describes its workspace and holds
`[every_app]`, what the backend kit writes to every app's setting table; each app's describes its data folder.

    live = "~/homehiro/data"            # its data folder on Simone

    [[item]]                             # a file or folder in the data folder; the path may be a pattern (*)
    path = "homehiro.db"
    kind = "database"                    # database | file | folder
    live = "copy"                        # live -> env0: copy | own
    envs = "copy"                        # env0 -> env1..env5: copy | link | none
    place_tables = ["websession"]        # a database's per-place tables: never from live, env0's own rows kept
    optional = false                     # true: skipped, not failed, when it can't be read (a locked file)
    why = "..."                          # always: what it is and why it comes along (or doesn't)

    [[setting]]                          # a per-place row of its setting table: never from live, env0's own kept
    key = "ha_token"
    needs = "reads"                      # optional: in env1..env5 left out unless the task has real reads | writes
    why = "..."

    [[switch]]                           # in env1..env5: turned off unless the task has that real system
    path = "nethiro.db"                  # a database item: table, column, value
    table = "statusitem"                 # (a JSON file item instead: key, value)
    column = "enabled"
    value = 0
    unless = "reads"                     # optional: reads | writes | ai; absent = always
    why = "..."

    [[env]]                              # an .env.dev line in env1..env5 (the core: its server's environment)
    name = "TALKER_KEY"                  # or match = "<regex>" for every variable it matches
    drop = true                          # or value = "..."
    unless = "ai"                        # optional
    why = "..."

Every field is checked when a list is read: an unknown field or value stops hiro-work with the file and the reason.
Standard library only, as hiro_work.py.
"""

from __future__ import annotations

import fnmatch
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

FILE = "data.toml"
CORE = "core"  # the core's list, in the HiroLeague repo
CORE_REPO = "hiroleague"
KINDS = ("database", "file", "folder")
LIVE = ("copy", "own")
ENVS = ("copy", "link", "none")
REAL = ("reads", "writes", "ai")


class ListError(ValueError):
    pass


@dataclass(frozen=True)
class Item:
    path: str
    kind: str
    live: str
    envs: str
    why: str
    place_tables: tuple[str, ...] = ()
    optional: bool = False

    @property
    def pattern(self) -> bool:
        return any(c in self.path for c in "*?[")

    def matches(self, name: str) -> bool:
        return fnmatch.fnmatchcase(name, self.path)


@dataclass(frozen=True)
class Setting:
    key: str
    why: str
    needs: str | None = None


@dataclass(frozen=True)
class Switch:
    path: str
    why: str
    value: object
    unless: str | None = None
    table: str | None = None
    column: str | None = None
    key: str | None = None


@dataclass(frozen=True)
class EnvLine:
    why: str
    name: str | None = None
    match: str | None = None
    value: str | None = None
    drop: bool = False
    unless: str | None = None

    def applies(self, real: list[str]) -> bool:
        return self.unless is None or self.unless not in real


@dataclass(frozen=True)
class EveryApp:
    place_key_pattern: str = ""
    place_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class CopyList:
    group: str  # "core", or the app's repo
    live: str  # its data folder on Simone
    items: tuple[Item, ...]
    settings: tuple[Setting, ...] = ()
    switches: tuple[Switch, ...] = ()
    env: tuple[EnvLine, ...] = ()
    every_app: EveryApp | None = None  # the core's list only

    def item(self, name: str) -> Item | None:
        """The item a top-level name (or a path, for the core's db/ files) falls under: an exact path first."""
        exact = next((i for i in self.items if i.path == name), None)
        return exact or next((i for i in self.items if i.pattern and i.matches(name)), None)

    def databases(self, side: str, how: str = "copy") -> list[Item]:
        return [i for i in self.items if i.kind == "database" and getattr(i, side) == how]

    def folders(self, side: str, how: str) -> list[Item]:
        return [i for i in self.items if i.kind == "folder" and getattr(i, side) == how]


def _fields(d: dict, where: str, required: set[str], allowed: set[str]) -> None:
    missing, unknown = required - d.keys(), d.keys() - allowed - required
    if missing:
        raise ListError(f"{where}: missing {', '.join(sorted(missing))}")
    if unknown:
        raise ListError(f"{where}: unknown field {', '.join(sorted(unknown))}")


def _one_of(value: object, choices: tuple[str, ...], where: str) -> None:
    if value not in choices:
        raise ListError(f"{where}: {value!r} is not one of {', '.join(choices)}")


def parse(text: str, group: str, name: str = FILE) -> CopyList:
    """A copy list from its TOML, checked."""
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ListError(f"{name}: {exc}") from exc
    top = {"live", "item", "setting", "switch", "env"} | ({"every_app"} if group == CORE else set())
    _fields(doc, name, {"live", "item"}, top)
    items = []
    for n, d in enumerate(doc["item"], 1):
        where = f"{name}, item {n} ({d.get('path', '?')})"
        _fields(d, where, {"path", "kind", "live", "envs", "why"}, {"place_tables", "optional"})
        _one_of(d["kind"], KINDS, where + ", kind")
        _one_of(d["live"], LIVE, where + ", live")
        _one_of(d["envs"], ENVS, where + ", envs")
        item = Item(d["path"], d["kind"], d["live"], d["envs"], d["why"], tuple(d.get("place_tables", ())),
                    bool(d.get("optional", False)))
        if item.place_tables and item.kind != "database":
            raise ListError(f"{where}: only a database has place_tables")
        if item.kind == "database" and item.pattern:
            raise ListError(f"{where}: a database is named, not a pattern")
        if item.envs == "link" and item.kind != "folder":
            raise ListError(f"{where}: only a folder is linked")
        if item.pattern and item.live == "copy":
            raise ListError(f"{where}: a pattern can't be fetched from live; name each file")
        if any(i.path == item.path for i in items):
            raise ListError(f"{where}: listed twice")
        items.append(item)
    paths = {i.path: i for i in items}
    settings = []
    for n, d in enumerate(doc.get("setting", []), 1):
        where = f"{name}, setting {n} ({d.get('key', '?')})"
        _fields(d, where, {"key", "why"}, {"needs"})
        if "needs" in d:
            _one_of(d["needs"], ("reads", "writes"), where + ", needs")
        if any(x.key == d["key"] for x in settings):
            raise ListError(f"{where}: listed twice")
        settings.append(Setting(d["key"], d["why"], d.get("needs")))
    switches = []
    for n, d in enumerate(doc.get("switch", []), 1):
        where = f"{name}, switch {n} ({d.get('path', '?')})"
        _fields(d, where, {"path", "value", "why"}, {"unless", "table", "column", "key"})
        target = paths.get(d["path"])
        if target is None or target.kind == "folder":
            raise ListError(f"{where}: its path is no database or file item")
        if target.kind == "database" and not ("table" in d and "column" in d and "key" not in d):
            raise ListError(f"{where}: a database's switch names a table and a column")
        if target.kind == "file" and not ("key" in d and "table" not in d and "column" not in d):
            raise ListError(f"{where}: a JSON file's switch names a key")
        if "unless" in d:
            _one_of(d["unless"], REAL, where + ", unless")
        if any((x.path, x.table, x.column, x.key) == (d["path"], d.get("table"), d.get("column"), d.get("key"))
               for x in switches):
            raise ListError(f"{where}: listed twice")
        switches.append(Switch(d["path"], d["why"], d["value"], d.get("unless"), d.get("table"), d.get("column"),
                               d.get("key")))
    env = []
    for n, d in enumerate(doc.get("env", []), 1):
        where = f"{name}, env {n} ({d.get('name') or d.get('match', '?')})"
        _fields(d, where, {"why"}, {"name", "match", "value", "drop", "unless"})
        if ("name" in d) == ("match" in d):
            raise ListError(f"{where}: name or match, one of them")
        if ("value" in d) == bool(d.get("drop")):
            raise ListError(f"{where}: value or drop, one of them")
        if "match" in d:
            try:
                re.compile(d["match"])
            except re.error as exc:
                raise ListError(f"{where}: match isn't a pattern: {exc}") from exc
        if "unless" in d:
            _one_of(d["unless"], REAL, where + ", unless")
        if any((x.name, x.match) == (d.get("name"), d.get("match")) for x in env):
            raise ListError(f"{where}: listed twice")
        env.append(EnvLine(d["why"], d.get("name"), d.get("match"), d.get("value"), bool(d.get("drop")),
                           d.get("unless")))
    every = None
    if group == CORE:
        e = doc.get("every_app")
        if e is None:
            raise ListError(f"{name}: the core's list holds [every_app]")
        _fields(e, f"{name}, every_app", {"place_key_pattern", "place_keys"}, set())
        every = EveryApp(e["place_key_pattern"], tuple(e["place_keys"]))
    return CopyList(group, doc["live"], tuple(items), tuple(settings), tuple(switches), tuple(env), every)


def repo_of(group: str) -> str:
    return CORE_REPO if group == CORE else group


def load(root: Path, group: str) -> CopyList:
    """A group's list from its repo under root (an environment's folder: C:\\hiro\\env0)."""
    path = root / repo_of(group) / FILE
    if not path.exists():
        raise ListError(f"{repo_of(group)} has no copy list ({path}): every app writes one (workflow.md)")
    return parse(path.read_text(encoding="utf-8"), group, f"{repo_of(group)}/{FILE}")


def load_all(root: Path, apps: list[str]) -> dict[str, CopyList]:
    """The core's list, then each app's, in apps.toml's order; an app's setting the core's list already covers (the
    kit's keys, or the pattern, for a setting with no `needs`) is refused: one line per thing."""
    lists = {g: load(root, g) for g in [CORE, *apps]}
    for g in apps:
        refuse_covered(lists[g], lists[CORE].every_app)
    return lists


def refuse_covered(lst: CopyList, every: EveryApp) -> None:
    """An app's setting line the core's list already covers: the kit's keys, or the pattern (unless it says `needs`,
    which the pattern doesn't)."""
    for s in lst.settings:
        if s.key in every.place_keys or (s.needs is None and re.search(every.place_key_pattern, s.key)):
            raise ListError(f"{repo_of(lst.group)}/{FILE}, setting {s.key}: the core's list already makes it "
                            "per-place (every_app): drop the line")


def unlisted(lst: CopyList, names: list[str]) -> list[str]:
    """The names in a data folder that no item covers: copied nowhere until they are listed. A database's -wal and
    -shm files go with it."""
    out = []
    for name in names:
        base = re.sub(r"-(wal|shm|journal)$", "", name)
        if lst.item(base) is None and lst.item(name) is None:
            out.append(name)
    return out


def main(argv: list[str]) -> int:
    """`python copylist.py <repo folder>`: read and check that repo's copy list, as hiro-work will (each repo's
    ./scripts/check.sh runs it, through the check engine, when its data.toml changes)."""
    if len(argv) != 1:
        print("usage: python copylist.py <repo folder>")
        return 2
    repo = Path(argv[0]).resolve()
    group = CORE if repo.name == CORE_REPO else repo.name
    try:
        lst = load(repo.parent, group)
        if group != CORE and (repo.parent / CORE_REPO / FILE).exists():  # beside the core: what it already covers
            refuse_covered(lst, load(repo.parent, CORE).every_app)
    except ListError as exc:
        print(f"copy list: {exc}")
        return 1
    print(f"copy list: {repo.name}/{FILE} reads: {len(lst.items)} item(s), {len(lst.settings)} setting(s), "
          f"{len(lst.switches)} switch(es), {len(lst.env)} env line(s)")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
