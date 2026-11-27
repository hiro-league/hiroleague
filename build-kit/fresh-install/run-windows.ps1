# A person's whole path on a fresh Windows, run inside Windows Sandbox by fresh.py (never on a machine anyone uses):
# uv, the core, `hiro service install`, Hello's install, its three upgrades and its removal, WhatsApp's install,
# upgrade and removal, the phones' channel refused, a standard user's command, the core's LAN name, and the service's
# own log read for problems.
#
#     run-windows.ps1 -Bundle <bundle folder> -Results <results folder>
#
# The bundle is fresh.py's (hiroleague\, hello\), copied to C:\hiro-test as a person unzips it. Each step's output
# goes to <results>\logs\NN-<step>.log; the result is <results>\result.md and result.json. The Sandbox's account is an
# administrator, so no prompt is asked (the prompt itself is proven on the PC).
param(
    [Parameter(Mandatory = $true)][string]$Bundle,
    [Parameter(Mandatory = $true)][string]$Results
)
$ErrorActionPreference = 'Continue'
$Name = 'hirofresh'  # the core's own name: hirofresh.local (never hiro: Simone owns it)
$Logs = Join-Path $Results 'logs'
New-Item -ItemType Directory -Force $Logs | Out-Null
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:COLUMNS = '160'
$env:NO_COLOR = '1'
$script:N = 0
$script:Steps = New-Object System.Collections.ArrayList

function Add-Result([string]$StepName, [bool]$Ok, [int]$Seconds, [string]$Detail, [string]$Log) {
    [void]$script:Steps.Add([pscustomobject]@{ step = $StepName; ok = $Ok; seconds = $Seconds; detail = $Detail; log = $Log })
    $mark = if ($Ok) { 'PASS' } else { 'FAIL' }
    Write-Host ('{0} {1,-34} {2}' -f $mark, $StepName, $Detail)
}

function New-LogPath([string]$StepName) {
    $script:N++
    $file = '{0:D2}-{1}.log' -f $script:N, ($StepName -replace '[^A-Za-z0-9.]+', '-')
    return (Join-Path $Logs $file)
}

# A step of the person's: a command line run by cmd, passing when its exit code is as expected ('ok' or 'fails') and
# its output holds the pattern
function Invoke-Step([string]$StepName, [string]$Expect, [string]$Pattern, [string]$Line) {
    $log = New-LogPath $StepName
    [IO.File]::WriteAllText($log, "> $Line`r`n")
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $p = Start-Process -FilePath $env:ComSpec -ArgumentList "/d /s /c `"$Line >> `"$log`" 2>&1`"" -Wait -PassThru -NoNewWindow
    $code = $p.ExitCode
    $ok = if ($Expect -eq 'ok') { $code -eq 0 } else { $code -ne 0 }
    $detail = "exit $code"
    if ($Pattern -and -not (Select-String -Path $log -Pattern $Pattern -Quiet)) {
        $ok = $false
        $detail += ", no `"$Pattern`" in its output"
    }
    Add-Result $StepName $ok ([int]$clock.Elapsed.TotalSeconds) $detail ('logs/' + (Split-Path $log -Leaf))
    return $ok
}

# A check, not a step of the person's: a script block that returns $true, its words to the log
function Test-Check([string]$StepName, [scriptblock]$Check) {
    $log = New-LogPath $StepName
    try {
        $out = & $Check 2>&1
        $ok = [bool]($out | Select-Object -Last 1)
        [IO.File]::WriteAllText($log, (($out | Out-String)))
    } catch {
        $ok = $false
        [IO.File]::WriteAllText($log, ($_ | Out-String))
    }
    $detail = if ($ok) { 'as expected' } else { 'see its log' }
    Add-Result $StepName $ok 0 $detail ('logs/' + (Split-Path $log -Leaf))
}

function Test-Hello([string]$Want) {
    $json = & hiro extension list --json | Out-String
    $json
    $rows = @((ConvertFrom-Json $json).installs | Where-Object { $_.key -eq 'example.hello' })
    if ($Want -eq 'gone') { return ($rows.Count -eq 0) }
    return ($rows.Count -eq 1 -and $rows[0].version -eq $Want -and $rows[0].running -eq $true)
}

# --- the person's path ---------------------------------------------------------------------------------------------
Test-Check 'an administrator (no prompt)' {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole('Administrators')
}
robocopy $Bundle C:\hiro-test /E /NFL /NDL /NJH /NJS /NP | Out-Null
$hello = 'C:\hiro-test\hello'
$core = 'C:\hiro-test\hiroleague\hiroserver\hiroleague'

# The package cache (fresh.py, unless --fresh): uv's machine-wide settings, which every uv here obeys (the person's,
# the service's, the core's own for apps), point at Simone's cache. The only difference from a person's machine.
$cacheFile = Join-Path $Bundle 'CACHE'
if (Test-Path $cacheFile) {
    $index, $pythons = (Get-Content $cacheFile -TotalCount 1).Trim() -split '\s+'
    New-Item -ItemType Directory -Force 'C:\ProgramData\uv' | Out-Null
    $toml = "python-install-mirror = `"$pythons`"`n`n[[index]]`nurl = `"$index`"`ndefault = true`n"
    [IO.File]::WriteAllText('C:\ProgramData\uv\uv.toml', $toml, (New-Object Text.UTF8Encoding($false)))
}
# The pinned downloads (fresh.py, unless --fresh): WinSW, Caddy and Microsoft's C++ runtime installer, in the machine's
# downloads folder, where the core looks first (each still checked there: the hash it pins, Microsoft's signature)
$downloads = Join-Path $Bundle 'downloads'
if (Test-Path $downloads) {
    New-Item -ItemType Directory -Force 'C:\ProgramData\HiroLeague\cache\downloads' | Out-Null
    Copy-Item (Join-Path $downloads '*') 'C:\ProgramData\HiroLeague\cache\downloads'
}
Invoke-Step 'uv' ok '' 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"' | Out-Null
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
Invoke-Step 'core (uv tool install)' ok '' "uv tool install --python 3.12 $core" | Out-Null
Invoke-Step 'service install' ok '' "hiro service install --from $core --name $Name" | Out-Null
Start-Sleep -Seconds 60  # a service that fails at start restarts every few seconds in this time
$serviceLogs = 'C:\ProgramData\HiroLeague\data\service-logs'
Test-Check 'service still runs after 60 s' {
    $state = (Get-Service hiro).Status
    "state: $state"
    Get-ChildItem $serviceLogs | Select-Object Name, Length | Out-String
    $err = Get-Content (Join-Path $serviceLogs 'hiro.err.log') -ErrorAction SilentlyContinue | Out-String
    $err
    ($state -eq 'Running') -and -not ($err -match 'Traceback|DLL load failed')
}

$env:HIRO_DATA_DIR = 'C:\ProgramData\HiroLeague\data'  # as the steps say: the service's data
Invoke-Step 'Hello 0.1.0 install' ok 'it runs and is paired' "hiro extension install $hello\example_hello-0.1.0-py3-none-any.whl --approve" | Out-Null
Test-Check 'Hello runs 0.1.0' { Test-Hello '0.1.0' }
Invoke-Step 'Hello 0.1.3 (goes back)' fails '' "hiro extension upgrade example.hello $hello\example_hello-0.1.3-py3-none-any.whl" | Out-Null
Test-Check 'Hello back on 0.1.0' { Test-Hello '0.1.0' }
Invoke-Step 'Hello 0.1.2 (stays)' fails '' "hiro extension upgrade example.hello $hello\example_hello-0.1.2-py3-none-any.whl" | Out-Null
Test-Check 'Hello still on 0.1.0' { Test-Hello '0.1.0' }
Invoke-Step 'Hello 0.1.1 (upgrades)' ok '' "hiro extension upgrade example.hello $hello\example_hello-0.1.1-py3-none-any.whl" | Out-Null
Test-Check 'Hello runs 0.1.1' { Test-Hello '0.1.1' }
Invoke-Step 'Hello remove --purge' ok 'Removed' 'hiro extension remove example.hello --purge --yes' | Out-Null
Test-Check 'Hello gone' { Test-Hello 'gone' }

Invoke-Step 'WhatsApp install' ok 'Installed' 'hiro extension install whatsapp' | Out-Null
Invoke-Step 'WhatsApp upgrade' ok 'Upgraded' 'hiro extension upgrade whatsapp' | Out-Null
Invoke-Step 'WhatsApp remove' ok 'Removed' 'hiro extension remove whatsapp' | Out-Null
Invoke-Step 'devices refused' fails 'comes with the core' 'hiro extension install devices' | Out-Null

# A standard user's terminal on the service's data: told to run as an administrator (a test account of this
# throwaway Sandbox, its password made here and never kept)
$release = Get-ChildItem 'C:\ProgramData\HiroLeague\releases' | Sort-Object Name | Select-Object -Last 1
$userLog = New-LogPath 'a standard user is told to be an administrator'
$password = ConvertTo-SecureString ([Guid]::NewGuid().ToString('N') + 'Aa1!') -AsPlainText -Force
# New-LocalUser asks nothing: `net user /add` asks yes or no for a password past 14 characters, the answer defaulted to
# no, and the account was never made ("The user name or password is incorrect")
New-LocalUser -Name freshperson -Password $password -AccountNeverExpires | Out-Null
Add-LocalGroupMember -SID 'S-1-5-32-545' -Member freshperson  # Users: a standard person, who may sign in
$credential = New-Object Management.Automation.PSCredential('freshperson', $password)
$userLine = "set HIRO_DATA_DIR=C:\ProgramData\HiroLeague\data&& `"$($release.FullName)\bin\hiro.exe`" extension list"
# Its output goes to a folder the standard user may write (not the mapped results folder), then into the log; the
# start's own failure and the exit code go in the log too: a run that said nothing left an empty log
$userOut = 'C:\Users\Public\fresh-user.out'
$userErr = 'C:\Users\Public\fresh-user.err'
try {
    $p = Start-Process -FilePath $env:ComSpec -ArgumentList "/d /s /c `"$userLine`"" -Credential $credential -LoadUserProfile `
        -Wait -PassThru -WorkingDirectory C:\ -RedirectStandardOutput $userOut -RedirectStandardError $userErr -NoNewWindow `
        -ErrorAction Stop
    $started = "exit $($p.ExitCode)"
} catch {
    $started = "the start failed: $($_.Exception.Message)"
}
[IO.File]::WriteAllText($userLog, "> (as freshperson) $userLine`r`n$started`r`n")
Get-Content $userOut, $userErr -ErrorAction SilentlyContinue | Add-Content $userLog
# Its words wrap at the console's width ("administrator" and "terminal" on two lines): matched with the lines joined
$told = ((Get-Content $userLog -Raw) -replace '\s+', ' ') -match 'administrator terminal'
Add-Result 'a standard user is told to be an administrator' $told 0 $(if ($told) { 'as expected' } else { 'see its log' }) ('logs/' + (Split-Path $userLog -Leaf))

Test-Check 'core announces its address' { $out = & hiro logs search 'announcing on' --json | Out-String; $out; $out -match 'announcing on' }
Test-Check "$Name.local resolves" { $a = Resolve-DnsName "$Name.local" -Type A -ErrorAction Stop; $a | Out-String; [bool]$a }
Test-Check "front door answers $Name.local" {
    try {
        $r = Invoke-WebRequest "http://127.0.0.1/" -Headers @{ Host = "$Name.local" } -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 20
        $code = [int]$r.StatusCode
    } catch [System.Net.WebException] {
        $code = [int]$_.Exception.Response.StatusCode
    }
    "HTTP $code"
    ($code -ge 200 -and $code -lt 400)
}
# read_logs.py judges both: anything the run didn't cause on purpose fails (uv's Python, the one the core runs on)
$readLogs = 'uv run --no-project --python 3.12 python C:\hiro-test\read_logs.py'
Invoke-Step 'problems in the logs' ok '' "hiro logs problems --since 2h --json | $readLogs problems" | Out-Null
Invoke-Step 'service log has no error' ok '' "type `"$serviceLogs\hiro.err.log`" | $readLogs service" | Out-Null

# --- the result ----------------------------------------------------------------------------------------------------
$commit = Get-Content (Join-Path $Bundle 'COMMIT') -ErrorAction SilentlyContinue
$os = (Get-CimInstance Win32_OperatingSystem).Caption
$lines = @("# Fresh install: Windows ($os, Windows Sandbox)", '', ((Get-Date -Format 'ddd, MMM d, h:mm tt') + " - core $commit"), '',
    '| | Step | Took | Detail | Log |', '|---|---|---|---|---|')
foreach ($s in $script:Steps) {
    $mark = if ($s.ok) { 'PASS' } else { '**FAIL**' }
    $lines += "| $mark | $($s.step) | $($s.seconds) s | $($s.detail -replace '\|', '/') | [log]($($s.log)) |"
}
$utf8 = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $Results 'result.md'), ($lines -join "`r`n") + "`r`n", $utf8)
$passed = -not ($script:Steps | Where-Object { -not $_.ok })
$json = [pscustomobject]@{ system = 'windows'; passed = $passed; steps = $script:Steps } | ConvertTo-Json -Depth 4
[IO.File]::WriteAllText((Join-Path $Results 'result.json'), $json, $utf8)
[IO.File]::WriteAllText((Join-Path $Results 'finished'), 'done', $utf8)
if (Test-Path (Join-Path $Bundle 'CLOSE')) { shutdown /s /t 5 }
