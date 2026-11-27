# Hiro League

Hiro is your private, personal assistant. It works for you, your home, and your family.

**This package is still in early development and not yet ready for use.**

## Install (end users)

```bash
uv tool install hiroleague
```

On Linux, add `--torch-backend cpu`: the local reranker's torch then comes without NVIDIA's ~2 GB of GPU libraries. For
the GPU build, name another backend (`--torch-backend auto`, or one such as `cu130`).

## Upgrade

To pull the latest version from PyPI, use the bundled command:

```bash
hiro upgrade
```

`hiro upgrade` detects how Hiro is installed (uv tool / pipx / pip), stops
the server if it's running, runs the appropriate upgrade command, and
restarts the server afterwards. For uv-tool installs it uses
`uv tool upgrade --reinstall hiroleague` to refresh uv's resolver cache —
that is safe because Python wheels have no install/uninstall hooks and your
workspace data lives outside the tool venv. On Linux it installs again with the
torch build you have (`uv tool install --upgrade --reinstall --torch-backend cpu
hiroleague`, or your GPU one), which uv doesn't remember by itself.

Add `--dry-run` to see what would run without changing anything, or `--yes`
to skip the confirmation prompt.

## Links

| Resource | URL |
|----------|-----|
| Website | [hiroleague.com](https://www.hiroleague.com) |
| Documentation | [docs.hiroleague.com](https://docs.hiroleague.com) |
| Source | [github.com/hiro-league/hiroleague](https://github.com/hiro-league/hiroleague) |

## License

MIT — see the [LICENSE](https://github.com/hiro-league/hiroleague/blob/main/LICENSE) file in the repository.
