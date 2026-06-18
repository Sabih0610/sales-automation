$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$EntryPoint = Join-Path $Root "scripts\backend_exe_entry.py"
$DistPath = Join-Path $Root "dist"
$WorkPath = Join-Path $Root "build\pyinstaller"
$SpecPath = Join-Path $Root "build\pyinstaller-spec"
$ExePath = Join-Path $DistPath "royal-cyber-backend\royal-cyber-backend.exe"

function Add-DataArg {
    param(
        [string]$Source,
        [string]$Dest
    )

    if (Test-Path $Source) {
        $script:PyInstallerArgs += @("--add-data", "$Source;$Dest")
    }
}

try {
    python -m PyInstaller --version | Out-Null
} catch {
    Write-Host "PyInstaller is not installed. Run this first:"
    Write-Host "  python -m pip install -r requirements-build.txt"
    throw
}

$PyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--name", "royal-cyber-backend",
    "--paths", $Root,
    "--distpath", $DistPath,
    "--workpath", $WorkPath,
    "--specpath", $SpecPath,
    "--collect-submodules", "src",
    "--collect-submodules", "uvicorn",
    "--collect-submodules", "playwright",
    "--hidden-import", "main",
    "--hidden-import", "src.api",
    "--hidden-import", "uvicorn.logging",
    "--hidden-import", "uvicorn.loops.auto",
    "--hidden-import", "uvicorn.protocols.http.auto",
    "--hidden-import", "uvicorn.protocols.websockets.auto",
    "--hidden-import", "uvicorn.lifespan.on"
)

Add-DataArg (Join-Path $Root "migrations") "migrations"
Add-DataArg (Join-Path $Root "knowledge_base") "knowledge_base"
Add-DataArg (Join-Path $Root "campaigns") "campaigns"
Add-DataArg (Join-Path $Root ".env.example") ".env.example"

Push-Location $Root
try {
    python -m PyInstaller @PyInstallerArgs $EntryPoint
} finally {
    Pop-Location
}

if (!(Test-Path $ExePath)) {
    throw "Expected backend executable was not created: $ExePath"
}

$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$BundlePath = Join-Path $DistPath "royal-cyber-backend"
icacls $BundlePath /grant "${CurrentUser}:(OI)(CI)F" /T | Out-Null

Write-Host "Backend executable created:"
Write-Host "  $ExePath"
Write-Host ""
Write-Host "Real .env files are not bundled. Production desktop config is read from app-data .env; development can still use the project .env."
