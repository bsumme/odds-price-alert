# PowerShell script to rebuild virtual environment and run the FastAPI app using cached dependencies when possible
# This script mirrors rebuild_and_run.ps1 but prefers installing packages from the local pip cache before falling back to online downloads.
# Usage: .\rebuild_and_run_cached.ps1 [-d|-t] [-f "<file_path>"]
#   -d : Run the app in debug trace level
#   -t : Run the app in trace level
#   -f : Log script output to the specified file path
#   default (no flag): Run in regular mode
# Example with logging to a full path:
#   .\rebuild_and_run_cached.ps1 -d -f "C:\\logs\\rebuild_and_run.log"

param(
    [switch]$d,
    [switch]$t,
    [string]$f
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
Write-Host "  Rebuilding and Starting Bet Watcher (cached deps)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

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

# Step 1: Deactivate and remove existing virtual environment
Write-Host "[1/6] Checking for existing virtual environment..." -ForegroundColor Yellow
if (Test-Path ".venv") {
    Write-Host "  Stopping any Python processes that might be using the venv..." -ForegroundColor Yellow
    Get-Process python* -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*$scriptDir\\.venv*" } | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1

    Write-Host "  Removing existing .venv directory..." -ForegroundColor Yellow
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
                Get-Process python* -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 2
            } else {
                Write-Host "  [ERROR] Could not remove .venv directory after $maxRetries attempts!" -ForegroundColor Red
                Write-Host "  Please manually close any programs using the .venv folder and try again." -ForegroundColor Red
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

$pycFiles = Get-ChildItem -Path . -Recurse -Filter "*.pyc" -ErrorAction SilentlyContinue
if ($pycFiles) {
    $pycFiles | Remove-Item -Force -ErrorAction SilentlyContinue
    Write-Host "  [OK] Cleared $($pycFiles.Count) .pyc file(s)" -ForegroundColor Green
}

# Step 3: Create new virtual environment
Write-Host ""
Write-Host "[3/6] Creating new virtual environment..." -ForegroundColor Yellow
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

# Step 5: Install dependencies with cache preference
Write-Host ""
Write-Host "[5/6] Installing dependencies (prefer cache)..." -ForegroundColor Yellow
$requirementsPath = Join-Path $scriptDir "requirements.txt"
if (-not (Test-Path $requirementsPath)) {
    Write-Host "  [ERROR] requirements.txt not found at $requirementsPath" -ForegroundColor Red
    exit 1
}

$pipCacheDir = (& python -m pip cache dir 2>$null).Trim()
$wheelCacheDir = if ($pipCacheDir) { Join-Path $pipCacheDir "wheels" } else { $null }
$hasCachedWheels = $false

if ($wheelCacheDir -and (Test-Path $wheelCacheDir)) {
    $cachedWheel = Get-ChildItem -Path $wheelCacheDir -Recurse -Filter "*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cachedWheel) {
        $hasCachedWheels = $true
        Write-Host "  Found cached wheels in: $wheelCacheDir" -ForegroundColor Green
    }
}

$pipInstallPlans = @()
if ($hasCachedWheels) {
    $pipInstallPlans += @{ Description = "cached install"; Args = @("install", "--upgrade", "--no-index", "--find-links", $wheelCacheDir, "-r", $requirementsPath) }
}
$pipInstallPlans += @{ Description = "online install"; Args = @("install", "--upgrade", "-r", $requirementsPath) }

$installed = $false
foreach ($plan in $pipInstallPlans) {
    Write-Host "  Attempting $($plan.Description)..." -ForegroundColor Yellow
    $pipOutput = & pip @($plan.Args) 2>&1

    if ($LASTEXITCODE -eq 0) {
        $installed = $true
        Write-Host "  [OK] Dependencies installed via $($plan.Description)" -ForegroundColor Green
        break
    } else {
        Write-Host "  [WARNING] $($plan.Description) failed with exit code $LASTEXITCODE" -ForegroundColor Yellow

        if ($plan.Description -eq "cached install") {
            $missingWheelHint = $pipOutput | Where-Object { $_ -match "(Could not find a version that satisfies the requirement|No matching distribution found)" }
            if ($missingWheelHint) {
                Write-Host "  Cached wheels are missing one or more required packages. Falling back to online install..." -ForegroundColor Yellow
            }
        }
    }
}

if (-not $installed) {
    Write-Host "  [ERROR] Failed to install dependencies using cache or online sources" -ForegroundColor Red
    exit 1
}

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
} else {
    Write-Host "  [OK] THE_ODDS_API_KEY found" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Starting FastAPI server..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
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

Write-Host "TRACE_LEVEL set to $traceLevel" -ForegroundColor Cyan
Write-Host "Server will be available at: http://127.0.0.1:8000/BensSportsBookApp.html" -ForegroundColor Green
Write-Host "Mobile URL: http://$mobileIpAddress:8000/BensSportsBookApp.html" -ForegroundColor Cyan
Write-Host "Press CTRL+C to stop the server" -ForegroundColor Yellow
Write-Host ""

$env:TRACE_LEVEL = $traceLevel
Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:8000/BensSportsBookApp.html"

uvicorn main:app --reload --host 127.0.0.1 --port 8000

if ($transcriptStarted) {
    Stop-Transcript | Out-Null
}
