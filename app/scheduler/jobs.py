from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from app.database import SessionLocal
from app.services.reminder import create_due_reminder_logs, send_pending_reminders

scheduler = BackgroundScheduler(timezone="UTC")


def scan_due_reminders() -> dict[str, list[int]]:
    db = SessionLocal()
    try:
        created = create_due_reminder_logs(db)
        sent = send_pending_reminders(db)
        return {"created": created, "sent": sent}
    finally:
        db.close()


def start_scheduler() -> None:
    if scheduler.running:
        return

    scheduler.add_job(
        scan_due_reminders,
        "interval",
        minutes=1,
        id="scan_due_reminders",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
