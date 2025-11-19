@echo off
cd /d "C:\Users\bsumm\CodingProjects\odds_price_alert"
call .venv\Scripts\activate.bat
python bet_watcher.py
echo.
echo Press any key to close this window...
pause >nul
