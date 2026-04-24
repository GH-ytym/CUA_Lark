$ErrorActionPreference = "Stop"

Write-Host "Backend command: .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --app-dir .\backend"
Write-Host "Frontend command: npm run dev --prefix .\frontend"
Write-Host "Optional checks:"
Write-Host "- Backend tests: .\.venv\Scripts\python.exe -m pytest .\backend\tests"
Write-Host "- Frontend typecheck: npm run typecheck --prefix .\frontend"
