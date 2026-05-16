from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models import Medication, ReminderLog, ReminderStatus
from app.services.feishu import send_text_message

ReminderSender = Callable[[str, str], Any]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def local_reminder_time_to_utc(local_date: date, hhmm: str, timezone_name: str) -> datetime:
    hour, minute = [int(part) for part in hhmm.split(":", 1)]
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    local_dt = datetime.combine(local_date, time(hour=hour, minute=minute), tzinfo=tz)
    return local_dt.astimezone(timezone.utc)


def create_due_reminder_logs(
    db: Session,
    now: datetime | None = None,
) -> list[int]:
    current = ensure_aware_utc(now or utc_now())
    created_ids: list[int] = []
    medications = db.scalars(
        select(Medication)
        .options(joinedload(Medication.user))
        .where(Medication.is_active.is_(True))
        .order_by(Medication.id)
    ).all()

    for medication in medications:
        user = medication.user
        if user is None:
            continue

        timezone_name = user.timezone or "UTC"
        try:
            local_today = current.astimezone(ZoneInfo(timezone_name)).date()
        except ZoneInfoNotFoundError:
            local_today = current.date()

        if medication.start_date and local_today < medication.start_date:
            continue
        if medication.end_date and local_today > medication.end_date:
            continue
        if medication.frequency == "weekly":
            continue

        for hhmm in medication.times or []:
            try:
                scheduled_for = local_reminder_time_to_utc(local_today, str(hhmm), timezone_name)
            except (ValueError, TypeError):
                continue

            created_id = _create_log_if_missing(
                db=db,
                user_id=int(medication.user_id),
                medication_id=int(medication.id),
                scheduled_for=scheduled_for,
            )
            if created_id is not None:
                created_ids.append(created_id)

    return created_ids


def send_pending_reminders(
    db: Session,
    now: datetime | None = None,
    sender: ReminderSender | None = None,
) -> list[int]:
    current = ensure_aware_utc(now or utc_now())
    send = sender or _send_feishu_open_id_text
    sent_ids: list[int] = []
    logs = db.scalars(
        select(ReminderLog)
        .options(joinedload(ReminderLog.user), joinedload(ReminderLog.medication))
        .where(
            ReminderLog.status == ReminderStatus.PENDING.value,
            ReminderLog.scheduled_for <= current,
        )
        .order_by(ReminderLog.scheduled_for, ReminderLog.id)
    ).all()

    for log in logs:
        user = log.user
        if user is None or not user.feishu_open_id:
            log.status = ReminderStatus.FAILED.value
            log.response_text = "Missing Feishu open_id for reminder delivery."
            db.commit()
            continue

        try:
            send(user.feishu_open_id, build_reminder_message(log))
        except Exception as exc:  # pragma: no cover - exercised through behavior, not exception class.
            log.status = ReminderStatus.FAILED.value
            log.response_text = str(exc)
            db.commit()
            continue

        log.status = ReminderStatus.SENT.value
        log.sent_at = current
        db.commit()
        sent_ids.append(int(log.id))

    return sent_ids


def build_reminder_message(log: ReminderLog) -> str:
    medication = log.medication
    instruction = f"，{medication.instructions}" if medication and medication.instructions else ""
    name = medication.name if medication else "用药"
    dose = medication.dose if medication else ""
    return (
        f"该吃药了：{name}，{dose}{instruction}。\n"
        "回复「已吃」或「推迟 30 分钟」。"
    )


def mark_reminder_taken(
    db: Session,
    user_id: int,
    reminder_log_id: int | None = None,
    medication_id: int | None = None,
    response_text: str = "已吃",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = ensure_aware_utc(now or utc_now())
    match = _find_sent_reminder(
        db=db,
        user_id=user_id,
        reminder_log_id=reminder_log_id,
        medication_id=medication_id,
    )
    if match["status"] != "ok":
        return match

    log = match["log"]
    log.status = ReminderStatus.TAKEN.value
    log.response_text = response_text
    log.updated_at = current
    course_completed = _should_deactivate_after_taken(log, current)
    if course_completed and log.medication is not None:
        log.medication.is_active = False
    db.commit()
    suffix = "该用药计划已完成，已自动停止提醒。" if course_completed else "该用药计划还未结束，会继续按计划提醒。"
    return {
        "ok": True,
        "reason": "taken",
        "reply": f"已记录：{log.medication.name} 已服用。{suffix}",
        "reminder_log_id": log.id,
        "course_completed": course_completed,
    }


def snooze_reminder(
    db: Session,
    user_id: int,
    minutes: int,
    reminder_log_id: int | None = None,
    medication_id: int | None = None,
    response_text: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if minutes < 5 or minutes > 240:
        return {
            "ok": False,
            "reason": "invalid_snooze_minutes",
            "reply": "推迟时间需要在 5 到 240 分钟之间。",
        }

    current = ensure_aware_utc(now or utc_now())
    match = _find_sent_reminder(
        db=db,
        user_id=user_id,
        reminder_log_id=reminder_log_id,
        medication_id=medication_id,
    )
    if match["status"] != "ok":
        return match

    log = match["log"]
    snoozed_until = current + timedelta(minutes=minutes)
    log.status = ReminderStatus.SNOOZED.value
    log.response_text = response_text or f"推迟 {minutes} 分钟"
    log.snoozed_until = snoozed_until
    log.updated_at = current
    db.commit()

    _create_log_if_missing(
        db=db,
        user_id=int(log.user_id),
        medication_id=int(log.medication_id),
        scheduled_for=snoozed_until,
    )

    local_time = _format_user_local_time(snoozed_until, log.user.timezone if log.user else "UTC")
    return {
        "ok": True,
        "reason": "snoozed",
        "reply": f"已推迟，将在 {local_time} 再提醒你：{log.medication.name}。",
        "reminder_log_id": log.id,
        "snoozed_until": snoozed_until.isoformat(),
    }


def handle_reminder_feedback(
    db: Session,
    user_id: int,
    text: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    normalized = text.strip()
    if normalized in {"已吃", "吃了", "已服用"}:
        return mark_reminder_taken(
            db=db,
            user_id=user_id,
            response_text=text,
            now=now,
        )

    named_taken = _parse_named_taken(db=db, user_id=user_id, text=normalized)
    if named_taken is not None:
        return mark_reminder_taken(
            db=db,
            user_id=user_id,
            medication_id=named_taken,
            response_text=text,
            now=now,
        )

    match = re.fullmatch(r"推迟\s*(\d+)\s*分钟", normalized)
    if match:
        return snooze_reminder(
            db=db,
            user_id=user_id,
            minutes=int(match.group(1)),
            response_text=text,
            now=now,
        )

    return None


def handle_reminder_query(
    db: Session,
    user_id: int,
    text: str,
) -> dict[str, Any] | None:
    normalized = text.strip()
    if _is_pending_confirmation_query(normalized):
        return _query_sent_reminders(db=db, user_id=user_id)
    if _is_reminder_list_query(normalized):
        return _query_open_reminders(db=db, user_id=user_id)
    return None


def _query_sent_reminders(db: Session, user_id: int) -> dict[str, Any]:
    logs = db.scalars(
        select(ReminderLog)
        .options(joinedload(ReminderLog.medication), joinedload(ReminderLog.user))
        .where(
            ReminderLog.user_id == user_id,
            ReminderLog.status == ReminderStatus.SENT.value,
        )
        .order_by(
            ReminderLog.sent_at.desc().nullslast(),
            ReminderLog.scheduled_for.desc(),
            ReminderLog.id.desc(),
        )
    ).all()
    if not logs:
        return {
            "ok": True,
            "reason": "no_sent_reminders",
            "reply": "你当前没有待确认的提醒。",
            "reminders": [],
        }

    return {
        "ok": True,
        "reason": "sent_reminders",
        "reply": _build_sent_reminders_reply(logs),
        "reminders": [_serialize_reminder_log(log) for log in logs],
    }


def _query_open_reminders(db: Session, user_id: int) -> dict[str, Any]:
    logs = db.scalars(
        select(ReminderLog)
        .options(joinedload(ReminderLog.medication), joinedload(ReminderLog.user))
        .where(
            ReminderLog.user_id == user_id,
            ReminderLog.status.in_([ReminderStatus.PENDING.value, ReminderStatus.SENT.value, ReminderStatus.SNOOZED.value]),
        )
        .order_by(ReminderLog.scheduled_for, ReminderLog.id)
    ).all()
    if not logs:
        return {
            "ok": True,
            "reason": "no_open_reminders",
            "reply": "你当前没有待发送或待确认的提醒。",
            "reminders": [],
        }

    return {
        "ok": True,
        "reason": "open_reminders",
        "reply": _build_open_reminders_reply(logs),
        "reminders": [_serialize_reminder_log(log) for log in logs],
    }


def _parse_named_taken(db: Session, user_id: int, text: str) -> int | None:
    if not any(keyword in text for keyword in ["已吃", "吃了", "已服用"]):
        return None

    logs = db.scalars(
        select(ReminderLog)
        .options(joinedload(ReminderLog.medication))
        .where(
            ReminderLog.user_id == user_id,
            ReminderLog.status == ReminderStatus.SENT.value,
        )
        .order_by(ReminderLog.sent_at.desc().nullslast(), ReminderLog.scheduled_for.desc())
    ).all()
    matches = [
        int(log.medication_id)
        for log in logs
        if log.medication is not None and log.medication.name in text
    ]
    unique_matches = list(dict.fromkeys(matches))
    if len(unique_matches) == 1:
        return unique_matches[0]

    active_medications = db.scalars(
        select(Medication).where(
            Medication.user_id == user_id,
            Medication.is_active.is_(True),
        )
    ).all()
    active_matches = [
        int(medication.id)
        for medication in active_medications
        if medication.name in text
    ]
    unique_active_matches = list(dict.fromkeys(active_matches))
    if len(unique_active_matches) == 1:
        return unique_active_matches[0]
    return None


def _is_pending_confirmation_query(text: str) -> bool:
    if any(keyword in text for keyword in ["已吃", "吃了", "已服用", "推迟"]):
        return False
    query_keywords = ["看", "查", "查询", "列", "列出", "有哪些", "有没有", "显示"]
    pending_keywords = ["待确认", "未确认", "没确认", "待回复", "没回复", "待处理"]
    return any(keyword in text for keyword in query_keywords) and any(keyword in text for keyword in pending_keywords)


def _is_reminder_list_query(text: str) -> bool:
    if any(keyword in text for keyword in ["已吃", "吃了", "已服用", "推迟"]):
        return False
    query_keywords = ["看", "查", "查询", "列", "列出", "有哪些", "有没有", "显示"]
    return "提醒" in text and any(keyword in text for keyword in query_keywords)


def _build_sent_reminders_reply(logs: list[ReminderLog]) -> str:
    lines = ["你当前有以下待确认提醒："]
    for index, log in enumerate(logs, start=1):
        medication = log.medication
        scheduled = _format_user_local_time(log.scheduled_for, log.user.timezone if log.user else "UTC")
        if medication is None:
            lines.append(f"{index}. 用药提醒，{scheduled}")
        else:
            lines.append(f"{index}. {medication.name}，{medication.dose}，{scheduled}")
    lines.append("请回复「已吃」或「药名已吃」，也可以回复「推迟 30 分钟」。")
    return "\n".join(lines)


def _build_open_reminders_reply(logs: list[ReminderLog]) -> str:
    lines = ["你当前有以下提醒："]
    for index, log in enumerate(logs, start=1):
        medication = log.medication
        scheduled = _format_user_local_time(log.scheduled_for, log.user.timezone if log.user else "UTC")
        status_label = {
            ReminderStatus.PENDING.value: "待发送",
            ReminderStatus.SENT.value: "待确认",
            ReminderStatus.SNOOZED.value: "已推迟",
        }.get(log.status, log.status)
        if medication is None:
            lines.append(f"{index}. 用药提醒，{scheduled}，{status_label}")
        else:
            lines.append(f"{index}. {medication.name}，{medication.dose}，{scheduled}，{status_label}")
    return "\n".join(lines)


def _serialize_reminder_log(log: ReminderLog) -> dict[str, Any]:
    medication = log.medication
    return {
        "id": log.id,
        "user_id": log.user_id,
        "medication_id": log.medication_id,
        "medication_name": medication.name if medication else None,
        "dose": medication.dose if medication else None,
        "scheduled_for": ensure_aware_utc(log.scheduled_for).isoformat(),
        "sent_at": ensure_aware_utc(log.sent_at).isoformat() if log.sent_at else None,
        "status": log.status,
    }


def _find_sent_reminder(
    db: Session,
    user_id: int,
    reminder_log_id: int | None = None,
    medication_id: int | None = None,
) -> dict[str, Any]:
    statement = (
        select(ReminderLog)
        .options(joinedload(ReminderLog.medication), joinedload(ReminderLog.user))
        .where(
            ReminderLog.user_id == user_id,
            ReminderLog.status == ReminderStatus.SENT.value,
        )
    )
    if reminder_log_id is not None:
        statement = statement.where(ReminderLog.id == reminder_log_id)
    if medication_id is not None:
        statement = statement.where(ReminderLog.medication_id == medication_id)

    logs = db.scalars(
        statement.order_by(
            ReminderLog.sent_at.desc().nullslast(),
            ReminderLog.scheduled_for.desc(),
            ReminderLog.id.desc(),
        )
    ).all()

    if not logs:
        return {
            "ok": False,
            "status": "not_found",
            "reason": "no_sent_reminder",
            "reply": "我没有找到正在等待确认的提醒。",
        }
    if len(logs) > 1 and reminder_log_id is None and medication_id is None:
        return {
            "ok": False,
            "status": "ambiguous",
            "reason": "ambiguous",
            "reply": _build_ambiguous_reply(logs),
        }
    return {"ok": True, "status": "ok", "log": logs[0]}


def _build_ambiguous_reply(logs: list[ReminderLog]) -> str:
    lines = ["你现在有多条待确认提醒，请回复具体药名，例如「二甲双胍已吃」："]
    for index, log in enumerate(logs, start=1):
        medication = log.medication
        scheduled = _format_user_local_time(log.scheduled_for, log.user.timezone if log.user else "UTC")
        if medication is None:
            lines.append(f"{index}. 用药提醒，{scheduled}")
        else:
            lines.append(f"{index}. {medication.name}，{medication.dose}，{scheduled}")
    return "\n".join(lines)


def _create_log_if_missing(
    db: Session,
    user_id: int,
    medication_id: int,
    scheduled_for: datetime,
) -> int | None:
    scheduled_for = ensure_aware_utc(scheduled_for)
    existing = db.scalar(
        select(ReminderLog.id).where(
            ReminderLog.user_id == user_id,
            ReminderLog.medication_id == medication_id,
            ReminderLog.scheduled_for == scheduled_for,
        )
    )
    if existing is not None:
        return None

    log = ReminderLog(
        user_id=user_id,
        medication_id=medication_id,
        scheduled_for=scheduled_for,
        status=ReminderStatus.PENDING.value,
    )
    db.add(log)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    db.refresh(log)
    return int(log.id)


def _should_deactivate_after_taken(log: ReminderLog, current: datetime) -> bool:
    medication = log.medication
    if medication is None or medication.end_date is None:
        return False

    timezone_name = log.user.timezone if log.user and log.user.timezone else "UTC"
    try:
        local_today = ensure_aware_utc(current).astimezone(ZoneInfo(timezone_name)).date()
    except ZoneInfoNotFoundError:
        local_today = ensure_aware_utc(current).date()
    return local_today >= medication.end_date


def _send_feishu_open_id_text(open_id: str, text: str) -> dict[str, Any]:
    return send_text_message(open_id, text, receive_id_type="open_id")


def _format_user_local_time(value: datetime, timezone_name: str) -> str:
    value = ensure_aware_utc(value)
    try:
        local_value = value.astimezone(ZoneInfo(timezone_name))
    except ZoneInfoNotFoundError:
        local_value = value
    return local_value.strftime("%H:%M")
