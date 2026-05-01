# hiro-commons

> **Internal package — not a public API.**
> This package exists so that `hirocli` and `hirogate` can share infrastructure
> code (constants, crypto, timestamp helpers, structured logging setup) without
> creating a sideways dependency between the two top-level packages.
>
> It is published to PyPI only because `hirogate` is independently distributable
> (e.g. on a VPS) and must therefore resolve `hiro-commons` from a public index.
>
> External code should not depend on `hiro-commons` directly. APIs may break
> between releases without notice. Pin an exact version if you must use it.

## What's inside

- `hiro_commons.constants` — shared infrastructure constants
  (network ports, timing defaults, storage paths, domain names).
  See [Constants architecture](https://docs.hiroleague.com/architecture/components/constants).
- `hiro_commons.crypto` — Ed25519 / signing primitives shared between server
  and gateway.
- Other cross-cutting helpers (timestamps, structured logging setup, etc.).

## Versioning

Released in lockstep with the rest of the Hiro League workspace; cross-package
pins use `~=X.Y.Z`. See
[Packaging releases](https://docs.hiroleague.com/build/local-build/packaging-releases).
