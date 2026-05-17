# HealthAgent

HealthAgent is a personal medication reminder Agent. It helps a user record, list, update, and delete medication plans through natural language, then sends due reminders through a Feishu bot.

## What It Does

- Manages structured medication plans in SQLite.
- Runs a LangGraph Agent for natural-language medication CRUD.
- Uses `SqliteSaver` checkpoints with `thread_id=user:{user_id}` for cross-session state recovery.
- Pauses high-risk changes with human-in-the-loop confirmation before execution.
- Sends scheduled reminders through Feishu.
- Handles reminder feedback such as `已吃` and `推迟 30 分钟`.
- Records LangSmith traces when tracing environment variables are enabled.

## Safety Boundary

This project is only for medication reminder management. It does not diagnose disease, recommend dose changes, evaluate drug interactions, or replace advice from a doctor or pharmacist. High-risk plan changes, such as dose changes and deletion, require user confirmation before execution.

## Architecture

```text
Feishu User
    |
    v
FastAPI /feishu/webhook
    |
    +--> Reminder feedback router
    |        +--> reminder_logs: taken / snoozed
    |
    +--> Conversation service
             |
             v
        LangGraph Agent
             |
             +--> Medication tools
             +--> Human review interrupt/resume
             +--> SqliteSaver checkpoints

APScheduler
    |
    v
Reminder service --> Feishu message API
```

## LangGraph Flow

```text
START
  -> agent
  -> route_after_agent
      -> tools -> agent
      -> review_gate -> human_review -> END
      -> fallback -> route_after_agent
      -> END
```

- `agent` calls the LLM with medication tools bound.
- `tools` executes low-risk tool calls.
- `review_gate` catches high-risk operations such as deletion, dose changes, and reminder time changes.
- `human_review` uses interrupt/resume so the user can reply `确认` or `取消`.
- `fallback` handles deterministic Chinese demo rules when the LLM does not call a tool.
- Checkpoints are isolated by user with `thread_id=user:{user_id}`.

## Data Model

- `users`: internal users plus Feishu binding fields.
- `medications`: active medication plans, dose, frequency, reminder times, instructions, and course dates.
- `reminder_logs`: scheduled reminder instances, send status, user response, and snooze state.
- LangGraph checkpoints are stored separately in `langgraph_checkpoints.sqlite`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env` from `.env.example`:

```text
APP_ENV=dev
ENABLE_SCHEDULER=true
DATABASE_URL=sqlite:///./health_agent.db
LANGGRAPH_CHECKPOINT_DB=./langgraph_checkpoints.sqlite
OPENAI_API_KEY=
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_VERIFICATION_TOKEN=
FEISHU_ENCRYPT_KEY=
APP_BASE_URL=
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=health-agent
```

Initialize the database if needed:

```bash
python scripts/init_db.py
```

## Run Locally

```bash
uvicorn app.main:app --reload --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Chat API:

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":1,"message":"列一下我现在的药","channel":"cli"}'
```

Disable the scheduler during API-only debugging:

```bash
ENABLE_SCHEDULER=false uvicorn app.main:app --reload --port 8000
```

## Feishu Bot Setup

Run the API and expose it with ngrok:

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

The webhook handles URL verification, token validation, encrypted payloads, text messages, user binding, duplicate message IDs, reminder feedback, and normal Agent messages.

## LangSmith Tracing

LangGraph and LangChain read standard LangSmith environment variables:

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_PROJECT=health-agent
export LANGSMITH_API_KEY=<your-langsmith-key>
export OPENAI_API_KEY=<your-openai-key>
```

Generate a trace:

```bash
python - <<'PY'
from app.agent.graph import run_agent_turn

print(run_agent_turn(1, "我每天早上 8 点吃二甲双胍 1 片，饭后，吃 7 天", "cli").reply)
print(run_agent_turn(1, "列一下我现在的药", "cli").reply)
print(run_agent_turn(1, "把二甲双胍改成 2 片", "cli").reply)
print(run_agent_turn(1, "确认", "cli").reply)
PY
```

Trace screenshot target:

```text
docs/images/langsmith-trace.png
```

## Demo Script

Send these messages in Feishu or through `/chat`:

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

For a fast local reminder test, update the stored medication time to the next minute in the user's timezone, then wait for the scheduler or trigger one scan:

```bash
python -c "from app.scheduler.jobs import scan_due_reminders; print(scan_due_reminders())"
```

When Feishu receives a reminder, reply:

```text
已吃
推迟 30 分钟
```

To inspect reminder state:

```bash
sqlite3 health_agent.db "select id, medication_id, scheduled_for, sent_at, status from reminder_logs order by id desc limit 10;"
```

## Tests

```bash
pytest
```

If `pytest` is not on `PATH`, use:

```bash
.venv/bin/python -m pytest
```

Focused checks:

```bash
.venv/bin/python -m pytest tests/test_agent_graph.py tests/test_agent_hitl.py
.venv/bin/python -m pytest tests/test_feishu_webhook.py tests/test_feishu_service.py
.venv/bin/python -m pytest tests/test_reminder_service.py
```

## Known Limits

- `weekly` medication reminders are skipped because the current schema does not store a weekday.
- The scheduler is designed for a single-process local demo. Multi-replica deployment needs a distributed lock or external task queue.
- Feishu support targets one-on-one text bot conversations.
- There is no medication knowledge base, drug interaction checker, OCR, or diagnosis workflow.
- There is no Alembic migration layer yet. During local development, rebuilding SQLite is simpler.
- Feishu send retry is intentionally small and bounded; permanent delivery failure is recorded on `reminder_logs`.

## Roadmap

- Add weekday support for weekly reminders.
- Add an admin/debug page for reminder logs.
- Add stronger retry and dead-letter handling for notification delivery.
- Add deployment docs for Railway or Fly.io.
- Add LangSmith screenshots and a short recorded demo.
