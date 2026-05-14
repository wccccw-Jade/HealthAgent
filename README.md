# HealthAgent

Personal medication reminder Agent.

Day 1 provides a FastAPI scaffold, SQLite settings, a no-tool `/chat` endpoint,
and LangGraph scratch scripts for graph, interrupt/resume, and checkpoint
research.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest
```
