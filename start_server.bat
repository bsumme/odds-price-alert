@echo off
REM Start the Odds Price Alert FastAPI app on Windows.
REM Requirements: dependencies installed in .venv and THE_ODDS_API_KEY set in the environment.
REM This script activates the local virtual environment (when present) and runs uvicorn with reload enabled.

cd /d "%~dp0"

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo No local virtual environment found at .venv\Scripts\activate.bat.
    echo Using the current Python environment to launch the server.
)

echo Starting FastAPI server at http://127.0.0.1:8000 ...
python main.py --reload %*
