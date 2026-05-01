# hiroleague

Umbrella meta-package for the **Hiro League** desktop install.

This package contains no code of its own. It exists to give end users a single
install command that pulls in the desktop server and the mandatory device
channel, with the local gateway as an optional extra.

## Install matrix

| Use case | Command |
|---|---|
| Desktop install (full bundle) | `pip install hiroleague` |
| VPS gateway only | `pip install hirogate` |
| Custom embed (server only, no device channel) | `pip install hirocli` |
| Channel plugin author | `pip install hiro-channel-sdk` |

## What it pulls in

| Package | How | Notes |
|---|---|---|
| `hirocli` | direct dep | Desktop server CLI (`hiro` command) |
| `hiro-channel-devices` | direct dep | Mandatory device channel plugin (subprocess) |
| `hirogate` | transitive (via `hirocli`) | Local WebSocket relay gateway. `hirocli` imports `hirogateway.service` to manage local gateway lifecycle, so it ships unconditionally with the desktop install. |

`hiro-commons` and `hiro-channel-sdk` are pulled in transitively as
implementation details — do not depend on them directly from end-user code.

VPS deployments install `hirogate` alone (no `hiroleague`, no `hirocli`).

## Versioning

All packages in the workspace are released in lockstep at the same version
number. Cross-package dependencies are pinned with `~=X.Y.Z` so a release
line stays internally consistent.

See [Packaging releases](https://docs.hiroleague.com/build/local-build/packaging-releases)
for the release procedure and policy.

## Development

This meta-package is a uv workspace member. Developers do not normally install
it — they install the constituent packages directly:

```bash
cd hiroserver
uv sync
uv tool install --editable hirocli
uv tool install --editable channels/hiro-channel-devices
uv tool install --editable gateway
```

`./dev-sync.sh` from the repo root automates the above.
