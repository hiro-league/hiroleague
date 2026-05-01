#!/usr/bin/env bash
# Manual PyPI publish script for the Hiro League workspace.
#
# Builds every published workspace package and uploads them in dependency
# order so the cross-package `~=X.Y.Z` pins resolve correctly on the index.
#
# Modes (mutually exclusive):
#   --dry-run                Build everything and run `uv publish --dry-run`
#                            against the chosen index. No files leave the
#                            machine. Equivalent of `npm publish --dry-run`.
#   --testpypi               Publish to https://test.pypi.org/legacy/ instead
#                            of the real index. Use for smoke testing before a
#                            real release.
#   (no flag)                Publish to PyPI (the real one). Will prompt twice
#                            unless --yes is given.
#
# Auth:
#   PyPI accepts only API tokens for upload. Generate one at:
#     https://pypi.org/manage/account/token/
#     https://test.pypi.org/manage/account/token/
#
#   This script reads the token from (in priority order):
#     1. --token <TOKEN>                 (CLI flag — fastest, but visible in
#                                         shell history)
#     2. UV_PUBLISH_TOKEN env var        (recommended)
#     3. ~/.pypirc                       (auto-detected, see below)
#     4. Interactive prompt              (hidden input)
#
#   Note: dry-run also requires a token. uv publish --dry-run still does an
#   auth handshake; it just skips the upload itself. Use any junk-but-shaped
#   token (`pypi-anything`) for offline dry-run if you don't have a real one
#   handy.
#
# ~/.pypirc:
#   You can put your token in ~/.pypirc instead of an env var. Format:
#     [pypi]
#     username = __token__
#     password = pypi-AgEIcHlwaS5vcmcCJDU4...   (your real PyPI token)
#
#     [testpypi]
#     repository = https://test.pypi.org/legacy/
#     username = __token__
#     password = pypi-AgENdGVzdC5weXBpLm9yZw...   (your TestPyPI token —
#                                                  separate from PyPI!)
#
#   On Windows + Git Bash the file lives at C:\Users\<you>\.pypirc.
#   On macOS/Linux it's ~/.pypirc. Permissions: chmod 600 ~/.pypirc.
#   This script auto-loads from ~/.pypirc when no token is otherwise provided.
#
# Other flags:
#   --yes                    Skip the final confirmation prompt.
#   --skip-build             Reuse whatever is already in hiroserver/dist/.
#                            Use when re-running after a partial failure.
#                            Implies --skip-frontend.
#   --skip-frontend          Skip the admin_frontend Svelte build. Use when
#                            you know admin_frontend/dist/ → hirocli's static
#                            artifacts are already up to date.
#   --token <TOKEN>          Pass token on the CLI instead of prompting.
#                            (Less safe — shows up in shell history.)
#
# Exit codes:
#   0  Success.
#   1  User aborted or invalid arguments.
#   2  Build or publish failed.
#
# This script is the manual / emergency path. The blessed flow is the
# `publish-pypi.yml` GitHub Actions workflow with PyPI Trusted Publishing
# (no token needed). See:
#   https://docs.hiroleague.com/build/local-build/packaging-releases

set -euo pipefail

# ---- Constants ------------------------------------------------------------

# Dependency order — leaves first. PyPI's resolver only sees what's already on
# the index, so the lockstep `~=X.Y.Z` cross-pins force this order. Do not
# reorder this list.
PACKAGES_BUILD_PATHS=(
    "hiro-commons"
    "hiro-channel-sdk"
    "gateway"
    "channels/hiro-channel-devices"
    "hirocli"
    "hiroleague"
)

# Wheel/sdist filename prefixes (PEP 427: hyphens become underscores in
# distribution filenames).
PACKAGES_DIST_PREFIXES=(
    "hiro_commons"
    "hiro_channel_sdk"
    "hirogate"
    "hiro_channel_devices"
    "hirocli"
    "hiroleague"
)

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="${REPO_ROOT}/hiroserver"
DIST_DIR="${WORKSPACE_DIR}/dist"
ADMIN_FRONTEND_DIR="${REPO_ROOT}/admin_frontend"

# ---- Argument parsing -----------------------------------------------------

mode="prod"
skip_build=false
skip_frontend=false
yes=false
token=""
token_from_flag=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)        mode="dry-run"; shift ;;
        --testpypi)       mode="testpypi"; shift ;;
        --yes|-y)         yes=true; shift ;;
        --skip-build)     skip_build=true; skip_frontend=true; shift ;;
        --skip-frontend)  skip_frontend=true; shift ;;
        --token)          token_from_flag="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' | head -n -2
            exit 0
            ;;
        *)
            echo "error: unknown argument: $1" >&2
            echo "run with --help for usage" >&2
            exit 1
            ;;
    esac
done

# ---- Mode-specific config -------------------------------------------------

case "$mode" in
    dry-run)
        index_label="DRY RUN (no upload)"
        publish_url=""
        check_url=""
        extra_publish_args=("--dry-run")
        ;;
    testpypi)
        index_label="TestPyPI (https://test.pypi.org)"
        publish_url="https://test.pypi.org/legacy/"
        check_url="https://test.pypi.org/simple/"
        extra_publish_args=()
        ;;
    prod)
        index_label="PyPI (https://pypi.org) — PRODUCTION"
        publish_url="https://upload.pypi.org/legacy/"
        check_url="https://pypi.org/simple/"
        extra_publish_args=()
        ;;
esac

# ---- Pre-flight -----------------------------------------------------------

echo ""
echo "================================================================"
echo "  Hiro League — manual PyPI publish"
echo "  target: ${index_label}"
echo "================================================================"
echo ""

if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv is not installed or not on PATH" >&2
    echo "       install from https://docs.astral.sh/uv/" >&2
    exit 1
fi

cd "${WORKSPACE_DIR}"

# Sync the workspace so the build environment matches uv.lock.
echo "==> Syncing workspace (uv sync --frozen)"
uv sync --frozen

# Production safety prompt — done first so an aborted run doesn't waste a token
# entry.
if [[ "$mode" == "prod" && "$yes" != "true" ]]; then
    echo ""
    echo "About to publish all packages to PRODUCTION PyPI."
    echo "This is irreversible — PyPI does not allow re-uploading the same"
    echo "version even after deletion."
    echo ""
    read -r -p "Type 'publish' to confirm: " confirmation
    if [[ "$confirmation" != "publish" ]]; then
        echo "aborted." >&2
        exit 1
    fi
fi

# ---- Token resolution -----------------------------------------------------
# uv publish needs a token even in --dry-run on uv 0.10.x (it goes through the
# auth handshake; only the actual upload is skipped). Resolve a token from one
# of four sources, in priority order, before any uv publish call.

token_source=""

# Source 1: --token CLI flag (highest priority).
if [[ -n "$token_from_flag" ]]; then
    token="$token_from_flag"
    token_source="--token flag"
fi

# Source 2: UV_PUBLISH_TOKEN env var.
if [[ -z "$token" && -n "${UV_PUBLISH_TOKEN:-}" ]]; then
    token="$UV_PUBLISH_TOKEN"
    token_source="UV_PUBLISH_TOKEN env var"
fi

# Source 3: ~/.pypirc — parse [pypi] (or [testpypi]) section for `password = ...`
if [[ -z "$token" && -f "${HOME}/.pypirc" ]]; then
    pypirc_section="pypi"
    if [[ "$mode" == "testpypi" ]]; then
        pypirc_section="testpypi"
    fi
    # Match the section header, then read forward to the next section header
    # or EOF, and grab the first `password = ...` line. Tolerates whitespace
    # around the `=`.
    token=$(awk -v section="[${pypirc_section}]" '
        $0 == section { in_section = 1; next }
        /^\[/ { in_section = 0 }
        in_section && /^[[:space:]]*password[[:space:]]*=/ {
            sub(/^[[:space:]]*password[[:space:]]*=[[:space:]]*/, "")
            print
            exit
        }
    ' "${HOME}/.pypirc")
    if [[ -n "$token" ]]; then
        token_source="~/.pypirc [${pypirc_section}]"
    fi
fi

# Source 4: prompt.
if [[ -z "$token" ]]; then
    if [[ -t 0 ]]; then
        echo ""
        echo "Enter ${index_label%% *} token (input is hidden; starts with 'pypi-'):"
        read -r -s token
        echo ""
        token_source="interactive prompt"
    else
        echo "error: no token provided and stdin is not a TTY" >&2
        echo "       set UV_PUBLISH_TOKEN, add it to ~/.pypirc, or pass --token <TOKEN>" >&2
        exit 1
    fi
fi

# Validate the token shape — empty or wrong-prefix tokens cause uv to fall back
# to interactive username/password prompts.
if [[ -z "$token" ]]; then
    echo "error: empty token" >&2
    exit 1
fi
if [[ "$token" != pypi-* ]]; then
    echo "error: token does not look like a PyPI token (must start with 'pypi-')" >&2
    echo "       generate one at https://pypi.org/manage/account/token/" >&2
    exit 1
fi

echo "==> Auth: token loaded from ${token_source} (${#token} chars, prefix '${token:0:5}...')"

# ---- Build admin_frontend (Svelte → hirocli static artifact) -------------

# hirocli's pyproject ships `src/hirocli/admin_svelte/static/**` as a wheel
# artifact. Those files are produced by the admin_frontend Svelte build, which
# writes directly into hirocli's source tree (see admin_frontend/svelte.config.js).
# Without this step the hirocli wheel ships an empty admin UI.
if [[ "$skip_frontend" == "true" ]]; then
    echo ""
    echo "==> Skipping admin_frontend build"
else
    if [[ ! -d "${ADMIN_FRONTEND_DIR}" ]]; then
        echo "error: admin_frontend directory not found at ${ADMIN_FRONTEND_DIR}" >&2
        exit 2
    fi
    if ! command -v npm >/dev/null 2>&1; then
        echo "error: npm is not installed or not on PATH" >&2
        echo "       install Node.js >= 22.12 (https://nodejs.org/)" >&2
        exit 1
    fi
    echo ""
    echo "==> Building admin_frontend (Svelte → hirocli/admin_svelte/static)"
    # `npm ci` for a deterministic install based on package-lock.json (matches
    # what GitHub Actions would do for a release build). `npm run package:python`
    # runs vite build with the static adapter that writes into hirocli.
    (cd "${ADMIN_FRONTEND_DIR}" && npm ci && npm run package:python)
fi

# ---- Build Python packages ------------------------------------------------

if [[ "$skip_build" == "true" ]]; then
    echo ""
    echo "==> Skipping Python build (using existing ${DIST_DIR})"
else
    echo ""
    echo "==> Cleaning ${DIST_DIR}"
    rm -rf "${DIST_DIR}"

    echo "==> Building all Python packages"
    for pkg_path in "${PACKAGES_BUILD_PATHS[@]}"; do
        echo ""
        echo "    -> ${pkg_path}"
        uv build "${pkg_path}"
    done
fi

# ---- Publish --------------------------------------------------------------

echo ""
echo "==> Publishing to ${index_label}"

# Always unset stale username/password env vars from the parent shell — these
# can come from previous twine/uv runs and silently override the token, leading
# to "Enter username/password" prompts even when we passed a token.
unset UV_PUBLISH_USERNAME UV_PUBLISH_PASSWORD TWINE_USERNAME TWINE_PASSWORD

# Pass the token via UV_PUBLISH_TOKEN env var rather than --token on the
# command line:
#   - never appears in `ps`, shell history, or process listings
#   - same mechanism uv itself documents
#   - inherited by every `uv publish` call we make below
#   - required even for --dry-run on uv 0.10.x (the auth handshake still runs)
export UV_PUBLISH_TOKEN="$token"

# Build the (non-secret) args common to every per-package publish call.
common_publish_args=()
if [[ -n "$publish_url" ]]; then
    common_publish_args+=("--publish-url" "$publish_url")
fi
# --check-url makes reruns idempotent: already-uploaded files are skipped
# instead of failing the whole script. Safe to use in dry-run too now that we
# always provide auth.
if [[ -n "$check_url" ]]; then
    common_publish_args+=("--check-url" "$check_url")
fi
# Disable trusted-publishing auto-detection. This script is the manual path;
# OIDC only works inside GitHub Actions, and leaving detection on prints
# spurious "trusted publishing failed" notices.
common_publish_args+=("--trusted-publishing" "never")

# Echo the command line we're about to run (without the token) so the user can
# see exactly what's happening if uv ever falls back to a prompt.
echo ""
echo "    uv publish ${common_publish_args[*]} ${extra_publish_args[*]:-} <files>"

for prefix in "${PACKAGES_DIST_PREFIXES[@]}"; do
    echo ""
    echo "    -> ${prefix}"
    # shellcheck disable=SC2206  # we want word splitting on the glob expansion
    files=( "${DIST_DIR}/${prefix}-"*.whl "${DIST_DIR}/${prefix}-"*.tar.gz )
    if [[ ! -e "${files[0]}" ]]; then
        echo "error: no built distributions found for ${prefix} in ${DIST_DIR}" >&2
        echo "       (did the build step succeed? try without --skip-build)" >&2
        exit 2
    fi
    # Redirect stdin from /dev/null so uv publish CAN'T fall back to interactive
    # prompts even if its auth resolution somehow decides to ask. With this in
    # place, any auth failure surfaces as a clean error instead of a hanging
    # prompt — and you immediately know the token didn't reach uv.
    uv publish "${common_publish_args[@]}" "${extra_publish_args[@]}" "${files[@]}" </dev/null
done

echo ""
echo "================================================================"
case "$mode" in
    dry-run)
        echo "  Dry run complete. No files were uploaded."
        ;;
    testpypi)
        echo "  Published to TestPyPI."
        echo ""
        echo "  Smoke test in a clean venv:"
        echo "    pip install --index-url https://test.pypi.org/simple/ \\"
        echo "                --extra-index-url https://pypi.org/simple/ \\"
        echo "                hiroleague"
        ;;
    prod)
        echo "  Published to PyPI."
        echo ""
        echo "  Verify in a clean venv:"
        echo "    pip install -U hiroleague"
        echo ""
        echo "  If you used a manually generated token, REVOKE it now at:"
        echo "    https://pypi.org/manage/account/token/"
        ;;
esac
echo "================================================================"
