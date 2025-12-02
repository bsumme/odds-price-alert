# Agent Notes for Odds Price Alert

This repository hosts a FastAPI backend with static HTML pages under `frontend/`. Run the site locally with:

- `uvicorn main:app --reload` (serves the API and static frontend at http://127.0.0.1:8000/)
- Open `frontend/value.html` or the other HTML files directly if you only need the static experience.

Key files:
- `main.py` – FastAPI app, dummy data generators, and value/arbitrage logic.
- `frontend/` – static HTML UIs for value finding, arbitrage, and bet watching.
- `logs/real_odds_api_responses.jsonl` – captures real API payloads used to shape dummy data.

Coding style: prefer readable, well-structured Python (PEP 8). Include clear docstrings/comments when adding helpers.
