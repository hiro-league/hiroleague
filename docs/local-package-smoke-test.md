# Local package smoke test

Use this before publishing when you want to verify the exact wheels produced by
the current checkout. This catches installed-package runtime bugs that workspace
tests can miss.

## Build local wheels

From the workspace root:

```powershell
cd D:\projects\hiroleague\hiroserver

uv build --package hiro-commons
uv build --package hiro-channel-sdk
uv build --package hirogate
uv build --package hiro-channel-devices
uv build --package hirocli
uv build --package hiroleague
```

## Create a disposable venv

Create the venv outside the uv workspace:

```powershell
cd D:\projects\hiroleague
python -m venv .smoke-runtime
.\.smoke-runtime\Scripts\Activate.ps1
```

## Install the local wheels

Install the wheel files directly, not the versions already published on PyPI:

```powershell
pip install `
  .\hiroserver\dist\hiro_commons-0.1.1-py3-none-any.whl `
  .\hiroserver\dist\hiro_channel_sdk-0.1.1-py3-none-any.whl `
  .\hiroserver\dist\hirogate-0.1.1-py3-none-any.whl `
  .\hiroserver\dist\hiro_channel_devices-0.1.1-py3-none-any.whl `
  .\hiroserver\dist\hirocli-0.1.1-py3-none-any.whl `
  .\hiroserver\dist\hiroleague-0.1.1-py3-none-any.whl
```

Replace `0.1.1` with the version you just built.

## Verify runtime behavior

```powershell
where.exe hiro
hiro status
hiro start
hiro status
hiro stop
```

The important signal is that `hiro start` runs from the venv install and does
not rely on a source uv workspace. For the packaged runtime path, failures like
`Could not find uv workspace root` are release blockers.
