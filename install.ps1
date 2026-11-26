# rmdash installer for Windows. Run from the rmdash folder in PowerShell:
#   powershell -ExecutionPolicy Bypass -File install.ps1
# (or double-click install.bat). Installs uv (which brings its own Python) if
# needed, installs rmdash's dependencies, then starts the setup wizard.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv, a small tool that installs Python and rmdash's dependencies..."
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Write-Host "Installing rmdash's dependencies..."
uv sync --quiet
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Downloading the headless browser used to draw the dashboard (once, about 150 MB)..."
uv run --quiet playwright install chromium
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

uv run rmdash setup @args
Write-Host ""
Write-Host "Next time, run commands from this folder like:  uv run rmdash setup"
