# Every Hiro app's local dev, one command, first time or any time after: one copy, here in HiroLeague, which each app's
# dev.ps1 runs (shared-code plan, step 2):
#   .\dev            install/update dependencies, then run backend + frontend with live reload
# The app's facts come from its app.env: its package (APP), name (APP_NAME), and dev ports (DEV_PORT for the backend,
# DEV_UI_PORT for the UI, the one to open). Ctrl+C stops both.
param([Parameter(Mandatory)] [string] $Root)
$ErrorActionPreference = 'Stop'
$backend = Join-Path $Root 'backend'
$frontend = Join-Path $Root 'frontend'

# KEY=value lines (bash-style: a value may be quoted, a # starts a comment), as the deploy reads them too
function Read-EnvFile([string] $path) {
    $values = @{}
    foreach ($line in Get-Content $path) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=("([^"]*)"|''([^'']*)''|([^#\s]*))') {
            $values[$Matches[1]] = if ($Matches[3] -ne $null) { $Matches[3] } elseif ($Matches[4] -ne $null) { $Matches[4] } else { $Matches[5] }
        }
    }
    return $values
}

$app = Read-EnvFile (Join-Path $Root 'app.env')
foreach ($key in 'APP', 'APP_NAME', 'DEV_PORT', 'DEV_UI_PORT') {
    if (-not $app[$key]) { throw "app.env has no $key" }
}
$name = $app.APP_NAME
$apiPort = [int]$app.DEV_PORT
$uiPort = [int]$app.DEV_UI_PORT

foreach ($tool in 'uv', 'npm') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is not installed or not on PATH" }
}

# Dev settings: created once from the example, never committed (OUTPUTS=off where the app sends or speaks anything,
# AUTH=off where it has its own sign-in).
$envDev = Join-Path $Root '.env.dev'
if (-not (Test-Path $envDev)) {
    Copy-Item (Join-Path $Root '.env.example') $envDev
    Write-Host 'Created .env.dev from .env.example' -ForegroundColor Yellow
}
# Load it into this session, so the backend (started below) sees it.
foreach ($line in Get-Content $envDev) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
        Set-Item "env:$($Matches[1])" $Matches[2]
    }
}

# A previous run that was not stopped cleanly still holds the ports: stop it.
foreach ($port in $apiPort, $uiPort) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object {
            Write-Host "Stopping old process on port $port (pid $($_.OwningProcess))" -ForegroundColor Yellow
            & taskkill /PID $_.OwningProcess /T /F | Out-Null
        }
}

Write-Host '== Backend dependencies (uv sync)' -ForegroundColor Cyan
Push-Location $backend
try { uv sync; if ($LASTEXITCODE) { throw 'uv sync failed' } } finally { Pop-Location }

Write-Host '== Frontend dependencies (npm install)' -ForegroundColor Cyan
Push-Location $frontend
try { npm install --no-audit --no-fund; if ($LASTEXITCODE) { throw 'npm install failed' } } finally { Pop-Location }

Write-Host "== Starting backend on :$apiPort (own minimized window, `"$name backend`") and UI on :$uiPort (Ctrl+C stops both)" -ForegroundColor Cyan
# The backend gets its own console window: on Windows, uvicorn's auto-reload stops the old server with
# a Ctrl+C sent to the whole console, which would also kill the UI server and this script.
# -NoExit keeps the window open after a crash, so its error stays readable.
# uvicorn rather than `fastapi dev` (the same server) for --timeout-graceful-shutdown: a reload waits
# for open requests, and one that never ends would hold the backend down; after 3 s it is cut off.
# (The browsers' /api/events streams end by themselves when the server stops: live.py.)
$backendCmd = "`$host.UI.RawUI.WindowTitle = '$name backend'; uv run uvicorn $($app.APP).main:app --reload --reload-dir src --port $apiPort --timeout-graceful-shutdown 3"
$api = Start-Process powershell -ArgumentList '-NoProfile', '-NoExit', '-Command', $backendCmd `
    -WorkingDirectory $backend -WindowStyle Minimized -PassThru
Push-Location $frontend
try {
    # Let the API come up first, so the page's first request does not hit a closed port.
    foreach ($i in 1..30) {
        if ($api.HasExited) { throw "Backend failed to start (see the `"$name backend`" window)" }
        if (Get-NetTCPConnection -LocalPort $apiPort -State Listen -ErrorAction SilentlyContinue) { break }
        Start-Sleep -Milliseconds 500
    }
    npm run dev -- --port $uiPort --strictPort
} finally {
    Pop-Location
    if (-not $api.HasExited) { & taskkill /PID $api.Id /T /F | Out-Null }
    Write-Host 'Stopped backend and UI.' -ForegroundColor Cyan
}
