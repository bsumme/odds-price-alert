# PowerShell script to pull latest changes and restart the FastAPI server
# This script will:
# 1. Run `git pull` to fetch the latest changes
# 2. Ensure the Python virtual environment exists
# 3. Install/update Python dependencies if requirements changed
# 4. Delegate to restart_server.ps1 for a clean restart

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Updating and Restarting Bet Watcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Get the script directory and move there so git and paths work as expected
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Step 1: Pull latest changes
Write-Host "[1/4] Pulling latest changes from git..." -ForegroundColor Yellow
git pull
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERROR] git pull failed. Please resolve git issues and try again." -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] Repository is up to date" -ForegroundColor Green

# Step 2: Ensure virtual environment exists
Write-Host ""
Write-Host "[2/4] Ensuring virtual environment exists..." -ForegroundColor Yellow
if (-not (Test-Path ".venv")) {
    Write-Host "  No virtual environment found. Creating one..." -ForegroundColor Yellow
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERROR] Failed to create virtual environment. Make sure Python is installed." -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] Virtual environment created" -ForegroundColor Green
} else {
    Write-Host "  [OK] Virtual environment already exists" -ForegroundColor Green
}

# Step 3: Activate venv and install dependencies
Write-Host ""
Write-Host "[3/4] Activating environment and installing dependencies..." -ForegroundColor Yellow
$activateScript = Join-Path $scriptDir ".venv/Scripts/Activate.ps1"
if (-not (Test-Path $activateScript)) {
    Write-Host "  [ERROR] Activation script not found. Try rerunning rebuild_and_run.ps1." -ForegroundColor Red
    exit 1
}

& $activateScript
if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) {
    Write-Host "  [ERROR] Failed to activate virtual environment." -ForegroundColor Red
    exit 1
}

if (Test-Path "requirements.txt") {
    Write-Host "  Installing/updating dependencies from requirements.txt..." -ForegroundColor Yellow
    pip install --upgrade -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERROR] Dependency installation failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] Dependencies are up to date" -ForegroundColor Green
} else {
    Write-Host "  [WARNING] requirements.txt not found; skipping dependency installation." -ForegroundColor Yellow
}

# Step 4: Restart the server using existing script for consistency
Write-Host ""
Write-Host "[4/4] Restarting server using restart_server.ps1..." -ForegroundColor Yellow
$restartScript = Join-Path $scriptDir "restart_server.ps1"
if (Test-Path $restartScript) {
    & $restartScript
} else {
    Write-Host "  [ERROR] restart_server.ps1 not found in repository root." -ForegroundColor Red
    exit 1
}
