r"""The switchboard for hiro-work: presets, and each test environment's file of what it reaches (hiro-docs
standards/workflow.md, "Data and real systems").

- The systems and the modes each can take are the core's own list (hiroserver/hiro-commons, switchboard.py), loaded
  from its file so hiro-work and the servers can't disagree.
- A preset names every system's mode (presets.toml beside this file: the built-in ones, then Michel's own).
- An environment's switchboard is its preset with the systems its task changed: written to
  C:\hiro\data\envN\switchboard.json, named to its servers in HIRO_SWITCHBOARD, read by them at start.
- The copy lists still say "reads", "writes" and "ai" (a setting's `needs`, a switch's `unless`): `real_of` works them
  out from the modes, so the data a copy gets follows its switchboard.

Standard library only, as hiro_work.py.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRESETS = HERE / "presets.toml"
FILE = "switchboard.json"
DEFAULT = "Safe"

_spec = importlib.util.spec_from_file_location(
    "hiro_switchboard", HERE.parents[1] / "hiroserver" / "hiro-commons" / "src" / "hiro_commons" / "switchboard.py")
board = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = board  # its dataclasses look their module up by name
_spec.loader.exec_module(board)
SYSTEMS: dict[str, tuple[str, tuple[str, ...]]] = board.SYSTEMS
ENV = board.ENV


class SwitchError(ValueError):
    pass


def check_modes(modes: dict[str, str], where: str) -> dict[str, str]:
    """Every system named once with a mode it can take; else SwitchError saying which."""
    unknown = sorted(set(modes) - set(SYSTEMS))
    if unknown:
        raise SwitchError(f"{where}: no system {', '.join(unknown)} (the systems: {', '.join(SYSTEMS)})")
    for system, mode in modes.items():
        if mode not in SYSTEMS[system][1]:
            raise SwitchError(f"{where}: {SYSTEMS[system][0]} can't be {mode!r} (it can be "
                              f"{', '.join(SYSTEMS[system][1])})")
    return modes


def presets(path: Path = PRESETS) -> list[dict]:
    """The presets, the built-in ones first: name, about, builtin, modes (every system)."""
    out = []
    for p in tomllib.loads(path.read_text(encoding="utf-8")).get("preset", []):
        modes = check_modes(dict(p["modes"]), f"preset {p['name']}")
        missing = sorted(set(SYSTEMS) - set(modes))
        if missing:
            raise SwitchError(f"preset {p['name']}: no mode for {', '.join(missing)}")
        out.append({"name": str(p["name"]), "about": str(p.get("about", "")), "builtin": bool(p.get("builtin")),
                    "modes": modes})
    return out


def preset(name: str, path: Path = PRESETS) -> dict:
    found = next((p for p in presets(path) if p["name"].lower() == name.strip().lower()), None)
    if found is None:
        raise SwitchError(f"No preset {name!r}: {', '.join(p['name'] for p in presets(path))}")
    return found


def parse_sets(sets: list[str]) -> dict[str, str]:
    """["ai=real", "ha=read"] as modes, checked."""
    out = {}
    for item in sets:
        system, sep, mode = item.partition("=")
        if not sep:
            raise SwitchError(f"{item!r}: write it as <system>=<mode>, like ai=real")
        out[system.strip()] = mode.strip()
    return check_modes(out, "--set")


def resolve(preset_name: str, changes: dict[str, str] | None = None, path: Path = PRESETS) -> dict[str, str]:
    """A preset's modes with the changed systems."""
    return {**preset(preset_name, path)["modes"], **check_modes(dict(changes or {}), "its changes")}


def real_of(modes: dict[str, str]) -> list[str]:
    """What the copy lists call it: "reads" (Home Assistant is reached at all: its address and token stay in the
    copy), "writes" (a login that writes is needed: AdGuard real, or Frigate real, where TrainHiro trains) and "ai"
    (real AI: the core's providers and keys)."""
    out = []
    if modes.get("ha") in (board.REAL, board.READ):
        out.append("reads")
    if board.REAL in (modes.get("adguard"), modes.get("frigate")):
        out.append("writes")
    if modes.get("ai") == board.REAL:
        out.append("ai")
    return out


def describe_sign_in(rec: dict | None) -> str:
    """The work card's words for an environment's sign-in."""
    s = (rec or {}).get("sign_in") or SIGN_IN_ON
    if s.get("mode") == board.OFF:
        return "sign-in off (everyone is the owner)"
    if s.get("mode") == board.AS:
        return f"sign-in off (everyone is {s.get('name') or s.get('person')})"
    return "sign-in on"


def app_env(modes: dict[str, str]) -> dict[str, str]:
    """The apps' own older switches, worked out from the modes until every send goes through a gate: OUTPUTS (on only
    when something that sends is real: the gates then decide each) and HA_AUTO_WRITES (on only with Home Assistant
    real)."""
    sends = board.REAL in (modes.get("whatsapp"), modes.get("talker"), modes.get("voices"))
    return {"OUTPUTS": "on" if sends else "off", "HA_AUTO_WRITES": "on" if modes.get("ha") == board.REAL else "off"}


SIGN_IN_ON: dict = {"mode": board.ON}


def sign_in(mode: str, person: dict | None = None) -> dict:
    """The file's `sign_in`: on, off, or as one person ({"id", "name"} of the environment's family list). "as" with
    nobody is on: never looser than asked."""
    if mode == board.OFF:
        return {"mode": board.OFF}
    if mode == board.AS and person:
        return {"mode": board.AS, "person": person["id"], "name": person["name"]}
    return dict(SIGN_IN_ON)


def find_person(people: list[dict], asked: str) -> dict | None:
    """The person `asked` names in a family list ([{"id", "name", "role"}]): by id, else by name (any case), when
    exactly one has it."""
    by_id = [p for p in people if p["id"] == asked]
    named = by_id or [p for p in people if p["name"].lower() == asked.strip().lower()]
    return named[0] if len(named) == 1 else None


def write(data_dir: Path, env: int, preset_name: str, changes: dict[str, str] | None = None,
          path: Path = PRESETS, sign_in: dict | None = None) -> dict:
    """An environment's switchboard file, from its preset, its changes and its sign-in: the record written."""
    rec = {"place": f"env{env}", "preset": preset(preset_name, path)["name"], "changes": dict(changes or {}),
           "modes": resolve(preset_name, changes, path), "sign_in": sign_in or dict(SIGN_IN_ON)}
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / FILE).write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


def read(data_dir: Path) -> dict | None:
    try:
        return json.loads((data_dir / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def describe(rec: dict | None) -> str:
    """The work card's line: the preset, its changes, and what is real."""
    if not rec:
        return "switchboard: none yet (Safe at its next copy)"
    real = [SYSTEMS[s][0] for s, m in rec["modes"].items() if m == board.REAL]
    plus = f" +{len(rec['changes'])}" if rec.get("changes") else ""
    return f"switchboard: {rec['preset']}{plus} | real: {', '.join(real) or 'nothing'}"


def save_preset(name: str, modes: dict[str, str], about: str = "", path: Path = PRESETS) -> None:
    """One of Michel's own presets, added to the file (a name a preset has is refused)."""
    clean = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ,+_-]{0,23}", clean):
        raise SwitchError("A preset's name is 1 to 24 letters, digits, spaces and , + _ -")
    if any(p["name"].lower() == clean.lower() for p in presets(path)):
        raise SwitchError(f"A preset is named {clean!r} already.")
    full = {**check_modes(dict(modes), f"preset {clean}")}
    missing = sorted(set(SYSTEMS) - set(full))
    if missing:
        raise SwitchError(f"preset {clean}: no mode for {', '.join(missing)}")
    line = ", ".join(f'{s} = "{full[s]}"' for s in SYSTEMS)
    about = (about.strip() or "Michel's own").replace('"', "'")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f'\n[[preset]]\nname = "{clean}"\nabout = "{about}"\nmodes = {{ {line} }}\n')


def remove_preset(name: str, path: Path = PRESETS) -> None:
    """Remove one of Michel's own presets (a built-in one is refused)."""
    found = preset(name, path)
    if found["builtin"]:
        raise SwitchError(f"{found['name']} is built in: it stays.")
    text = path.read_text(encoding="utf-8")
    block = re.compile(r'\n\[\[preset\]\]\nname = "' + re.escape(found["name"]) + r'"\n(?:(?!\[\[preset\]\]).*\n?)*')
    path.write_text(block.sub("\n", text, count=1).rstrip("\n") + "\n", encoding="utf-8")
