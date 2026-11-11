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
$previousState = $env:OFFERPATH_SERVICE_STATE_DIR
Push-Location $repoRoot
try {
    Write-Host 'OfferPath microservice foundation. Existing start.bat deployment is unchanged.'
    $env:OFFERPATH_SERVICE_STATE_DIR = $stateDir
    $composeArgs = @('compose', '-f', $composeFile)
    if ($Action -in @('Init','Up')) {
        & $pythonExe -m mailcheck.services.manage init --state-dir $stateDir
        if ($LASTEXITCODE -ne 0) { throw 'Initialization failed; existing credentials were not overwritten.' }
        # Restrict local files before Docker reads them. No credentials in arguments.
        $principal = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $protectedPaths = @($stateDir, (Join-Path $stateDir 'secrets'), (Join-Path $stateDir 'manifest.json'))
        $protectedPaths += @(Get-ChildItem (Join-Path $stateDir 'secrets') -File | ForEach-Object FullName)
        foreach ($protectedPath in $protectedPaths) {
            & icacls.exe $protectedPath /inheritance:r /grant:r "${principal}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Could not restrict the local service state ACL.' }
        }
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
