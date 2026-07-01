# run-local.ps1
# Local development orchestrator script for Windows (PowerShell)
# Usage: 
#   .\run-local.ps1 start
#   .\run-local.ps1 stop

param (
    [Parameter(Mandatory=$true)]
    [ValidateSet("start", "stop")]
    [string]$Action
)

function Start-Services {
    Write-Host "1. Starting Docker containers (Postgres, ChromaDB, Redis)..." -ForegroundColor Cyan
    docker compose up -d
    
    Write-Host "Waiting for database services to become healthy..." -ForegroundColor Yellow
    Start-Sleep -Seconds 5

    Write-Host "2. Starting FastAPI Backend Server on port 8000..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd apps/invoice-be; .venv\Scripts\uvicorn main:app --port 8000"

    Write-Host "3. Starting Celery Worker..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd apps/invoice-be; .venv\Scripts\python -u -m celery -A workers.celery_app worker --loglevel=info -P solo"

    Write-Host "4. Starting Next.js Frontend Server on port 3000..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd apps/invoice-fe; npm run dev"

    Write-Host "`nAll components started! You can access the UI at http://localhost:3000" -ForegroundColor Green
}

function Stop-Services {
    Write-Host "1. Shutting down running dev processes (Uvicorn, Celery, Next.js)..." -ForegroundColor Cyan
    
    # Gracefully terminate python (uvicorn/celery) and node (next.js)
    Stop-Process -Name "python" -Force -ErrorAction SilentlyContinue
    Stop-Process -Name "node" -Force -ErrorAction SilentlyContinue
    
    Write-Host "2. Stopping Docker containers..." -ForegroundColor Cyan
    docker compose down

    Write-Host "`nAll services stopped successfully." -ForegroundColor Green
}

if ($Action -eq "start") {
    Start-Services
} elseif ($Action -eq "stop") {
    Stop-Services
}
