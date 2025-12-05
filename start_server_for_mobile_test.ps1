# PowerShell script to start server for mobile testing
# This will find your local IP and start the server accessible from BlueStacks

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Starting Server for Mobile Testing" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Get the script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Find local IP address
Write-Host "Finding your local IP address..." -ForegroundColor Yellow
$ipAddress = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { 
    $_.IPAddress -notlike "127.*" -and 
    $_.IPAddress -notlike "169.254.*" 
} | Select-Object -First 1).IPAddress

if ($ipAddress) {
    Write-Host "  [OK] Found IP: $ipAddress" -ForegroundColor Green
} else {
    Write-Host "  [WARNING] Could not find local IP, using 0.0.0.0" -ForegroundColor Yellow
    $ipAddress = "0.0.0.0"
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Server Configuration" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Server will be accessible at:" -ForegroundColor Green
Write-Host "  Desktop: http://127.0.0.1:8000/BensSportsBookApp.html" -ForegroundColor Cyan
Write-Host "  Mobile:  http://$ipAddress:8000/BensSportsBookApp.html" -ForegroundColor Cyan
Write-Host ""
Write-Host "In BlueStacks, open a browser and navigate to:" -ForegroundColor Yellow
Write-Host "  http://$ipAddress:8000/BensSportsBookApp.html" -ForegroundColor White
Write-Host ""
Write-Host "Press CTRL+C to stop the server" -ForegroundColor Yellow
Write-Host ""

# Check if virtual environment exists
if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    Write-Host "  [ERROR] Virtual environment not found!" -ForegroundColor Red
    Write-Host "  Run rebuild_and_run.ps1 first to create the virtual environment." -ForegroundColor Yellow
    exit 1
}

# Activate virtual environment
try {
    & .\.venv\Scripts\Activate.ps1
    Write-Host "  [OK] Virtual environment activated" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Failed to activate virtual environment!" -ForegroundColor Red
    exit 1
}

# Start server on 0.0.0.0 to accept connections from network
Write-Host ""
Write-Host "Starting server..." -ForegroundColor Yellow
uvicorn main:app --reload --host 0.0.0.0 --port 8000



