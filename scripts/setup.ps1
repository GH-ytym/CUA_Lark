$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$venvPython = Join-Path $root ".venv\\Scripts\\python.exe"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "Python is required. Install Python 3.12+ and ensure it is on PATH."
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  throw "Node.js and npm are required. Install Node.js 20+ and ensure npm is on PATH."
}

if (-not (Test-Path ".venv") -or -not (Test-Path $venvPython)) {
  python -m venv .venv
}

& $venvPython -m pip install -e ".\backend[dev]"
if ($LASTEXITCODE -ne 0) {
  throw "Backend dependency installation failed."
}

Push-Location ".\frontend"
npm install
Pop-Location
if ($LASTEXITCODE -ne 0) {
  throw "Frontend dependency installation failed."
}

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
}

Write-Host "Environment setup completed."
Write-Host "Next steps:"
Write-Host "1. Edit .env with your Feishu, Lark-CLI, Redis, and CUA provider settings."
Write-Host "2. Start backend: .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --app-dir .\backend"
Write-Host "3. Start frontend: npm run dev --prefix .\frontend"
