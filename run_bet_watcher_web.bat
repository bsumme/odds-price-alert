@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo Starting Bet Watcher Web (FastAPI)...
start "" http://127.0.0.1:8000/ArbitrageBetFinder.html
uvicorn main:app --reload
