"""Microsoft's Visual C++ runtime on Windows: the core's graph database (Kuzu) needs MSVCP140.dll, which a fresh
Windows doesn't have and Python doesn't bring (it brings vcruntime140.dll only). Without it the core can't start.

``hiro service install`` (already an administrator) brings it, as most Windows installers do: Microsoft's own
installer, from Microsoft's link, run only when Microsoft signed it, without its window. The command says so on screen
before it starts. When it can't (no network, a refused signature), the install goes on and says what to install, and
the core says the same when it can't load the runtime.
"""

from __future__ import annotations

import os
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import truststore
from hiro_commons.log import Logger

log = Logger.get("CLI.SERVICE")

# Microsoft's permanent link to the current x64 Visual C++ Redistributable (2015 to 2022 and later share MSVCP140)
INSTALLER_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
SIGNER = "O=Microsoft Corporation"
# 3010: done, a restart finishes it (the core doesn't need one); 1638: this version or a newer one is installed
INSTALLED_CODES = (0, 3010, 1638)
BY_HAND = f"install Microsoft's Visual C++ Redistributable (x64) from {INSTALLER_URL}, then start the core again"
_TIMEOUT_S = 600


def library() -> Path:
    return Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32" / "msvcp140.dll"


def missing() -> bool:
    return not library().is_file()


def _download(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # The system checks the certificate (truststore): a fresh Windows refuses Python's own check of Microsoft's
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with urllib.request.urlopen(INSTALLER_URL, timeout=_TIMEOUT_S, context=context) as response, dest.open("wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)


def signer_of(path: Path) -> str:
    """Who signed the file, when Windows finds the signature valid; "" otherwise."""
    # The path goes in the environment: -Command joins any further argument into the script's own text
    script = ("$s = Get-AuthenticodeSignature -LiteralPath $env:HIRO_SIGNED_FILE; "
              "if ($s.Status -eq 'Valid') { $s.SignerCertificate.Subject }")
    result = subprocess.run(  # noqa: S603 — Windows' own PowerShell, a fixed script, no shell
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],  # noqa: S607
        capture_output=True, text=True, timeout=60, check=False, env={**os.environ, "HIRO_SIGNED_FILE": str(path)},
    )
    return result.stdout.strip()


def install(cache: Path) -> str:
    """Install the runtime when it's missing. Returns what to tell the person; never raises for a failure."""
    if not missing():
        return "present"
    installer = cache / "vc_redist.x64.exe"
    try:
        _download(installer)
        signer = signer_of(installer)
        if SIGNER not in signer:
            log.warning("⚠️ The C++ runtime's installer isn't signed by Microsoft, so it wasn't run — HiroServer · service",
                        url=INSTALLER_URL, signer=signer or "none")
            return f"not installed (the download isn't signed by Microsoft): {BY_HAND}"
        result = subprocess.run(  # noqa: S603 — Microsoft's signed installer, fixed arguments
            [str(installer), "/install", "/quiet", "/norestart"], capture_output=True, timeout=_TIMEOUT_S, check=False,
        )
    except (urllib.error.URLError, OSError, subprocess.SubprocessError) as exc:
        log.warning("⚠️ The C++ runtime couldn't be installed — HiroServer · service", url=INSTALLER_URL,
                    error=str(getattr(exc, "reason", None) or exc))
        return f"not installed: {BY_HAND}"
    finally:
        installer.unlink(missing_ok=True)
    if result.returncode not in INSTALLED_CODES or missing():
        log.warning("⚠️ The C++ runtime's installer ended without it — HiroServer · service", code=result.returncode)
        return f"not installed (Microsoft's installer ended with {result.returncode}): {BY_HAND}"
    log.info("✅ Microsoft's C++ runtime installed — HiroServer · service", code=result.returncode)
    return "installed now (Microsoft's Visual C++ Redistributable)"
