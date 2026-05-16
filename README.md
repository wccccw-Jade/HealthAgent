# HealthAgent

Personal medication reminder Agent.

Current scope provides:

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
- Day 6 reminder service and scheduler:
  active medication plans generate daily reminder logs, due reminders are pushed
  through Feishu, and `已吃` / `推迟 30 分钟` update reminder state.

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
ENABLE_SCHEDULER=true
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
我每天早上 8 点吃二甲双胍 1 片，饭后，吃 7 天
列一下我现在的药
把二甲双胍改成 2 片
确认
删掉二甲双胍
取消
```

Reminder demo:

```text
我每天 08:00 吃二甲双胍 2 片，饭后，吃 7 天
```

For a fast local test, update the stored medication time to the next minute in
the user's timezone, then either wait for the scheduler or trigger one scan:

```bash
python -c "from app.scheduler.jobs import scan_due_reminders; print(scan_due_reminders())"
```

When Feishu receives a reminder, reply:

```text
已吃
推迟 30 分钟
```

`weekly` medication reminders are intentionally skipped in the Day 6 scheduler
because the current medication schema does not yet store a weekday.
