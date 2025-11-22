# PowerShell script to quickly restart the FastAPI server
# This script will:
# 1. Stop any running uvicorn/python processes for this app
# 2. Clear Python cache files
# 3. Start the FastAPI server

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Restarting Bet Watcher Server" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Get the script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Step 1: Stop any running processes on port 8000
Write-Host "[1/3] Stopping existing server processes..." -ForegroundColor Yellow

# Kill processes by port 8000 (most reliable method)
$portProcess = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
if ($portProcess) {
    foreach ($pid in $portProcess) {
        try {
            $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
            if ($proc) {
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                Write-Host "  Stopped process using port 8000 (PID: $pid - $($proc.ProcessName))" -ForegroundColor Green
            }
        } catch {
            Write-Host "  Could not stop process on port 8000 (PID: $pid)" -ForegroundColor Yellow
        }
    }
    Start-Sleep -Seconds 2
    Write-Host "  [OK] Port 8000 cleared" -ForegroundColor Green
} else {
    Write-Host "  [OK] Port 8000 is free" -ForegroundColor Green
}

# Step 2: Clear Python cache (quick cleanup)
Write-Host ""
Write-Host "[2/3] Clearing Python cache..." -ForegroundColor Yellow
$cacheDirs = Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue
if ($cacheDirs) {
    $cacheDirs | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  [OK] Cleared $($cacheDirs.Count) cache directory(ies)" -ForegroundColor Green
} else {
    Write-Host "  [OK] No cache directories found" -ForegroundColor Green
}

# Step 3: Activate virtual environment and start server
Write-Host ""
Write-Host "[3/3] Starting server..." -ForegroundColor Yellow

# Check if virtual environment exists
if (-not (Test-Path ".venv")) {
    Write-Host "  [ERROR] Virtual environment not found!" -ForegroundColor Red
    Write-Host "  Run rebuild_and_run.ps1 first to create the virtual environment." -ForegroundColor Yellow
    exit 1
}

# Activate virtual environment
& .\.venv\Scripts\Activate.ps1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERROR] Failed to activate virtual environment!" -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] Virtual environment activated" -ForegroundColor Green

# Check for API key
$apiKey = [Environment]::GetEnvironmentVariable("THE_ODDS_API_KEY", "User")
if (-not $apiKey) {
    $apiKey = [Environment]::GetEnvironmentVariable("THE_ODDS_API_KEY", "Machine")
}
if (-not $apiKey) {
    Write-Host "  [WARNING] THE_ODDS_API_KEY not found!" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Server Starting..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Server will be available at: http://127.0.0.1:8000/" -ForegroundColor Green
Write-Host "Press CTRL+C to stop the server" -ForegroundColor Yellow
Write-Host ""

# Open browser after a short delay
Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:8000/"

# Start uvicorn server
uvicorn main:app --reload --host 127.0.0.1 --port 8000

