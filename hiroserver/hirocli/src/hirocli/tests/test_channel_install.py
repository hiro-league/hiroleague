"""A channel's install, upgrade and removal through `hiro extension` (services/channel_install.py and the channel tools
of tools/extension_install.py). uv is faked: `uv tool` is the whole PC's, so a test never runs it."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME
from hirocli.domain.channel_config import ChannelConfig, load_channel_config, save_channel_config
from hirocli.domain.channel_secret_store import SECRET_MARKER
from hirocli.runtime.extension_starter import key_dir
from hirocli.services import channel_install
from hirocli.services.channel_install import ChannelInstallRefused, Source
from hirocli.tools import channel as channel_tools
from hirocli.tools import extension as extension_tools
from hirocli.tools import extension_install as tools


class _Uv:
    """`uv tool install`/`uninstall`/`list` as the channel tools run them, and the tool's receipt."""

    def __init__(self, tmp_path: Path, monkeypatch) -> None:
        self.installs: list[tuple[str, bool, bool]] = []
        self.uninstalls: list[str] = []
        self.version = "0.2.0"
        self.tool_dir = tmp_path / "uv-tools"
        uv = self

        class Install:
            def execute(self, channel_name, package=None, editable=False, reinstall=False):
                uv.installs.append((package, editable, reinstall))
                receipt = uv.tool_dir / "hiro-channel-whatsapp" / "uv-receipt.toml"
                receipt.parent.mkdir(parents=True, exist_ok=True)
                kind = "editable" if editable else ("directory" if "/" in package or "\\" in package else None)
                req = f'{{ name = "hiro-channel-whatsapp", {kind} = "{Path(package).as_posix()}" }}' if kind else \
                    f'{{ name = "hiro-channel-whatsapp"{_spec(package)} }}'
                receipt.write_text(f"[tool]\nrequirements = [{req}]\n", encoding="utf-8")
                if reinstall:
                    uv.version = "0.2.1"

        class Uninstall:
            def execute(self, channel_name, package=None):
                uv.uninstalls.append(channel_name)

        monkeypatch.setattr(channel_tools, "ChannelInstallTool", Install)
        monkeypatch.setattr(extension_tools, "ChannelUninstallTool", Uninstall)
        monkeypatch.setattr(channel_tools, "installed_channel_command", lambda name: f"/tools/bin/hiro-channel-{name}")
        monkeypatch.setattr(channel_install, "check_starts", lambda command, label: None)
        monkeypatch.setattr(channel_install, "_tool_dir", lambda: self.tool_dir)
        monkeypatch.setattr(channel_install, "installed_version", lambda package: self.version)


def _spec(package: str) -> str:
    return f', specifier = "{package.partition("==")[1]}{package.partition("==")[2]}"' if "==" in package else ""


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    for module in (channel_tools, extension_tools, tools):
        monkeypatch.setattr(module, "_resolve_path", lambda _ws: ws)
    # Not a source checkout, nor a core installed from a folder: a new install comes from PyPI
    monkeypatch.setattr(channel_install, "find_workspace_root", lambda: None)
    monkeypatch.setattr(channel_install, "core_source_root", lambda: None)
    return ws


def test_only_a_catalog_channel_installs_and_the_phones_channel_comes_with_the_core() -> None:
    assert channel_install.catalog_entry("whatsapp").package == "hiro-channel-whatsapp"
    with pytest.raises(ChannelInstallRefused, match="comes with the core") as e:
        channel_install.catalog_entry(MANDATORY_CHANNEL_NAME)
    assert e.value.code == "mandatory"
    with pytest.raises(ChannelInstallRefused, match="isn't a channel the core knows"):
        channel_install.catalog_entry("telegram")


def test_a_new_install_comes_from_pypi_or_this_checkouts_folder(tmp_path: Path, monkeypatch) -> None:
    entry = channel_install.catalog_entry("whatsapp")
    monkeypatch.setattr(channel_install, "find_workspace_root", lambda: None)
    monkeypatch.setattr(channel_install, "core_source_root", lambda: None)
    assert channel_install.install_source(entry) == Source("hiro-channel-whatsapp")
    assert channel_install.install_source(entry, "0.2.1") == Source("hiro-channel-whatsapp==0.2.1")
    (tmp_path / "channels" / "hiro-channel-whatsapp").mkdir(parents=True)
    monkeypatch.setattr(channel_install, "find_workspace_root", lambda: tmp_path)
    assert channel_install.install_source(entry) == Source(str(tmp_path / "channels" / "hiro-channel-whatsapp"))


def test_a_core_installed_from_a_folder_installs_the_channel_from_that_folder(tmp_path: Path, monkeypatch) -> None:
    """A bundle's core (installed from its folder, not editable) takes the channel beside it, the one its lock tested,
    not PyPI's release of the same version number."""
    entry = channel_install.catalog_entry("whatsapp")
    monkeypatch.setattr(channel_install, "find_workspace_root", lambda: None)
    (tmp_path / "hiroserver" / "channels" / "hiro-channel-whatsapp").mkdir(parents=True)
    monkeypatch.setattr(channel_install, "core_source_root", lambda: tmp_path / "hiroserver")
    assert channel_install.install_source(entry) == Source(str(tmp_path / "hiroserver" / "channels" /
                                                               "hiro-channel-whatsapp"))


def test_the_core_s_folder_comes_from_hirocli_s_install_record(tmp_path: Path) -> None:
    folder = tmp_path / "hiro test" / "hiroserver"
    record = json.dumps({"url": (folder / "hirocli").as_uri(), "dir_info": {}})
    assert channel_install.source_root(record) == folder
    assert channel_install.source_root(json.dumps({"url": "https://files.pythonhosted.org/x.whl",
                                                   "archive_info": {}})) is None
    assert channel_install.source_root(None) is None  # from PyPI: no record
    assert channel_install.source_root("not json") is None


@pytest.mark.parametrize(
    ("requirement", "source"),
    [
        ('{ name = "hiro-channel-whatsapp", editable = "C:/src/wa" }', Source("C:/src/wa", editable=True)),
        ('{ name = "hiro-channel-whatsapp", directory = "/src/wa" }', Source("/src/wa")),
        ('{ name = "hiro-channel-whatsapp", specifier = "==0.2.0" }', Source("hiro-channel-whatsapp==0.2.0")),
        ('{ name = "hiro-channel-whatsapp" }', Source("hiro-channel-whatsapp")),
    ],
)
def test_the_receipt_says_where_uv_installed_it_from(requirement: str, source: Source) -> None:
    receipt = f"[tool]\nrequirements = [{requirement}]\n"
    assert channel_install.receipt_source(receipt, "hiro-channel-whatsapp") == source
    assert channel_install.receipt_source(receipt, "hiro-channel-other") is None
    assert channel_install.receipt_source("not toml [", "hiro-channel-whatsapp") is None


def test_installing_a_channel_installs_its_program_then_writes_its_row_switched_off(workspace: Path,
                                                                                    tmp_path: Path,
                                                                                    monkeypatch) -> None:
    uv = _Uv(tmp_path, monkeypatch)
    result = tools.ExtensionChannelInstallTool().execute("whatsapp")
    assert (result.refused, result.package, result.version) == ("", "hiro-channel-whatsapp", "0.2.0")
    assert uv.installs == [("hiro-channel-whatsapp", False, False)]
    cfg = load_channel_config(workspace, "whatsapp")
    assert cfg is not None and not cfg.enabled
    assert cfg.command == ["/tools/bin/hiro-channel-whatsapp"] and cfg.workspace_dir == ""
    again = tools.ExtensionChannelInstallTool().execute("whatsapp")
    assert again.refused == "installed" and "installed already" in again.words
    assert tools.ExtensionChannelInstallTool().execute(MANDATORY_CHANNEL_NAME).refused == "mandatory"


def test_an_upgrade_installs_it_again_from_where_it_came_from(workspace: Path, tmp_path: Path, monkeypatch) -> None:
    uv = _Uv(tmp_path, monkeypatch)
    assert tools.ExtensionChannelUpgradeTool().execute("whatsapp").refused == "not_installed"
    tools.ExtensionChannelInstallTool().execute("whatsapp", version="0.2.0")
    done = tools.ExtensionChannelUpgradeTool().execute("whatsapp")
    assert (done.refused, done.before, done.version) == ("", "0.2.0", "0.2.1")
    # A version pinned at install isn't kept: the upgrade takes the newest on PyPI
    assert uv.installs[-1] == ("hiro-channel-whatsapp", False, True)
    tools.ExtensionChannelUpgradeTool().execute("whatsapp", version="0.3.0")
    assert uv.installs[-1] == ("hiro-channel-whatsapp==0.3.0", False, True)


def test_an_editable_checkout_stays_one_when_it_upgrades(workspace: Path, tmp_path: Path, monkeypatch) -> None:
    uv = _Uv(tmp_path, monkeypatch)
    save_channel_config(workspace, ChannelConfig(name="whatsapp", enabled=False))
    channel_tools.ChannelInstallTool().execute("whatsapp", "C:/hiro/src/wa", True)
    tools.ExtensionChannelUpgradeTool().execute("whatsapp")
    assert uv.installs[-1] == ("C:/hiro/src/wa", True, True)


class _Manager:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def deactivate(self, name: str) -> None:
        self.events.append(f"stop {name}")

    async def activate(self, name: str) -> None:
        self.events.append(f"start {name}")


def _runtime(tool, manager: _Manager):
    from types import SimpleNamespace

    tool.attach_runtime(SimpleNamespace(comm_manager=SimpleNamespace(ctx=SimpleNamespace(
        extension_manager=manager, channel_status={"whatsapp": {"state": "connected"}}))))
    return tool


def test_the_running_core_stops_the_plugin_around_an_upgrade_and_starts_it_when_it_is_on(workspace: Path,
                                                                                         tmp_path: Path,
                                                                                         monkeypatch) -> None:
    _Uv(tmp_path, monkeypatch)
    save_channel_config(workspace, ChannelConfig(name="whatsapp", enabled=True))
    channel_tools.ChannelInstallTool().execute("whatsapp", "hiro-channel-whatsapp")
    manager = _Manager()
    asyncio.run(_runtime(tools.ExtensionChannelUpgradeTool(), manager).execute_async("whatsapp"))
    assert manager.events == ["stop whatsapp", "start whatsapp"]
    save_channel_config(workspace, ChannelConfig(name="whatsapp", enabled=False))
    manager.events.clear()
    asyncio.run(_runtime(tools.ExtensionChannelUpgradeTool(), manager).execute_async("whatsapp"))
    assert manager.events == ["stop whatsapp"]  # off: it stays off


def test_removing_a_channel_stops_it_drops_its_row_and_program_and_keeps_its_folder(workspace: Path, tmp_path: Path,
                                                                                    monkeypatch) -> None:
    uv = _Uv(tmp_path, monkeypatch)
    tools.ExtensionChannelInstallTool().execute("whatsapp")
    folder = key_dir(workspace, "whatsapp")
    folder.mkdir(parents=True)
    (folder / "session.db").write_text("the account's link")
    manager = _Manager()
    tool = _runtime(tools.ExtensionChannelRemoveTool(), manager)
    done = asyncio.run(tool.execute_async("whatsapp"))
    assert done.refused == "" and done.gone == ["its row and settings", "its program"]
    assert manager.events == ["stop whatsapp"] and uv.uninstalls == ["whatsapp"]
    assert load_channel_config(workspace, "whatsapp") is None
    assert (folder / "session.db").is_file()  # kept: only --purge deletes it
    assert tool._runtime.comm_manager.ctx.channel_status == {}
    assert tools.ExtensionChannelRemoveTool().execute("whatsapp").refused == "not_installed"


def test_purging_a_channel_deletes_its_folder_and_its_secrets(workspace: Path, tmp_path: Path, monkeypatch) -> None:
    from hirocli.domain import channel_secret_store

    _Uv(tmp_path, monkeypatch)
    tools.ExtensionChannelInstallTool().execute("whatsapp")
    cfg = load_channel_config(workspace, "whatsapp")
    assert cfg is not None
    cfg.config = {"api_key": dict(SECRET_MARKER), "allowed": ["+1"]}
    save_channel_config(workspace, cfg)
    key_dir(workspace, "whatsapp").mkdir(parents=True)
    deleted: list[tuple[str, str]] = []
    monkeypatch.setattr(channel_secret_store.ChannelSecretStore, "delete",
                        lambda self, channel, key: deleted.append((channel, key)))
    monkeypatch.setattr("hirocli.domain.workspace.workspace_id_for_path", lambda path: "ws-id")
    done = tools.ExtensionChannelRemoveTool().execute("whatsapp", purge=True)
    assert done.refused == "" and not key_dir(workspace, "whatsapp").exists()
    assert deleted == [("whatsapp", "api_key")]
    assert any("1 secret(s)" in g for g in done.gone)


def test_the_phones_channel_is_never_stopped_nor_removed_here(workspace: Path, tmp_path: Path, monkeypatch) -> None:
    uv = _Uv(tmp_path, monkeypatch)
    save_channel_config(workspace, ChannelConfig(name=MANDATORY_CHANNEL_NAME, enabled=True))
    monkeypatch.setattr(channel_tools, "feature_active", lambda feature: True)
    manager = _Manager()
    done = asyncio.run(_runtime(tools.ExtensionChannelRemoveTool(), manager).execute_async(MANDATORY_CHANNEL_NAME))
    assert done.refused == "mandatory" and manager.events == [] and uv.uninstalls == []
    assert load_channel_config(workspace, MANDATORY_CHANNEL_NAME) is not None


def test_the_installed_program_is_found_with_the_uv_the_install_used(tmp_path: Path, monkeypatch) -> None:
    # A Windows service core has no uv on its PATH, only the Hiro home's copy: a bare "uv" there failed, and the
    # channel was set up with a bare command that didn't start (a clean laptop, Nov 26, 2026).
    import subprocess

    home_uv = str(tmp_path / "HiroLeague" / "bin" / "uv.exe")
    bin_dir = tmp_path / "service-profile" / "bin"
    bin_dir.mkdir(parents=True)
    exe = bin_dir / ("hiro-channel-whatsapp" + (".exe" if channel_tools.os.name == "nt" else ""))
    exe.write_bytes(b"")
    ran: list[list[str]] = []

    def run(cmd, **kw):
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{bin_dir}\n", stderr="")

    monkeypatch.setattr(channel_install, "find_uv", lambda: home_uv)
    monkeypatch.setattr(channel_tools.subprocess, "run", run)
    assert channel_tools.installed_channel_command("whatsapp") == str(exe)
    assert ran == [[home_uv, "tool", "dir", "--bin"]]


def test_no_uv_anywhere_leaves_the_bare_command_with_a_warning(monkeypatch, caplog) -> None:
    def no_uv() -> str:
        raise RuntimeError("uv isn't on this machine")

    monkeypatch.setattr(channel_install, "find_uv", no_uv)
    with caplog.at_level("WARNING"):
        assert channel_tools.installed_channel_command("whatsapp") is None
    assert any("Could not resolve uv tool bin dir" in r.getMessage() for r in caplog.records)
