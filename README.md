# Hiro League

Hiro is your private, personal assistant. It works for you, your home, and your family.

** This package is still in early development and not yet ready for use **

## Install (end users)


```bash
uv tool install hiroleague --python 3.12
```

On Linux, add `--torch-backend cpu`: the local reranker's torch then comes without NVIDIA's ~2 GB of GPU libraries. For
the GPU build, name another backend (`--torch-backend auto`, or one such as `cu130`).

## Run

```bash
hiro start
```

## Links

| Resource | URL |
|----------|-----|
| Website | [hiroleague.com](https://www.hiroleague.com) |
| Documentation | [docs.hiroleague.com](https://docs.hiroleague.com) |
| Source | [github.com/hiro-league/hiroleague](https://github.com/hiro-league/hiroleague) |

## License

MIT — see [LICENSE](./LICENSE).
