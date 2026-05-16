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
- Day 5 Feishu bot webhook entrypoint for text messages, URL verification,
  Feishu user binding, and HITL `确认` / `取消` routing through the same Agent
  service used by `/chat`.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest
```

## Feishu Bot Local Development

Set these values in `.env`:

```text
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_VERIFICATION_TOKEN=
FEISHU_ENCRYPT_KEY=
APP_BASE_URL=
OPENAI_API_KEY=
```

Run the API and expose it through ngrok:

```bash
uvicorn app.main:app --reload --port 8000
ngrok http 8000
```

Configure the Feishu event subscription URL:

```text
https://<ngrok-host>/feishu/webhook
```

Subscribe to:

```text
im.message.receive_v1
```

Manual demo script:

```text
我每天早上 8 点吃二甲双胍 1 片，饭后
列一下我现在的药
把二甲双胍改成 2 片
确认
删掉二甲双胍
取消
```
