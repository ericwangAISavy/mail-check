[CmdletBinding()]
param(
    [ValidateSet('Init','Up','Down','Status','Doctor','Verify')]
    [string]$Action = 'Status',
    [string]$ModelUrl = 'http://127.0.0.1:11434'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot 'deployment\microservices\compose.yaml'
$stateDir = Join-Path $repoRoot 'deployment\microservices\.local'
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) { $pythonExe = (Get-Command python -ErrorAction Stop).Source }
# Repair owner access before Python validates existing state. An empty file DACL
# permits its owner to fix the ACL but prevents reading the manifest itself.
function Protect-ServicePath([System.IO.FileSystemInfo]$Item) {
    if ($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw 'Service state cannot contain symbolic links or junctions.'
    }
    $rights = if ($Item -is [System.IO.DirectoryInfo]) { '(OI)(CI)F' } else { 'F' }
    $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $aclTool = Join-Path $env:SystemRoot 'System32\icacls.exe'
    & $aclTool $Item.FullName /L /inheritance:r /grant:r "*${sid}:$rights" "*S-1-5-18:$rights" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not configure service-state access. Run Init using the account that owns these files.'
    }
}

function Protect-ServiceState {
    if (-not (Test-Path -LiteralPath $stateDir)) { return }
    Protect-ServicePath (Get-Item -Force -LiteralPath $stateDir)
    $entries = @(Get-ChildItem -Force -LiteralPath $stateDir)
    foreach ($entry in $entries) {
        if ($entry.Name -in @('manifest.json','secrets')) { Protect-ServicePath $entry }
    }
    $secretDir = Join-Path $stateDir 'secrets'
    if (Test-Path -LiteralPath $secretDir -PathType Container) {
        Get-ChildItem -Force -File -LiteralPath $secretDir | ForEach-Object { Protect-ServicePath $_ }
    }
}

$previousState = $env:OFFERPATH_SERVICE_STATE_DIR
Push-Location $repoRoot
try {
    Write-Host 'OfferPath microservice foundation. Existing start.bat deployment is unchanged.'
    $env:OFFERPATH_SERVICE_STATE_DIR = $stateDir
    $composeArgs = @('compose', '-f', $composeFile)
    if ($Action -in @('Init','Up')) {
        Protect-ServiceState
        $initOutput = & $pythonExe -m mailcheck.services.manage init --state-dir $stateDir
        $initExitCode = $LASTEXITCODE
        $initOutput | ForEach-Object { Write-Host $_ }
        if ($initExitCode -ne 0) {
            try { $initReport = ($initOutput -join "`n") | ConvertFrom-Json -ErrorAction Stop }
            catch { $initReport = $null }
            if ($initReport.code) {
                throw "Initialization failed [$($initReport.code)]. $($initReport.error) $($initReport.hint)"
            }
            throw 'Initialization failed; existing credentials were not overwritten.'
        }
        # Apply the same policy to any files created by initialization.
        Protect-ServiceState
    }
    switch ($Action) {
        'Up' { & docker @composeArgs up --build --detach --wait --wait-timeout 180; if ($LASTEXITCODE -ne 0) { throw 'Foundation startup failed.' } }
        'Down' { & docker @composeArgs down; if ($LASTEXITCODE -ne 0) { throw 'Foundation shutdown failed.' } }
        'Status' { & docker @composeArgs ps; if ($LASTEXITCODE -ne 0) { throw 'Could not read foundation status.' } }
        'Verify' { & docker @composeArgs --profile tools run --rm verify; if ($LASTEXITCODE -ne 0) { throw 'Foundation dependency verification failed.' }; & $pythonExe -m mailcheck.services.verify_stack; if ($LASTEXITCODE -ne 0) { throw 'Foundation edge verification failed.' } }
        'Doctor' { & $pythonExe -m mailcheck.services.manage doctor --model-url $ModelUrl; if ($LASTEXITCODE -ne 0) { throw 'Host diagnostic failed.' } }
    }
    if ($Action -eq 'Up') {
        Write-Host 'Health: http://127.0.0.1:52500/platform/core/dependencies'
        Write-Host 'This is NOT a production cutover. Business APIs intentionally return migration_not_ready.'
    }
} finally {
    if ($null -eq $previousState) { Remove-Item Env:OFFERPATH_SERVICE_STATE_DIR -ErrorAction SilentlyContinue }
    else { $env:OFFERPATH_SERVICE_STATE_DIR = $previousState }
    Pop-Location
}
