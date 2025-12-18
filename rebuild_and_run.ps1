# PowerShell script to rebuild virtual environment and run the FastAPI app
# This script will:
# 1. Ensure a virtual environment exists
# 2. Clear Python cache files
# 3. Activate virtual environment
# 4. Check environment setup
# 5. Start the FastAPI server
#
# Usage: .\rebuild_and_run.ps1 [-d|-t] [-f "<file_path>"] [-Mobile] [-DummyData]
#   -d           : Run the app in debug trace level
#   -t           : Run the app in trace level
#   -f           : Log script output to the specified file path
#   -Mobile      : Bind the server to 0.0.0.0 and print the LAN URL for mobile
#                  testing (replaces start_server_for_mobile_test.ps1)
#   -DummyData   : Serve mock odds instead of live API responses (startup only)
#   default (no flag): Run in regular mode
# Example with logging to a full path:
#   .\rebuild_and_run.ps1 -d -f "C:\logs\rebuild_and_run.log"

param(
    [switch]$d,
    [switch]$t,
    [string]$f,
    [switch]$Mobile,
    [switch]$DummyData
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

$hostAddress = if ($Mobile) { "0.0.0.0" } else { "127.0.0.1" }
$port = 8000
$dummyDataEnabled = $DummyData -or ($env:DUMMY_DATA -and $env:DUMMY_DATA.ToLower() -in @("1", "true", "yes"))

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Rebuilding and Starting Bet Watcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if ($DummyData) {
    $env:DUMMY_DATA = "true"
    $dummyDataEnabled = $true
    Write-Host "[INFO] Dummy data ENABLED for this session (startup flag)" -ForegroundColor Yellow
} elseif ($dummyDataEnabled) {
    Write-Host "[INFO] Dummy data ENABLED via existing DUMMY_DATA environment variable" -ForegroundColor Yellow
}

# Get the script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$transcriptStarted = $false
if ($f) {
    $logPath = if ([System.IO.Path]::IsPathRooted($f)) { $f } else { Join-Path $scriptDir $f }
    $logDir = Split-Path -Parent $logPath

    if ($logDir -and -not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }

    Write-Host "[INFO] Logging output to: $logPath" -ForegroundColor Yellow
    try {
        Start-Transcript -Path $logPath -Append | Out-Null
        $transcriptStarted = $true
    } catch {
        Write-Host "[ERROR] Failed to start logging to $logPath. $_" -ForegroundColor Red
        exit 1
    }
}

# Step 1: Ensure a virtual environment exists
Write-Host "[1/5] Ensuring virtual environment exists..." -ForegroundColor Yellow
if (-not (Test-Path ".venv")) {
    Write-Host "  No .venv detected; creating one..." -ForegroundColor Yellow
    Start-Sleep -Seconds 1

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
} else {
    Write-Host "  [OK] Existing virtual environment found" -ForegroundColor Green
}

# Step 2: Clear Python cache files
Write-Host ""
Write-Host "[2/5] Clearing Python cache files..." -ForegroundColor Yellow
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

# Step 3: Activate virtual environment
Write-Host ""
Write-Host "[3/5] Activating virtual environment..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERROR] Failed to activate virtual environment!" -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] Virtual environment activated" -ForegroundColor Green
Write-Host "  [INFO] Skipping dependency installation for faster reloads. Ensure .venv already has required packages." -ForegroundColor Yellow

# Step 4: Check for API key
Write-Host ""
Write-Host "[4/5] Checking environment setup..." -ForegroundColor Yellow
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

# Step 5: Start the server
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Starting FastAPI server..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
if ($Mobile) {
    Write-Host "Detecting local IP address for mobile access..." -ForegroundColor Yellow
    $mobileIpAddress = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $_.IPAddress -notlike "127.*" -and
        $_.IPAddress -notlike "169.254.*"
    } | Select-Object -First 1).IPAddress

    if ($mobileIpAddress) {
        Write-Host "  [OK] Mobile testing IP detected: $mobileIpAddress" -ForegroundColor Green
    } else {
        Write-Host "  [WARNING] Could not find local IP, using 0.0.0.0" -ForegroundColor Yellow
        $mobileIpAddress = "0.0.0.0"
    }
}

Write-Host "TRACE_LEVEL set to $traceLevel" -ForegroundColor Cyan
if ($dummyDataEnabled) {
    Write-Host "Dummy data mode: ENABLED (restart without -DummyData to disable)" -ForegroundColor Yellow
} else {
    Write-Host "Dummy data mode: disabled (start with -DummyData to serve mock odds)" -ForegroundColor Yellow
}
Write-Host "Server will be available at: http://${hostAddress}:${port}/BensSportsBookApp.html" -ForegroundColor Green
if ($Mobile) {
    Write-Host "Mobile URL: http://${mobileIpAddress}:${port}/BensSportsBookApp.html" -ForegroundColor Cyan
} else {
    Write-Host "Use -Mobile to expose the app to your LAN for device testing" -ForegroundColor Yellow
}
Write-Host "Press CTRL+C to stop the server" -ForegroundColor Yellow
Write-Host ""

# Apply trace level for the running process
$env:TRACE_LEVEL = $traceLevel

# Open browser after a short delay
Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:$port/BensSportsBookApp.html"

# Start uvicorn server
uvicorn main:app --reload --host $hostAddress --port $port

if ($transcriptStarted) {
    Stop-Transcript | Out-Null
}
