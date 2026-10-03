$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Here ".venv"
$DriveConfigDir = "G:\Meine Ablage\Antigravity\AI_Intel\CONFIG"
$DriveConfig = Join-Path $DriveConfigDir "config.yaml"

if (-not (Test-Path "G:\Meine Ablage\Antigravity\AI_Intel")) {
  throw "Canonical Drive path not found: G:\Meine Ablage\Antigravity\AI_Intel"
}

if (-not (Test-Path $Venv)) {
  py -3 -m venv $Venv
}

& (Join-Path $Venv "Scripts\python.exe") -m pip install --upgrade pip
& (Join-Path $Venv "Scripts\pip.exe") install -r (Join-Path $Here "requirements.txt")

New-Item -ItemType Directory -Force -Path $DriveConfigDir | Out-Null
if (-not (Test-Path $DriveConfig)) {
  Copy-Item (Join-Path $Here "config.example.yaml") $DriveConfig
}

Write-Host "AI Radar installed. Config: $DriveConfig"
Write-Host "Scheduler intentionally not changed. Register the nightly command in the existing Hermes scheduler."
