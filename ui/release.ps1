# =============================================================================
# release.ps1 — Build completo dos instaladores Windows (.msi e .exe)
# =============================================================================

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "NFSe Manager — Release Build (Windows)" -ForegroundColor Cyan

& (Join-Path $ScriptDir "build_sidecar.ps1")

Set-Location $ScriptDir
if (-not (Test-Path (Join-Path $ScriptDir "node_modules"))) {
    Write-Host "Instalando dependencias npm..." -ForegroundColor Yellow
    npm install
}

npm run tauri build
if ($LASTEXITCODE -ne 0) {
    throw "Falha no 'npm run tauri build'."
}

$BundleDir = Join-Path $ScriptDir "src-tauri\target\release\bundle"
Write-Host "Instaladores gerados em: $BundleDir" -ForegroundColor Green
Get-ChildItem -Path $BundleDir -Recurse -Include *.msi,*.exe | ForEach-Object {
    Write-Host " - $($_.FullName)"
}
