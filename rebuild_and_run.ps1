# PowerShell script to rebuild virtual environment and run the FastAPI app
# This script will:
# 1. Remove existing virtual environment
# 2. Clear Python cache files
# 3. Create fresh virtual environment
# 4. Install all required dependencies
# 5. Start the FastAPI server
#
# Usage: .\rebuild_and_run.ps1 [-d|-t]
#   -d : Run the app in debug trace level
#   -t : Run the app in trace level
#   default (no flag): Run in regular mode

param(
    [switch]$d,
    [switch]$t
)

if ($d -and $t) {
    Write-Host "[ERROR] Specify only one trace flag: -d for debug or -t for trace" -ForegroundColor Red
    exit 1
}

$traceLevel = "regular"
if ($d) {
    $traceLevel = "debug"
} elseif ($t) {
    $traceLevel = "trace"
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Rebuilding and Starting Bet Watcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Get the script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Step 1: Deactivate and remove existing virtual environment
Write-Host "[1/6] Checking for existing virtual environment..." -ForegroundColor Yellow
if (Test-Path ".venv") {
    Write-Host "  Stopping any Python processes that might be using the venv..." -ForegroundColor Yellow
    # Try to stop any Python processes that might be locking files
    Get-Process python* -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*$scriptDir\.venv*" } | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    
    Write-Host "  Removing existing .venv directory..." -ForegroundColor Yellow
    # Try to remove with retry logic
    $maxRetries = 3
    $retryCount = 0
    $removed = $false
    
    while ($retryCount -lt $maxRetries -and -not $removed) {
        try {
            Remove-Item -Recurse -Force .venv -ErrorAction Stop
            $removed = $true
            Write-Host "  [OK] Virtual environment removed" -ForegroundColor Green
        } catch {
            $retryCount++
            if ($retryCount -lt $maxRetries) {
                Write-Host "  [WARNING] Failed to remove .venv (attempt $retryCount/$maxRetries). Retrying..." -ForegroundColor Yellow
                # Try to kill any processes that might be locking files
                Get-Process python* -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 2
            } else {
                Write-Host "  [ERROR] Could not remove .venv directory after $maxRetries attempts!" -ForegroundColor Red
                Write-Host "  Please manually close any programs using the .venv folder and try again." -ForegroundColor Red
                Write-Host "  Or manually delete the .venv folder and run this script again." -ForegroundColor Red
                exit 1
            }
        }
    }
} else {
    Write-Host "  [OK] No existing virtual environment found" -ForegroundColor Green
}

# Step 2: Clear Python cache files
Write-Host ""
Write-Host "[2/6] Clearing Python cache files..." -ForegroundColor Yellow
$cacheDirs = Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue
if ($cacheDirs) {
    $cacheDirs | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  [OK] Cleared $($cacheDirs.Count) cache directory(ies)" -ForegroundColor Green
} else {
    Write-Host "  [OK] No cache directories found" -ForegroundColor Green
}

# Clear .pyc files
$pycFiles = Get-ChildItem -Path . -Recurse -Filter "*.pyc" -ErrorAction SilentlyContinue
if ($pycFiles) {
    $pycFiles | Remove-Item -Force -ErrorAction SilentlyContinue
    Write-Host "  [OK] Cleared $($pycFiles.Count) .pyc file(s)" -ForegroundColor Green
}

# Step 3: Create new virtual environment
Write-Host ""
Write-Host "[3/6] Creating new virtual environment..." -ForegroundColor Yellow
# Small delay to ensure Windows has released all file handles
Start-Sleep -Seconds 1

# Try to create venv with retry logic
$maxRetries = 3
$retryCount = 0
$created = $false

while ($retryCount -lt $maxRetries -and -not $created) {
    try {
        python -m venv .venv 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $created = $true
            Write-Host "  [OK] Virtual environment created" -ForegroundColor Green
        } else {
            throw "venv creation failed with exit code $LASTEXITCODE"
        }
    } catch {
        $retryCount++
        if ($retryCount -lt $maxRetries) {
            Write-Host "  [WARNING] Failed to create venv (attempt $retryCount/$maxRetries). Retrying..." -ForegroundColor Yellow
            Start-Sleep -Seconds 2
        } else {
            Write-Host "  [ERROR] Failed to create virtual environment after $maxRetries attempts!" -ForegroundColor Red
            Write-Host "  Make sure Python is installed and in your PATH" -ForegroundColor Red
            Write-Host "  Also ensure no other processes are using the .venv directory" -ForegroundColor Red
            exit 1
        }
    }
}

# Step 4: Activate virtual environment
Write-Host ""
Write-Host "[4/6] Activating virtual environment..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERROR] Failed to activate virtual environment!" -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] Virtual environment activated" -ForegroundColor Green

# Step 5: Upgrade pip and install dependencies
Write-Host ""
Write-Host "[5/6] Installing dependencies..." -ForegroundColor Yellow
python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERROR] Failed to upgrade pip!" -ForegroundColor Red
    exit 1
}

Write-Host "  Installing packages: fastapi, uvicorn, requests, pydantic..." -ForegroundColor Yellow
pip install fastapi uvicorn[standard] requests pydantic
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERROR] Failed to install dependencies!" -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] All dependencies installed" -ForegroundColor Green

# Step 6: Check for API key
Write-Host ""
Write-Host "[6/6] Checking environment setup..." -ForegroundColor Yellow
$apiKey = [Environment]::GetEnvironmentVariable("THE_ODDS_API_KEY", "User")
if (-not $apiKey) {
    $apiKey = [Environment]::GetEnvironmentVariable("THE_ODDS_API_KEY", "Machine")
}
if (-not $apiKey) {
    Write-Host "  [WARNING] THE_ODDS_API_KEY not found in environment variables!" -ForegroundColor Yellow
    Write-Host "  The app will fail when making API calls." -ForegroundColor Yellow
    Write-Host "  Set it in System Properties -> Environment Variables" -ForegroundColor Yellow
} else {
    Write-Host "  [OK] THE_ODDS_API_KEY found" -ForegroundColor Green
}

# Step 7: Start the server
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Starting FastAPI server..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "TRACE_LEVEL set to $traceLevel" -ForegroundColor Cyan
Write-Host "Server will be available at: http://127.0.0.1:8000/BensSportsBookApp.html" -ForegroundColor Green
Write-Host "Press CTRL+C to stop the server" -ForegroundColor Yellow
Write-Host ""

# Apply trace level for the running process
$env:TRACE_LEVEL = $traceLevel

# Open browser after a short delay
Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:8000/BensSportsBookApp.html"

# Start uvicorn server
uvicorn main:app --reload --host 127.0.0.1 --port 8000

