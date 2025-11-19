@echo off
cd /d "C:\Users\bsumm\CodingProjects\odds_price_alert"
call .venv\Scripts\activate.bat
echo Starting Bet Watcher Web (FastAPI)...
start "" http://127.0.0.1:8000/
uvicorn main:app --reload
