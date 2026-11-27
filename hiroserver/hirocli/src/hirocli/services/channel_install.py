"""Installing, upgrading and removing a channel: the core's own steps behind ``hiro extension`` (Installing apps,
phase 5; the design's §6).

A channel installs the way it always has: its program is a uv tool (``uv tool install``) of its published package
(``hiro-channel-whatsapp`` on PyPI), or of its folder beside the core's own source (a dev checkout, or the
folder the core was installed from), and the core starts it itself. So there is
no account, no service and no administrator step. ``hiro extension`` is the one lifecycle for apps and channels;
``hiro channel`` keeps a channel's own settings.

- **Install** (``hiro extension install whatsapp``): a channel of the catalog (domain/channel_catalog.py), not the
  mandatory one (it comes with the core's own package), not set up yet. Its program is installed, then its row is
  written switched off, with the program's full path (channel_setup).
- **Upgrade** (``hiro extension upgrade whatsapp [--version X]``): the program is installed again from where it was
  installed from (its uv receipt: an editable checkout stays one), or ``<package>==X`` from PyPI. It must start
  (``--help``) after, as the core's deploy checks it.
- **Remove** (``hiro extension remove whatsapp [--purge]``): its row goes and its program is uninstalled
  (extension_remove); ``--purge`` deletes its folder too (its key, its descriptor, its account's link such as
  WhatsApp's session) and its secrets.

Stopping and starting the running plugin around an upgrade or a removal is the caller's (the extension manager's).
"""

from __future__ import annotations

import importlib.metadata
import json
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from hiro_commons.log import Logger
from hiro_commons.process import find_workspace_root

from ..domain.channel_catalog import CatalogChannel, catalog_channel
from ..domain.channel_config import load_channel_config
from ..domain.hiro_home import hiro_home
from ..runtime.extension_starter import key_dir

log = Logger.get("EXTENSIONS.CHANNELS")

_UV_TIMEOUT_S = 900
_START_TIMEOUT_S = 60


class ChannelInstallRefused(ValueError):
    """The core won't do it: ``code`` says which rule (not_in_catalog, mandatory, installed, not_installed), the
    message is for people."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Source:
    """What ``uv tool install`` installs a channel from: a requirement (``hiro-channel-whatsapp==0.2.1``) or a folder,
    editable or not."""

    target: str
    editable: bool = False


def catalog_entry(name: str) -> CatalogChannel:
    """The channel's catalog entry; ChannelInstallRefused for a name the catalog doesn't know, or the phones'
    channel, which comes with the core."""
    from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME

    if name == MANDATORY_CHANNEL_NAME:
        raise ChannelInstallRefused("mandatory", f"The {name} channel comes with the core: it is installed, upgraded "
                                                 "and removed with it.")
    entry = catalog_channel(name)
    if entry is None:
        raise ChannelInstallRefused("not_in_catalog", f"“{name}” isn't a channel the core knows (its catalog names "
                                                      "the channels it installs).")
    return entry


def source_root(direct_url: str | None) -> Path | None:
    """The folder of the core's packages (``hiroserver``) when hirocli was installed from its folder: its install
    record (``direct_url.json``, PEP 610) names ``<root>/hirocli``. None for a package from an index (PyPI), or a
    record that isn't one."""
    try:
        record = json.loads(direct_url or "")
    except ValueError:
        return None
    url = urlparse(record.get("url", "")) if isinstance(record, dict) else None
    if url is None or url.scheme != "file" or "dir_info" not in record:
        return None
    return Path(url2pathname(unquote(url.path))).parent


def core_source_root() -> Path | None:
    """The core's source folder when it was installed from one, not from PyPI (a bundle a person unzipped)."""
    try:
        return source_root(importlib.metadata.distribution("hirocli").read_text("direct_url.json"))
    except importlib.metadata.PackageNotFoundError:
        return None


def install_source(entry: CatalogChannel, version: str = "") -> Source:
    """Where a new install comes from: ``<package>==<version>`` from PyPI when a version is named; else the channel's
    folder of the source checkout the core runs from (a dev core), or of the folder the core was installed from;
    else its package from PyPI. Why the folder first: the channel there is the one the core's lock tested, and the
    install keeps to that lock's versions (tools/channel.py); PyPI's may be an older release of the same version
    number, whose own pins the lock doesn't hold (Nov 27, 2026: WhatsApp 0.2.0 on PyPI needs neonize 0.3.18.post0, the
    lock 0.5.2)."""
    if version:
        return Source(f"{entry.package}=={version}")
    for root in (find_workspace_root(), core_source_root()):
        local = root / "channels" / entry.package if root is not None else None
        if local is not None and local.is_dir():
            return Source(str(local))
    return Source(entry.package)


def receipt_source(receipt: str, package: str) -> Source | None:
    """Where uv installed the tool from, read from its receipt (``uv-receipt.toml``); None when it doesn't say."""
    try:
        requirements = tomllib.loads(receipt).get("tool", {}).get("requirements", [])
    except tomllib.TOMLDecodeError:
        return None
    for req in requirements:
        if req.get("name") != package:
            continue
        if req.get("editable"):
            return Source(str(req["editable"]), editable=True)
        if req.get("directory") or req.get("path"):
            return Source(str(req.get("directory") or req.get("path")))
        return Source(f"{package}{req.get('specifier', '')}")
    return None


def upgrade_source(entry: CatalogChannel, version: str = "") -> Source:
    """Where an upgrade comes from: ``<package>==<version>`` when named, else where it was installed from."""
    if version:
        return Source(f"{entry.package}=={version}")
    receipt = _tool_dir() / entry.package / "uv-receipt.toml"
    try:
        found = receipt_source(receipt.read_text(encoding="utf-8"), entry.package)
    except OSError:
        found = None
    if found is None:
        raise ChannelInstallRefused("not_installed", f"{entry.label}'s program isn't installed as a uv tool here "
                                                     f"({receipt.parent}): install it first.")
    if not found.editable and found.target.startswith(entry.package):
        # A version pinned at install isn't kept: an upgrade takes the newest on PyPI unless one is named
        return Source(entry.package)
    return found


def find_uv() -> str:
    """uv: on the core's PATH, else the Hiro home's own copy (a service core on Windows has no PATH of the person's)."""
    found = shutil.which("uv") or shutil.which("uv", path=str(hiro_home() / "bin"))
    if not found:
        raise RuntimeError("uv isn't on this machine (neither on the PATH nor in the Hiro home's bin): install uv.")
    return found


def _uv(args: list[str], what: str) -> str:
    try:
        done = subprocess.run(  # noqa: S603 — uv with fixed arguments, no shell
            [find_uv(), *args], capture_output=True, text=True, timeout=_UV_TIMEOUT_S, check=False, encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{what} failed: {exc}.") from exc
    if done.returncode != 0:
        detail = " | ".join((done.stderr or done.stdout).strip().splitlines()[-3:])
        raise RuntimeError(f"{what} failed: {detail or f'exit code {done.returncode}'}.")
    return (done.stdout or done.stderr).strip()


def _tool_dir() -> Path:
    return Path(_uv(["tool", "dir"], "Finding uv's tool folder"))


def installed_version(package: str) -> str:
    """The version of the tool uv installed for ``package`` (``uv tool list``), "" when it isn't installed."""
    for line in _uv(["tool", "list"], "Listing uv's tools").splitlines():
        name, _, version = line.partition(" ")
        if name == package and version.startswith("v"):
            return version[1:].strip()
    return ""


def check_starts(command: str, label: str) -> None:
    """The channel's program starts (``--help``), as the core's deploy proves it after installing it again."""
    try:
        done = subprocess.run([command, "--help"], capture_output=True, timeout=_START_TIMEOUT_S, check=False)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{label}'s program doesn't start after its install: {exc}.") from exc
    if done.returncode != 0:
        raise RuntimeError(f"{label}'s program doesn't start after its install (`{command} --help` fails).")


def install(workspace_path: Path, workspace: str | None, name: str, version: str = "") -> tuple[str, str]:
    """Install a channel of the catalog: its program as a uv tool, then its row, switched off. Returns (package,
    version). ChannelInstallRefused or RuntimeError with words."""
    from ..tools.channel import ChannelInstallTool, ChannelSetupTool, installed_channel_command

    entry = catalog_entry(name)
    if load_channel_config(workspace_path, name) is not None:
        raise ChannelInstallRefused("installed", f"{entry.label} is installed already: upgrade it, or remove it "
                                                 "first.")
    source = install_source(entry, version)
    ChannelInstallTool().execute(name, source.target, source.editable)
    command = installed_channel_command(name) or entry.command
    check_starts(command, entry.label)
    # workspace_dir "": the program runs as uv installed it, never wrapped in `uv run` (its own environment)
    ChannelSetupTool().execute(name, command, False, workspace, "")
    done = installed_version(entry.package)
    log.info(f"✅ Channel installed — {entry.label} {done}: switched off until it is switched on", channel=name,
             source=source.target)
    return entry.package, done


def upgrade(name: str, version: str = "") -> tuple[str, str]:
    """Install a channel's program again, newer (its running process stopped by the caller). Returns (before,
    after). ChannelInstallRefused or RuntimeError with words."""
    from ..tools.channel import ChannelInstallTool, installed_channel_command

    entry = catalog_entry(name)
    source = upgrade_source(entry, version)
    before = installed_version(entry.package)
    ChannelInstallTool().execute(name, source.target, source.editable, reinstall=True)
    check_starts(installed_channel_command(name) or entry.command, entry.label)
    after = installed_version(entry.package)
    log.info(f"✅ Channel upgraded — {entry.label} {before} → {after}", channel=name, source=source.target)
    return before, after


def secret_keys_of(workspace_path: Path, name: str) -> list[str]:
    """The settings of a channel kept as secrets (its row holds a marker for each): read before its row goes, since
    the keyring can't list them."""
    from ..domain.channel_secret_store import is_secret_marker

    cfg = load_channel_config(workspace_path, name)
    return [k for k, v in (cfg.config if cfg else {}).items() if is_secret_marker(v)]


def purge(workspace_path: Path, name: str, secrets: list[str]) -> list[str]:
    """After its removal: delete the channel's folder (its key, its descriptor, its account's link such as WhatsApp's
    session) and its secrets. Returns what went, in words. Only the folder the core gave it: a link there is refused,
    never followed."""
    from ..domain.channel_secret_store import ChannelSecretStore
    from ..domain.workspace import workspace_id_for_path

    gone: list[str] = []
    folder = key_dir(workspace_path, name)
    if folder.is_symlink() or (folder.exists() and folder.resolve() != folder.absolute()):
        raise RuntimeError(f"{folder} is a link, not the channel's own folder: it was left as it is.")
    if folder.is_dir():
        shutil.rmtree(folder)
        gone.append(f"its folder {folder}")
    workspace_id = workspace_id_for_path(workspace_path)
    if secrets and workspace_id:
        store = ChannelSecretStore(workspace_path, workspace_id)
        for key in secrets:
            store.delete(name, key)
        gone.append(f"{len(secrets)} secret(s)")
    log.info(f"Channel purged — {name}: {', '.join(gone) or 'nothing was left'}", channel=name)
    return gone
