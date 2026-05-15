# HealthAgent

Personal medication reminder Agent.

Current Day 4 scope provides:

- FastAPI `/health` and `/chat` endpoints.
- SQLite-backed `users`, `medications`, and `reminder_logs` tables.
- Medication add/list/update/delete services and tool wrappers.
- A LangGraph-backed `/chat` entrypoint with per-user checkpoint thread IDs
  using `user:{user_id}`.
- Human-in-the-loop review for high-risk medication changes before execution:
  dose/time updates and deletes are paused until the user replies `确认`.
- `取消` clears the pending action without changing medication data.
- A debug streaming entrypoint through `stream_agent_turn()`.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest
```
