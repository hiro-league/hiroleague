[CmdletBinding()]
param(
    [string]$Model = "gemma4:26b",
    [ValidateRange(1, 16)]
    [int]$ExpectedParallel = $(
        $persisted = [Environment]::GetEnvironmentVariable("OLLAMA_NUM_PARALLEL", "User")
        if ($persisted -match '^\d+$') { [int]$persisted } else { 2 }
    ),
    [ValidateRange(1024, 262144)]
    [int]$Context = 16384,
    [ValidateRange(16, 4096)]
    [int]$OutputTokens = 128,
    [string]$TracePath,
    [double]$MinStartupFreeRamGB = 12,
    [double]$MinStartupVirtualFreeGB = 40,
    [double]$MaxPagefileUsagePercent = 35,
    [double]$MinPromptTokensPerSecond = 500,
    [double]$MinOutputTokensPerSecond = 15,
    [switch]$SkipBenchmark
)

$ErrorActionPreference = "Stop"
$warnings = [System.Collections.Generic.List[string]]::new()

function Add-CheckWarning {
    param([string]$Message)

    $warnings.Add($Message)
    Write-Warning $Message
}

function Get-LatestOllamaLog {
    $ollamaLogDirectory = Join-Path $env:LOCALAPPDATA "Ollama"
    Get-ChildItem -LiteralPath $ollamaLogDirectory -Filter "server*.log" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

function Get-RepresentativeStages {
    param([string]$Path)

    foreach ($line in Get-Content -LiteralPath $Path) {
        if (-not $line.Trim()) {
            continue
        }

        $record = $line | ConvertFrom-Json
        $stages = @($record.stages | Where-Object {
            $_.source -eq "llm" -and $_.node -in @("extract_entities", "extract_facts")
        })
        if ($stages.Count -ge 2) {
            return @($stages | Select-Object -First 2)
        }
    }

    return @()
}

function Copy-MessagesWithCacheBuster {
    param(
        [object[]]$Messages,
        [string]$CacheBuster
    )

    $markedUserMessage = $false
    @($Messages | ForEach-Object {
        $content = [string]$_.content
        if (-not $markedUserMessage -and $_.role -eq "user") {
            $content = "Diagnostic request id: $CacheBuster`n$content"
            $markedUserMessage = $true
        }
        [pscustomobject]@{
            role = [string]$_.role
            content = $content
        }
    })
}

if (-not $IsWindows -and $PSVersionTable.PSEdition -eq "Core") {
    throw "This script is intended for the Windows Ollama desktop application."
}

try {
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 3
} catch {
    throw "Ollama is not responding at http://127.0.0.1:11434."
}

$logFile = Get-LatestOllamaLog
if (-not $logFile) {
    throw "No Ollama server log was found under $env:LOCALAPPDATA\Ollama."
}

Write-Host "Ollama log: $($logFile.FullName)"

$configLine = (Select-String -LiteralPath $logFile.FullName -Pattern 'server config' |
    Select-Object -Last 1).Line
if ($configLine -notmatch 'OLLAMA_NUM_PARALLEL:(\d+)') {
    Add-CheckWarning "The active OLLAMA_NUM_PARALLEL value was not found in the server log."
} else {
    $activeParallel = [int]$Matches[1]
    if ($activeParallel -ne $ExpectedParallel) {
        Add-CheckWarning "Active parallel value is $activeParallel; expected $ExpectedParallel."
    }
}

$persistedParallel = [Environment]::GetEnvironmentVariable("OLLAMA_NUM_PARALLEL", "User")
if ($persistedParallel -ne [string]$ExpectedParallel) {
    Add-CheckWarning "Persisted user OLLAMA_NUM_PARALLEL is '$persistedParallel'; expected '$ExpectedParallel'."
}

$expectedTotalContext = $ExpectedParallel * $Context
$llamaProcesses = @(Get-Process -Name "llama-server" -ErrorAction SilentlyContinue)
if (-not $SkipBenchmark -and $llamaProcesses.Count -eq 0) {
    Write-Host "Loading $Model so runner configuration can be verified..."
    $warmupBody = @{
        model = $Model
        messages = @(@{ role = "user"; content = "Reply with OK." })
        stream = $false
        keep_alive = "10m"
        options = @{
            num_ctx = $Context
            num_predict = 4
            temperature = 0
        }
    } | ConvertTo-Json -Depth 6
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/chat" -Method Post `
        -ContentType "application/json" -Body $warmupBody -TimeoutSec 300
    $logFile = Get-LatestOllamaLog
    $llamaProcesses = @(Get-Process -Name "llama-server" -ErrorAction SilentlyContinue)
}

$runnerChecksSkipped = $llamaProcesses.Count -eq 0
$startupFreeRamGB = $null
$startupVirtualFreeGB = $null
if ($llamaProcesses.Count -gt 1) {
    Add-CheckWarning "Found $($llamaProcesses.Count) llama-server processes; expected exactly one."
} elseif ($runnerChecksSkipped) {
    Write-Host "Model runner: not loaded; runner slot, context, and load-memory checks skipped."
} else {
    $runnerLine = (Select-String -LiteralPath $logFile.FullName -Pattern 'starting llama-server' |
        Select-Object -Last 1).Line
    if ($runnerLine -notmatch '(?:^|\s)-np\s+(\d+)') {
        Add-CheckWarning "The runner parallel-slot argument was not found in the server log."
    } elseif ([int]$Matches[1] -ne $ExpectedParallel) {
        Add-CheckWarning "Runner has $($Matches[1]) slots; expected $ExpectedParallel."
    }

    if ($runnerLine -notmatch '(?:^|\s)-c\s+(\d+)') {
        Add-CheckWarning "The runner total context argument was not found in the server log."
    } elseif ([int]$Matches[1] -ne $expectedTotalContext) {
        Add-CheckWarning "Runner total context is $($Matches[1]); expected $expectedTotalContext ($ExpectedParallel x $Context)."
    }

    $sequenceLine = (Select-String -LiteralPath $logFile.FullName -Pattern 'llama_context: n_seq_max' |
        Select-Object -Last 1).Line
    if ($sequenceLine -notmatch '=\s+(\d+)' -or [int]$Matches[1] -ne $ExpectedParallel) {
        Add-CheckWarning "Runner did not report the expected $ExpectedParallel active sequence slots."
    }

    $sequenceContextLine = (Select-String -LiteralPath $logFile.FullName -Pattern 'llama_context: n_ctx_seq\s+=' |
        Select-Object -Last 1).Line
    if ($sequenceContextLine -notmatch '=\s+(\d+)' -or [int]$Matches[1] -ne $Context) {
        Add-CheckWarning "Runner did not report the expected $Context-token context per sequence."
    }

    $startupMemoryLine = (Select-String -LiteralPath $logFile.FullName -Pattern 'msg="system memory"' |
        Select-Object -Last 1).Line
    if ($startupMemoryLine -match 'free="([0-9.]+) GiB"\s+free_swap="([0-9.]+) GiB"') {
        $startupFreeRamGB = [double]$Matches[1]
        $startupVirtualFreeGB = [double]$Matches[2]
        if ($startupFreeRamGB -lt $MinStartupFreeRamGB) {
            Add-CheckWarning "Runner loaded with only $startupFreeRamGB GB free RAM; minimum is $MinStartupFreeRamGB GB."
        }
        if ($startupVirtualFreeGB -lt $MinStartupVirtualFreeGB) {
            Add-CheckWarning "Runner loaded with only $startupVirtualFreeGB GB free virtual memory; minimum is $MinStartupVirtualFreeGB GB."
        }
    } else {
        Add-CheckWarning "Runner startup memory values were not found in the server log."
    }
}

try {
    $pagefileUsage = [double](Get-Counter '\Paging File(_Total)\% Usage').CounterSamples.CookedValue
    if ($pagefileUsage -gt $MaxPagefileUsagePercent) {
        Add-CheckWarning "Pagefile usage is $([math]::Round($pagefileUsage, 1))%; maximum is $MaxPagefileUsagePercent%."
    }
} catch {
    Add-CheckWarning "Could not read current pagefile usage: $($_.Exception.Message)"
    $pagefileUsage = $null
}

$benchmarkResults = @()
$concurrentWallSeconds = $null
if (-not $SkipBenchmark) {
    if (-not $TracePath) {
        $workspaceDirectory = Join-Path $env:LOCALAPPDATA "hiro\workspaces"
        $TracePath = Get-ChildItem -LiteralPath $workspaceDirectory -Filter "*.jsonl" -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.DirectoryName -like '*\logs\ingest_trace' } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1 -ExpandProperty FullName
    }

    if (-not $TracePath -or -not (Test-Path -LiteralPath $TracePath)) {
        Add-CheckWarning "No ingestion trace was available for the representative benchmark."
    } else {
        $stages = @(Get-RepresentativeStages -Path $TracePath)
        if ($stages.Count -lt 2) {
            Add-CheckWarning "Trace '$TracePath' does not contain representative entity and fact extraction prompts."
        } else {
            Add-Type -AssemblyName System.Net.Http
            $nonce = [guid]::NewGuid().ToString("N")
            $payloads = @()
            $benchmarkStages = @()
            for ($index = 0; $index -lt $ExpectedParallel; $index++) {
                $stage = $stages[$index % $stages.Count]
                $benchmarkStages += $stage
                $messages = Copy-MessagesWithCacheBuster -Messages $stage.input -CacheBuster "$nonce-$index"
                $payloads += @{
                    model = $Model
                    messages = $messages
                    stream = $false
                    keep_alive = "10m"
                    options = @{
                        num_ctx = $Context
                        num_predict = $OutputTokens
                        temperature = 0
                    }
                } | ConvertTo-Json -Depth 30 -Compress
            }

            $client = [System.Net.Http.HttpClient]::new()
            $client.Timeout = [TimeSpan]::FromMinutes(10)
            $stopwatch = [Diagnostics.Stopwatch]::StartNew()
            $tasks = @($payloads | ForEach-Object {
                $content = [System.Net.Http.StringContent]::new(
                    $_,
                    [Text.Encoding]::UTF8,
                    "application/json"
                )
                $client.PostAsync("http://127.0.0.1:11434/api/chat", $content)
            })
            [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]$tasks)
            $concurrentWallSeconds = $stopwatch.Elapsed.TotalSeconds

            for ($index = 0; $index -lt $ExpectedParallel; $index++) {
                $response = $tasks[$index].Result.Content.ReadAsStringAsync().Result | ConvertFrom-Json
                if ($response.error) {
                    Add-CheckWarning "Benchmark request $($index + 1) failed: $($response.error)"
                    continue
                }

                $promptSeconds = [double]$response.prompt_eval_duration / 1e9
                $outputSeconds = [double]$response.eval_duration / 1e9
                $promptRate = if ($promptSeconds -gt 0) { [double]$response.prompt_eval_count / $promptSeconds } else { 0 }
                $outputRate = if ($outputSeconds -gt 0) { [double]$response.eval_count / $outputSeconds } else { 0 }
                $result = [pscustomobject]@{
                    Request = $index + 1
                    Stage = $benchmarkStages[$index].node
                    InputTokens = [int]$response.prompt_eval_count
                    OutputTokens = [int]$response.eval_count
                    PromptTokSec = [math]::Round($promptRate, 1)
                    OutputTokSec = [math]::Round($outputRate, 1)
                    TotalSec = [math]::Round(([double]$response.total_duration / 1e9), 2)
                }
                $benchmarkResults += $result

                if ($result.InputTokens -lt 1000) {
                    Add-CheckWarning "Benchmark request $($index + 1) had only $($result.InputTokens) input tokens; use a larger trace prompt."
                }
                if ($promptRate -lt $MinPromptTokensPerSecond) {
                    Add-CheckWarning "Benchmark request $($index + 1) prompt rate was $([math]::Round($promptRate, 1)) tok/s; minimum is $MinPromptTokensPerSecond tok/s."
                }
                if ($outputRate -lt $MinOutputTokensPerSecond) {
                    Add-CheckWarning "Benchmark request $($index + 1) output rate was $([math]::Round($outputRate, 1)) tok/s; minimum is $MinOutputTokensPerSecond tok/s."
                }
            }

            if ($ExpectedParallel -gt 1 -and $benchmarkResults.Count -eq $ExpectedParallel) {
                $minimumRequestSeconds = ($benchmarkResults.TotalSec | Measure-Object -Minimum).Minimum
                $maximumRequestSeconds = ($benchmarkResults.TotalSec | Measure-Object -Maximum).Maximum
                if ($minimumRequestSeconds -gt 0 -and ($maximumRequestSeconds / $minimumRequestSeconds) -gt 1.5) {
                    Add-CheckWarning "Concurrent request completion times differ by more than 50%; requests may be queueing instead of running together."
                }
                if ($concurrentWallSeconds -gt ($maximumRequestSeconds * 1.15)) {
                    Add-CheckWarning "Concurrent wall time exceeds the longest request by more than 15%."
                }
            }
        }
    }
}

Write-Host ""
Write-Host "Configuration"
[pscustomobject]@{
    ExpectedParallel = $ExpectedParallel
    ContextPerSequence = $Context
    ExpectedTotalContext = $expectedTotalContext
    StartupFreeRamGB = $startupFreeRamGB
    StartupVirtualFreeGB = $startupVirtualFreeGB
    CurrentPagefilePercent = if ($null -ne $pagefileUsage) { [math]::Round($pagefileUsage, 1) } else { $null }
} | Format-List

if ($benchmarkResults.Count -gt 0) {
    Write-Host "Benchmark"
    $benchmarkResults | Format-Table -AutoSize
    Write-Host "Concurrent wall time: $([math]::Round($concurrentWallSeconds, 2))s"
}

if ($warnings.Count -gt 0) {
    Write-Host ""
    Write-Host "FAILED with $($warnings.Count) warning(s)." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
if ($runnerChecksSkipped) {
    Write-Host "INCOMPLETE: Ollama server configuration looks healthy, but runner checks were skipped because no model is loaded." -ForegroundColor Yellow
} else {
    Write-Host "PASS: Ollama parallel configuration and representative throughput look healthy." -ForegroundColor Green
}
