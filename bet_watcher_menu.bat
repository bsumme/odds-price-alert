@echo off
REM Menu to run bet_watcher in normal or snapshot-only mode

cd /d "C:\Users\bsumm\CodingProjects\odds_price_alert"

REM Activate virtual environment
call .venv\Scripts\activate.bat

:menu
echo ===========================================
echo          Bet Watcher Launcher
echo ===========================================
echo  1. Watch bets with alerts (looping)
echo  2. Snapshot only (print current odds once)
echo  3. Exit
echo.
set /p choice=Select an option (1-3): 

if "%choice%"=="1" goto watch
if "%choice%"=="2" goto snapshot
if "%choice%"=="3" goto end

echo.
echo Invalid choice. Please try again.
echo.
goto menu

:watch
echo.
echo Starting Bet Watcher in normal mode...
echo (Press CTRL+C to stop when you're done.)
echo.
python bet_watcher.py
echo.
echo Bet Watcher exited.
echo.
goto menu

:snapshot
echo.
echo Running Bet Watcher in snapshot-only mode...
echo.
python bet_watcher.py -s
echo.
echo Snapshot complete.
echo.
goto menu

:end
echo.
echo Goodbye! Press any key to close this window...
pause >nul
