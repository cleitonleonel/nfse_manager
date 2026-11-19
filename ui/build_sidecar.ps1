# =============================================================================
# build_sidecar.ps1 — Empacota o servidor Python (.exe) para o Tauri no Windows
# =============================================================================
# Uso (PowerShell na raiz ou dentro de ui/):
#   .\ui\build_sidecar.ps1
# =============================================================================

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$BinariesDir = Join-Path $ScriptDir "src-tauri\binaries"

Write-Host "NFSe Manager — Build Sidecar (Windows)" -ForegroundColor Cyan
Write-Host "Projeto: $ProjectRoot"

$RustHostLine = (& rustc -Vv | Select-String "^host:\s*(.+)$")
if (-not $RustHostLine) {
    throw "Nao foi possivel detectar o target triple via 'rustc -Vv'."
}
$TargetTriple = $RustHostLine.Matches[0].Groups[1].Value.Trim()
Write-Host "Target: $TargetTriple"

Set-Location $ProjectRoot

$PythonCmd = "python"
if ($env:PYTHON_BIN) {
    $PythonCmd = $env:PYTHON_BIN
} elseif (Get-Command poetry -ErrorAction SilentlyContinue) {
    $PoetryPy = (& poetry run python -c "import sys; print(sys.executable)" 2>$null)
    if ($LASTEXITCODE -eq 0 -and $PoetryPy) {
        $PythonCmd = $PoetryPy.Trim()
    }
}

Write-Host "Python: $PythonCmd"

& $PythonCmd -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Instalando PyInstaller..." -ForegroundColor Yellow
    & $PythonCmd -m pip install pyinstaller
}

foreach ($DirName in @("dist", "build")) {
    $Target = Join-Path $ProjectRoot $DirName
    if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
}

$ExtraDataArgs = @()
if (Test-Path (Join-Path $ProjectRoot "backend\migrations")) {
    $ExtraDataArgs += @("--add-data", "backend\migrations;backend\migrations")
}
foreach ($ChangelogFile in @("CHANGELOG.md", "changelog.txt")) {
    if (Test-Path (Join-Path $ProjectRoot $ChangelogFile)) {
        $ExtraDataArgs += @("--add-data", "$ChangelogFile;.")
    }
}

Write-Host "Empacotando servidor Python (PyInstaller)..." -ForegroundColor Cyan
& $PythonCmd -m PyInstaller `
    --noconfirm `
    --onefile `
    --noconsole `
    --name server `
    --paths backend `
    --collect-submodules app `
    --collect-all pynfse `
    --collect-all signxml `
    --collect-all cryptography `
    --hidden-import uvicorn.logging `
    --hidden-import uvicorn.loops `
    --hidden-import uvicorn.loops.auto `
    --hidden-import uvicorn.protocols `
    --hidden-import uvicorn.protocols.http `
    --hidden-import uvicorn.protocols.http.auto `
    --hidden-import uvicorn.protocols.websockets `
    --hidden-import uvicorn.protocols.websockets.auto `
    --hidden-import uvicorn.lifespan `
    --hidden-import uvicorn.lifespan.on `
    --hidden-import fastapi `
    --hidden-import sqlalchemy `
    --hidden-import sqlalchemy.dialects.postgresql `
    --hidden-import sqlalchemy.dialects.sqlite `
    --hidden-import psycopg2 `
    --hidden-import httpx2 `
    --hidden-import openpyxl `
    --hidden-import reportlab `
    --hidden-import lxml `
    --hidden-import bs4 `
    --hidden-import multipart `
    --hidden-import requests `
    --hidden-import requests_pkcs12 `
    --add-data "frontend;frontend" `
    --add-data "pyproject.toml;." `
    @ExtraDataArgs `
    server.py

if ($LASTEXITCODE -ne 0) {
    throw "Falha ao empacotar server.py com PyInstaller."
}

New-Item -ItemType Directory -Force -Path $BinariesDir | Out-Null
$DestBin = Join-Path $BinariesDir "server-$TargetTriple.exe"
Copy-Item -Force (Join-Path $ProjectRoot "dist\server.exe") $DestBin

Write-Host "Sidecar criado em: $DestBin" -ForegroundColor Green
