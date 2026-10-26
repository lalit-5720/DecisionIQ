<#
  One-command local demo (Windows PowerShell):   .\scripts\demo.ps1
  Creates the Python environment, installs dependencies, builds everything from data\raw\train.csv
  (skipping finished steps), starts the API on :8000 and the frontend on :5173.
  Use -SkipInstall to skip pip/npm installs on later runs.
#>
param([switch]$SkipInstall)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

Set-Location "$root\backend"
if (-not (Test-Path ".venv")) { python -m venv .venv }
if (-not $SkipInstall) { & .\.venv\Scripts\python.exe -m pip install -r requirements.txt }
& .\.venv\Scripts\python.exe -m app.bootstrap
if ($LASTEXITCODE -ne 0) { throw "Bootstrap failed - see the message above." }

Write-Host "Starting the API on http://localhost:8000 ..."
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m", "uvicorn", "app.main:app", "--port", "8000" -WindowStyle Minimized

Set-Location "$root\frontend"
if ((-not $SkipInstall) -or (-not (Test-Path "node_modules"))) { npm install }
Write-Host "Starting the frontend on http://localhost:5173 (demo accounts: see README)"
npm run dev
