[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateRange(1, 16)]
    [int]$Parallel,
    [ValidateRange(5, 120)]
    [int]$ShutdownTimeoutSeconds = 30,
    [ValidateRange(5, 120)]
    [int]$StartupTimeoutSeconds = 30,
    [double]$MinFreeRamGB = 12,
    [double]$MinVirtualFreeGB = 40,
    [string]$OllamaAppPath = "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
)

$ErrorActionPreference = "Stop"
$processNames = @("ollama app", "ollama", "llama-server")

function Get-OllamaProcesses {
    @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -in $processNames
    })
}

function Get-MemoryStatus {
    $operatingSystem = Get-CimInstance Win32_OperatingSystem
    [pscustomobject]@{
        FreeRamGB = [math]::Round($operatingSystem.FreePhysicalMemory / 1MB, 2)
        VirtualFreeGB = [math]::Round($operatingSystem.FreeVirtualMemory / 1MB, 2)
    }
}

function Wait-Until {
    param(
        [scriptblock]$Condition,
        [int]$TimeoutSeconds,
        [string]$FailureMessage
    )

    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    while ($stopwatch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if (& $Condition) {
            return
        }
        Start-Sleep -Milliseconds 500
    }

    throw $FailureMessage
}

if (-not (Test-Path -LiteralPath $OllamaAppPath)) {
    throw "Ollama desktop application was not found at '$OllamaAppPath'."
}

Write-Host "Stopping Ollama and all llama-server children..."

# Ask the desktop app and server to stop first, then force-stop anything that remains.
Get-OllamaProcesses |
    Where-Object { $_.ProcessName -ne "llama-server" } |
    Stop-Process -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Get-OllamaProcesses | Stop-Process -Force -ErrorAction SilentlyContinue

Wait-Until -TimeoutSeconds $ShutdownTimeoutSeconds `
    -FailureMessage "Ollama processes did not terminate within $ShutdownTimeoutSeconds seconds." `
    -Condition { (Get-OllamaProcesses).Count -eq 0 }

Wait-Until -TimeoutSeconds $ShutdownTimeoutSeconds `
    -FailureMessage "Memory did not recover to at least $MinFreeRamGB GB RAM and $MinVirtualFreeGB GB virtual memory. Ollama was not restarted." `
    -Condition {
        $memory = Get-MemoryStatus
        $memory.FreeRamGB -ge $MinFreeRamGB -and
            $memory.VirtualFreeGB -ge $MinVirtualFreeGB
    }

$memoryBeforeStart = Get-MemoryStatus
Write-Host "Recovered memory: $($memoryBeforeStart.FreeRamGB) GB RAM, $($memoryBeforeStart.VirtualFreeGB) GB virtual."

$parallelValue = [string]$Parallel
[Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL", $parallelValue, "User")
$env:OLLAMA_NUM_PARALLEL = $parallelValue

Write-Host "Starting Ollama with OLLAMA_NUM_PARALLEL=$Parallel..."
$startedAt = Get-Date
Start-Process -FilePath $OllamaAppPath -WindowStyle Hidden

Wait-Until -TimeoutSeconds $StartupTimeoutSeconds `
    -FailureMessage "Ollama did not respond within $StartupTimeoutSeconds seconds." `
    -Condition {
        try {
            $null = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 2
            $true
        } catch {
            $false
        }
    }

$logDirectory = Join-Path $env:LOCALAPPDATA "Ollama"
$activeConfigLine = $null
Wait-Until -TimeoutSeconds $StartupTimeoutSeconds `
    -FailureMessage "The new Ollama server log did not report OLLAMA_NUM_PARALLEL=$Parallel." `
    -Condition {
        $latestLog = Get-ChildItem -LiteralPath $logDirectory -Filter "server*.log" -File |
            Where-Object { $_.LastWriteTime -ge $startedAt.AddSeconds(-1) } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if (-not $latestLog) {
            return $false
        }

        $script:activeConfigLine = (Select-String -LiteralPath $latestLog.FullName -Pattern 'server config' |
            Select-Object -Last 1).Line
        $script:activeConfigLine -match "OLLAMA_NUM_PARALLEL:$Parallel(?:\s|])"
    }

$persistedValue = [Environment]::GetEnvironmentVariable("OLLAMA_NUM_PARALLEL", "User")
if ($persistedValue -ne $parallelValue) {
    throw "Persisted OLLAMA_NUM_PARALLEL is '$persistedValue'; expected '$parallelValue'."
}

$ollamaProcesses = @(Get-OllamaProcesses | Where-Object {
    $_.ProcessName -in @("ollama app", "ollama")
})
if ($ollamaProcesses.Count -lt 2) {
    throw "Ollama responded, but the expected desktop and server processes were not both present."
}

Write-Host ""
[pscustomobject]@{
    PersistedParallel = $persistedValue
    ActiveParallel = $Parallel
    FreeRamBeforeStartGB = $memoryBeforeStart.FreeRamGB
    VirtualFreeBeforeStartGB = $memoryBeforeStart.VirtualFreeGB
    StartedAt = $startedAt.ToString("yyyy-MM-dd HH:mm:ss")
} | Format-List

Write-Host "PASS: Ollama restarted cleanly with OLLAMA_NUM_PARALLEL=$Parallel." -ForegroundColor Green
Write-Host "Run scripts\check-ollama-parallel.ps1 after the model loads to verify runner slots and context."
