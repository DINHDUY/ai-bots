#Requires -Version 5
<#
.SYNOPSIS
    Install Podman on Windows using winget (default) or Chocolatey.

.DESCRIPTION
    Installs the Podman CLI and initialises a WSL2-backed Podman Machine.
    Run this script once from an elevated PowerShell prompt.

.PARAMETER UseChoco
    Use Chocolatey instead of winget.

.EXAMPLE
    .\scripts\install-podman-windows.ps1
    .\scripts\install-podman-windows.ps1 -UseChoco
#>

param(
    [switch]$UseChoco
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── 1. Verify WSL2 ──────────────────────────────────────────────────────────
Write-Host "==> Checking WSL2..." -ForegroundColor Cyan
try {
    $wslStatus = wsl --status 2>&1
    if ($wslStatus -notmatch 'Default Version: 2') {
        Write-Warning "WSL2 default version not set. Run:  wsl --set-default-version 2"
    }
} catch {
    Write-Host "WSL2 not found. Install with:  wsl --install  then reboot." -ForegroundColor Red
    exit 1
}

# ── 2. Install Podman CLI ────────────────────────────────────────────────────
if ($UseChoco) {
    Write-Host "==> Installing Podman via Chocolatey..." -ForegroundColor Cyan
    choco install podman -y
} else {
    Write-Host "==> Installing Podman via winget..." -ForegroundColor Cyan
    winget install --id RedHat.Podman --accept-package-agreements --accept-source-agreements
}

# Refresh PATH
$env:PATH = [System.Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' +
            [System.Environment]::GetEnvironmentVariable('PATH', 'User')

# ── 3. Install podman-compose ────────────────────────────────────────────────
Write-Host "==> Installing podman-compose via pip..." -ForegroundColor Cyan
python -m pip install --user podman-compose

# ── 4. Initialise Podman Machine ─────────────────────────────────────────────
Write-Host "==> Initialising Podman Machine (WSL2-backed)..." -ForegroundColor Cyan
$machines = podman machine list --format json 2>$null | ConvertFrom-Json
if ($machines | Where-Object { $_.Name -eq 'podman-machine-default' }) {
    Write-Host "    Machine already exists, skipping init."
} else {
    podman machine init
}

Write-Host "==> Starting Podman Machine..." -ForegroundColor Cyan
podman machine start

# ── 5. Print socket info ─────────────────────────────────────────────────────
$socketPath = podman machine inspect --format '{{.ConnectionInfo.PodmanSocket.Path}}' 2>$null
Write-Host ""
Write-Host "Podman installed and machine is running." -ForegroundColor Green
Write-Host "Socket (for .env.compose):  $socketPath" -ForegroundColor Yellow
Write-Host ""
Write-Host "Add to .env.compose:" -ForegroundColor Cyan
Write-Host "  PODMAN_SOCK=$socketPath"
Write-Host "  DOCKER_HOST=npipe:////./pipe/podman-machine-default"
Write-Host ""
Write-Host "Then run:  podman compose -f compose.dev.yml up --build"
