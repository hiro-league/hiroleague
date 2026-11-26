"""Build an app's package: the one file the core installs (`hiro extension install <package>`).

    python build-kit/package.py <app folder> [--out <folder>] [--ui-built]

Run with the core's Python (`uv run --project hiroserver python build-kit/package.py ...`): it needs the SDK's
manifest model. The app folder holds `backend/` (pyproject.toml, uv.lock, src/<module>) and `frontend/` (a SvelteKit
app built to `frontend/build`, or just that folder).

The package is `<key, dashed>-<version>.zip` (Michel, Nov 25, 2026: one zip, one package for every system):

    hiro-extension.toml      the manifest, written from the app's declaration (hiro_channel_sdk.manifest)
    requirements.txt         every library from PyPI, pinned with its hashes (exported from the app's uv.lock)
    wheels/                  the app's wheel, its built UI inside (<module>/static), and the kits' wheels

The manifest's fields come from the app itself: its key, port, title, address and asks from its `Extension(...)` and
`setup(...)` (read in its own environment; the asks as the kit declares them to the core, `asks_for()`), its version
from pyproject.toml (the declaration must say the same), its command from its one console script, its predeploy when
it has `<module>/predeploy.py`. The core versions it works with follow the
kit it was built with: the kits and the core are released together, so kit 0.2.x works with core 0.2.x.

Nothing here changes the app's folder: the UI is put into a copy of the backend, which is built from there.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

from hiro_channel_sdk.manifest import KIND_APP, MANIFEST_FILE, Manifest, dashed, render_manifest

KIT = "hiro-extension-kit"
HEALTH = "/api/health"

# What the app's own environment prints about it: run there, since its declaration imports the app's package
_DECLARATION = """
import json, sys
import importlib
module = importlib.import_module(sys.argv[1])
from hiro_extension_kit import identity
from hiro_extension_kit.extension import ext
from hiro_extension_kit.hiroleague import asks_for
e = ext()
asks = asks_for()
print(json.dumps({"key": e.name, "port": e.port, "version": e.version, "title": identity.app().title,
                  "site": e.site_default or "",
                  "asks": None if asks is None else [a.model_dump(exclude_none=True) for a in asks]}))
"""


class PackageError(Exception):
    """Why the package can't be built, in words for people."""


def _run(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    done = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", check=False)
    if done.returncode != 0:
        raise PackageError(f"{' '.join(args[:3])} failed in {cwd}:\n{done.stderr.strip() or done.stdout.strip()}")
    return done.stdout


def _project(backend: Path) -> tuple[dict, str]:
    """The backend's pyproject.toml and its Python module's name."""
    pyproject = tomllib.loads((backend / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project", {})
    module = pyproject.get("tool", {}).get("uv", {}).get("build-backend", {}).get("module-name") \
        or project["name"].replace("-", "_")
    return project, module


def local_packages(lock_text: str) -> dict[str, str]:
    """The packages the app's uv.lock takes from local folders (the kits), by name → their path from the backend;
    the app itself (``editable = "."``) is left out."""
    found: dict[str, str] = {}
    for package in tomllib.loads(lock_text).get("package", []):
        source = package.get("source", {})
        path = source.get("editable") or source.get("directory") or source.get("path")
        if path and path != ".":
            found[package["name"]] = path
    return found


def core_range(kit_version: str) -> str:
    """The core versions an app built with this kit works with: the same release line (0.2.x → >=0.2,<0.3)."""
    match = re.match(r"(\d+)\.(\d+)", kit_version)
    if not match:
        raise PackageError(f"The kit's version {kit_version!r} isn't major.minor.patch.")
    major, minor = int(match[1]), int(match[2])
    return f">={major}.{minor},<{major}.{minor + 1}"


def command_of(project: dict) -> str:
    """The app's one console script: the program its service runs."""
    scripts = project.get("scripts", {})
    if len(scripts) != 1:
        raise PackageError(
            "The app needs exactly one console script in [project.scripts], the program its service runs "
            f"(it has {len(scripts)})."
        )
    return next(iter(scripts))


def _build_ui(frontend: Path, ui_built: bool) -> Path:
    built = frontend / "build"
    if (frontend / "package.json").is_file() and not ui_built:
        npm = shutil.which("npm")
        if npm is None:
            raise PackageError("npm isn't on the PATH: the app's UI can't be built (or pass --ui-built).")
        _run([npm, "ci"], frontend)
        _run([npm, "run", "build"], frontend)
    if not (built / "index.html").is_file() and not (built / "200.html").is_file():
        raise PackageError(f"The app's UI isn't built: {built} has no index.html.")
    return built


def _stage_backend(backend: Path, module: str, ui: Path, stage: Path) -> Path:
    """A copy of the backend with the UI inside the module (<module>/static), its local sources made absolute so the
    copy builds from anywhere."""
    copy = stage / "backend"
    shutil.copytree(backend, copy, ignore=shutil.ignore_patterns(".venv", "data", "__pycache__", ".pytest_cache",
                                                                 "tests", ".ruff_cache"))
    static = copy / "src" / module / "static"
    if static.exists():
        shutil.rmtree(static)
    shutil.copytree(ui, static)
    text = (copy / "pyproject.toml").read_text(encoding="utf-8")

    def absolute(match: re.Match[str]) -> str:
        return f'{match[1]}"{(backend / match[2]).resolve().as_posix()}"'

    (copy / "pyproject.toml").write_text(re.sub(r'(path\s*=\s*)"([^"]+)"', absolute, text), encoding="utf-8")
    return copy


def _declaration(backend: Path, module: str, data: Path) -> dict:
    env = {**os.environ, "DATA_DIR": str(data)}
    out = _run(["uv", "run", "--frozen", "--no-dev", "python", "-c", _DECLARATION, module], backend, env)
    return json.loads(out.strip().splitlines()[-1])


def build(app: Path, out: Path, *, ui_built: bool = False) -> Path:
    """Build the app's package into ``out``; returns its path. Raises PackageError with words."""
    backend = app / "backend"
    if not (backend / "pyproject.toml").is_file() or not (backend / "uv.lock").is_file():
        raise PackageError(f"{backend} needs pyproject.toml and uv.lock.")
    project, module = _project(backend)
    lock_text = (backend / "uv.lock").read_text(encoding="utf-8")
    local = local_packages(lock_text)
    if KIT not in local:
        raise PackageError(f"The app doesn't take {KIT} from a local folder: is it an app on the kit?")
    kit_version = next(p["version"] for p in tomllib.loads(lock_text)["package"] if p["name"] == KIT)

    with tempfile.TemporaryDirectory(prefix="hiro-package-") as tmp:
        stage = Path(tmp)
        declared = _declaration(backend, module, stage / "data")
        if declared["version"] != project["version"]:
            raise PackageError(
                f"The app declares version {declared['version']} to the core but pyproject.toml says "
                f"{project['version']}."
            )
        if declared["asks"] is None:
            # The person installing it approves what it asks before anything is made: an app that says nothing
            # would be installed with its asks unknown, and every one would wait on the Extensions page
            raise PackageError(
                "The app doesn't say what it asks to do on its own: set Extension(asks=...) (asks=() for nothing)."
            )
        manifest = Manifest(
            key=declared["key"], kind=KIND_APP, title=declared["title"], version=project["version"],
            core=core_range(kit_version), command=command_of(project), port=declared["port"],
            predeploy=f"python -m {module}.predeploy" if (backend / "src" / module / "predeploy.py").is_file() else "",
            health=HEALTH, site=declared["site"], asks=tuple(declared["asks"]),
        )
        ui = _build_ui(app / "frontend", ui_built)
        copy = _stage_backend(backend, module, ui, stage)
        wheels = stage / "wheels"
        _run(["uv", "build", "--wheel", "--out-dir", str(wheels)], copy)
        for path in local.values():
            _run(["uv", "build", "--wheel", "--out-dir", str(wheels), str((backend / path).resolve())], backend)
        requirements = _run(
            ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-emit-local",
             "--format", "requirements.txt", "--no-header"],
            backend,
        )
        out.mkdir(parents=True, exist_ok=True)
        package = out / f"{dashed(manifest.key)}-{manifest.version}.zip"
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST_FILE, render_manifest(manifest))
            zf.writestr("requirements.txt", requirements)
            for wheel in sorted(wheels.glob("*.whl")):
                zf.write(wheel, f"wheels/{wheel.name}")
    return package


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build an app's package for `hiro extension install`.")
    parser.add_argument("app", type=Path, help="the app's folder (backend/ and frontend/)")
    parser.add_argument("--out", type=Path, default=Path("dist"), help="where the package goes (default: dist)")
    parser.add_argument("--ui-built", action="store_true", help="use frontend/build as it is, without npm")
    args = parser.parse_args(argv)
    try:
        package = build(args.app.resolve(), args.out.resolve(), ui_built=args.ui_built)
    except PackageError as exc:
        print(f"Can't build the package: {exc}", file=sys.stderr)
        return 1
    print(package)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
