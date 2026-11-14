# syntax=docker/dockerfile:1
# Every Hiro app's image (HomeHiro, NetHiro, TrainHiro, StudyHiro): one copy, here in HiroLeague, that each app's
# compose.yaml builds from its own folder (shared-code plan, step 2):
#
#   build:
#     context: .
#     dockerfile: ../hiroleague/build-kit/Dockerfile
#     additional_contexts:
#       hiroleague: ../hiroleague
#
# The app's own facts (its package name and port) are in its app.env, which compose.yaml also passes to the container:
# the image that runs starts `uvicorn <APP>.main:app` on 127.0.0.1:<APP_PORT>, so one Dockerfile serves every app.
#
# A deploy builds only the app (the default target): the check before the push (./scripts/check.sh on the PC) is the
# gate, and the full check (the `fullcheck` target: the UI's svelte-check, ESLint and vitest, the backend checks app.env
# lists) runs every night on the server (build-kit/nightly-check.sh, reported to NetHiro's System health). The npm and
# uv downloads are kept between builds (cache mounts), and the third-party Python packages are installed before
# HiroLeague's SDK and kits are copied in, so a core deploy doesn't reinstall them all (a change to uv.lock does).

# 1) The UI's sources and packages
FROM node:24-alpine AS ui-src
WORKDIR /ui
# The shared UI kit (@hiroleague/ui): read at ../../hiroleague/ui-kit from frontend/, so /hiroleague/ui-kit in the image.
# It comes from the HiroLeague checkout beside the app (the build context "hiroleague", as the SDK does below);
# `npm run kit` (the kit's scripts/kit-sync.mjs, run by the app's build and check) copies its src/lib to frontend/.kit,
# where the app reads it. .npmrc: an app may have none.
COPY --from=hiroleague ui-kit /hiroleague/ui-kit
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc* ./
RUN --mount=type=cache,target=/root/.npm npm ci --prefer-offline --no-audit --no-fund
COPY frontend/ ./

# 2) The SvelteKit UI built to static files (what a deploy needs)
FROM ui-src AS ui
RUN npm run build

# 3) The UI's check (the nightly full check): svelte-check, ESLint and vitest side by side, since they don't depend on
#    each other (ESLint's type-aware rules take ~80 s alone): the same checks as the app's `npm run check`. Any failure
#    fails the target. `npm run kit` first: vite.config.ts reads the kit's copy (.kit), which this stage doesn't get
#    from `npm run build`.
FROM ui-src AS ui-check
RUN set -e; npm run kit; npx svelte-kit sync; \
    (npx svelte-check --tsconfig ./tsconfig.json > /tmp/svelte-check.log 2>&1; echo $? > /tmp/svelte-check.rc) & \
    (npx eslint . > /tmp/eslint.log 2>&1; echo $? > /tmp/eslint.rc) & \
    (npx vitest run > /tmp/vitest.log 2>&1; echo $? > /tmp/vitest.rc) & \
    wait; \
    failed=0; for t in svelte-check eslint vitest; do \
      tail -3 /tmp/$t.log; \
      if [ "$(cat /tmp/$t.rc)" != 0 ]; then echo "== $t failed:"; tail -40 /tmp/$t.log; failed=1; fi; \
    done; \
    [ "$failed" = 0 ]; \
    touch /ui-checked

# 4) Node and npm, for pyright in the backend's check (stage 6) when the app runs it. The image that runs has no Node.
FROM node:24-slim AS node

# 5) The Python backend
FROM python:3.12-slim AS backend
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
# The third-party packages first, so this layer is reused until uv.lock changes. HiroLeague's SDK, commons and
# extension kit are left out here: they change with every core deploy, and copying them in before this step reinstalled
# every package.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project \
      --no-install-package hiro-channel-sdk --no-install-package hiro-commons \
      --no-install-package hiro-extension-kit
# HiroLeague's SDK, commons and extension kit (the app connects to the core as its extension; the backend every app
# shares): editable path dependencies at ../../hiroleague/... from here, so /hiroleague/... in the image, from the
# HiroLeague checkout beside the app (the build context "hiroleague"); only these folders.
COPY --from=hiroleague hiroserver/hiro-channel-sdk /hiroleague/hiroserver/hiro-channel-sdk
COPY --from=hiroleague hiroserver/hiro-commons /hiroleague/hiroserver/hiro-commons
COPY --from=hiroleague hiroserver/hiro-extension-kit /hiroleague/hiroserver/hiro-extension-kit
COPY backend/ ./
# --refresh-package: never take the SDK, commons or the kit from uv's cache. They keep version 0.2.0 while their code
# changes, and uv reuses a cached build of a same-version local package (the stale-SDK trap of 2026-11-06). They are
# editable installs, so the app reads the source copied just above.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --refresh-package hiro-channel-sdk --refresh-package hiro-commons \
      --refresh-package hiro-extension-kit
ENV STATIC_DIR=/app/static DATA_DIR=/app/data PATH="/app/.venv/bin:$PATH"

# 6) The backend's check (the nightly full check): the checks the app's app.env lists (BACKEND_CHECKS: ruff, pyright,
#    import rules, pytest), on the app's own environment plus the dev tools, with build-kit/backend-check.sh, the
#    script the app's scripts/check.sh runs on the PC. nightly-check.sh passes BACKEND_CHECKS.
FROM backend AS check
ARG BACKEND_CHECKS="ruff pytest"
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
COPY --from=hiroleague --chmod=755 build-kit/backend-check.sh /usr/local/bin/backend-check
RUN --mount=type=cache,target=/root/.cache/uv \
    ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && uv sync --frozen && IN_IMAGE=1 BACKEND_CHECKS="$BACKEND_CHECKS" backend-check && touch /checked

# 7) The nightly full check: both checks above (`docker buildx build --target fullcheck`, build-kit/nightly-check.sh)
FROM backend AS fullcheck
COPY --from=check /checked /checked
COPY --from=ui-check /ui-checked /ui-checked

# 8) The image that runs: the backend and its built UI (the default target, what a deploy builds). Loopback only: the
#    core's Caddy is the one way in, so nobody on the LAN can go around sign-in and roles (compose.yaml: host network).
#    APP and APP_PORT come from the app's app.env (compose.yaml's env_file); exec, so uvicorn gets the stop signal.
FROM backend
COPY --from=ui /ui/build /app/static
CMD ["sh", "-c", "exec uvicorn \"$APP.main:app\" --host 127.0.0.1 --port \"$APP_PORT\""]
