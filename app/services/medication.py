from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Medication, MedicationFrequency, ReminderLog, ReminderStatus, User

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def add_medication(
    db: Session,
    user_id: int,
    name: str,
    dose: str,
    frequency: str,
    times: list[str],
    instructions: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    medication_days: int | None = None,
) -> dict[str, Any]:
    frequency_value = _validate_frequency(frequency)
    normalized_times = _validate_times(times)
    user = _get_or_create_user(db, user_id)
    start_date, end_date = _resolve_course_dates(
        user=user,
        start_date=start_date,
        end_date=end_date,
        medication_days=medication_days,
    )
    existing = _find_duplicate_active_medication(
        db=db,
        user_id=user.id,
        name=name,
        dose=dose,
        frequency=frequency_value,
        times=normalized_times,
        instructions=instructions,
        start_date=start_date,
        end_date=end_date,
    )
    if existing is not None:
        return {
            "ok": True,
            "duplicate": True,
            "medication": serialize_medication(existing),
        }
    conflicts = _find_overlapping_active_medications(
        db=db,
        user_id=user.id,
        name=name,
        start_date=start_date,
        end_date=end_date,
    )
    if conflicts:
        return {
            "ok": False,
            "reason": "overlapping_medication_plan",
            "message": _build_overlap_message(conflicts, name, dose, frequency_value, normalized_times, start_date, end_date),
            "conflicting_medications": [serialize_medication(conflict) for conflict in conflicts],
            "conflicting_medication": serialize_medication(conflicts[0]),
            "requested_medication": {
                "user_id": user.id,
                "name": name,
                "dose": dose,
                "frequency": frequency_value,
                "times": normalized_times,
                "instructions": instructions,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "is_active": True,
            },
        }

    medication = Medication(
        user_id=user.id,
        name=name,
        dose=dose,
        frequency=frequency_value,
        times=normalized_times,
        instructions=instructions,
        start_date=start_date,
        end_date=end_date,
        is_active=True,
    )
    db.add(medication)
    db.commit()
    db.refresh(medication)

    return {
        "ok": True,
        "duplicate": False,
        "medication": serialize_medication(medication),
    }


def list_medications(
    db: Session,
    user_id: int,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    statement = select(Medication).where(Medication.user_id == user_id)
    if active_only:
        statement = statement.where(Medication.is_active.is_(True))
    statement = statement.order_by(Medication.id)

    medications = db.scalars(statement).all()
    return [serialize_medication(medication) for medication in medications]


def update_medication(
    db: Session,
    user_id: int,
    medication_id: int,
    name: str | None = None,
    dose: str | None = None,
    frequency: str | None = None,
    times: list[str] | None = None,
    instructions: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    medication = _get_user_medication(db, user_id, medication_id)

    requires_review = False
    review_reason: str | None = None

    if name is not None:
        medication.name = name
    if dose is not None:
        medication.dose = dose
        requires_review = True
        review_reason = "dose_change"
    if frequency is not None:
        medication.frequency = _validate_frequency(frequency)
    if times is not None:
        medication.times = _validate_times(times)
        if not requires_review:
            requires_review = True
            review_reason = "time_change"
    if instructions is not None:
        medication.instructions = instructions
    if start_date is not None:
        medication.start_date = start_date
    if end_date is not None:
        medication.end_date = end_date
    if is_active is not None:
        medication.is_active = is_active

    db.commit()
    db.refresh(medication)

    return {
        "ok": True,
        "requires_review": requires_review,
        "review_reason": review_reason,
        "medication": serialize_medication(medication),
    }


def delete_medication(
    db: Session,
    user_id: int,
    medication_id: int,
) -> dict[str, Any]:
    medication = _get_user_medication(db, user_id, medication_id)
    medication.is_active = False
    cancelled_reminder_count = _cancel_open_reminders_for_medication(
        db=db,
        user_id=user_id,
        medication_id=medication_id,
    )
    db.commit()
    db.refresh(medication)

    return {
        "ok": True,
        "requires_review": True,
        "review_reason": "delete_medication",
        "cancelled_reminder_count": cancelled_reminder_count,
        "medication": serialize_medication(medication),
    }


def resolve_medication_plan_conflict(
    db: Session,
    user_id: int,
    decision: Literal["keep_existing", "keep_requested", "reset"],
    requested_medication: dict[str, Any],
    conflicting_medication_id: int | None = None,
    conflicting_medication_ids: list[int] | None = None,
) -> dict[str, Any]:
    conflict_ids = list(dict.fromkeys(conflicting_medication_ids or []))
    if conflicting_medication_id is not None and conflicting_medication_id not in conflict_ids:
        conflict_ids.append(conflicting_medication_id)
    if not conflict_ids:
        raise ValueError("At least one conflicting medication id is required.")

    conflicts = [_get_user_medication(db, user_id, medication_id) for medication_id in conflict_ids]

    if decision == "keep_existing":
        return {
            "ok": True,
            "decision": decision,
            "message": f"已保留原有用药计划：{_format_medication_names(conflicts)}。",
            "medications": [serialize_medication(conflict) for conflict in conflicts],
            "medication": serialize_medication(conflicts[0]),
        }

    cancelled_reminder_count = 0
    for conflict in conflicts:
        conflict.is_active = False
        cancelled_reminder_count += _cancel_open_reminders_for_medication(
            db=db,
            user_id=user_id,
            medication_id=int(conflict.id),
        )

    if decision == "reset":
        db.commit()
        for conflict in conflicts:
            db.refresh(conflict)
        return {
            "ok": True,
            "decision": decision,
            "message": "已停用冲突的旧用药计划。请重新发送完整的新用药计划。",
            "cancelled_reminder_count": cancelled_reminder_count,
            "medications": [serialize_medication(conflict) for conflict in conflicts],
            "medication": serialize_medication(conflicts[0]),
        }

    if decision != "keep_requested":
        raise ValueError(f"Unsupported conflict decision: {decision}")

    requested = _normalize_requested_medication(requested_medication)
    medication = Medication(
        user_id=user_id,
        name=requested["name"],
        dose=requested["dose"],
        frequency=_validate_frequency(requested["frequency"]),
        times=_validate_times(requested["times"]),
        instructions=requested.get("instructions"),
        start_date=requested["start_date"],
        end_date=requested["end_date"],
        is_active=True,
    )
    db.add(medication)
    db.commit()
    db.refresh(medication)
    return {
        "ok": True,
        "decision": decision,
        "message": f"已停用旧计划，并保留新的用药计划：{medication.name}。",
        "cancelled_reminder_count": cancelled_reminder_count,
        "medication": serialize_medication(medication),
    }


def serialize_medication(medication: Medication) -> dict[str, Any]:
    return {
        "id": medication.id,
        "user_id": medication.user_id,
        "name": medication.name,
        "dose": medication.dose,
        "frequency": medication.frequency,
        "times": list(medication.times),
        "instructions": medication.instructions,
        "start_date": medication.start_date.isoformat() if medication.start_date else None,
        "end_date": medication.end_date.isoformat() if medication.end_date else None,
        "is_active": medication.is_active,
    }


def _get_or_create_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is not None:
        return user

    user = User(id=user_id)
    db.add(user)
    db.flush()
    return user


def _get_user_medication(db: Session, user_id: int, medication_id: int) -> Medication:
    medication = db.get(Medication, medication_id)
    if medication is None or medication.user_id != user_id:
        raise ValueError("Medication not found.")
    return medication


def _find_duplicate_active_medication(
    db: Session,
    user_id: int,
    name: str,
    dose: str,
    frequency: str,
    times: list[str],
    instructions: str | None,
    start_date: date,
    end_date: date,
) -> Medication | None:
    candidates = db.scalars(
        select(Medication).where(
            Medication.user_id == user_id,
            Medication.name == name,
            Medication.dose == dose,
            Medication.frequency == frequency,
            Medication.is_active.is_(True),
            Medication.start_date == start_date,
            Medication.end_date == end_date,
        )
    ).all()

    normalized_instructions = instructions or None
    for medication in candidates:
        if list(medication.times or []) == times and (medication.instructions or None) == normalized_instructions:
            return medication
    return None


def _find_overlapping_active_medications(
    db: Session,
    user_id: int,
    name: str,
    start_date: date,
    end_date: date,
) -> list[Medication]:
    return list(db.scalars(
        select(Medication).where(
            Medication.user_id == user_id,
            Medication.name == name,
            Medication.is_active.is_(True),
            Medication.start_date <= end_date,
            Medication.end_date >= start_date,
        ).order_by(Medication.start_date, Medication.id)
    ).all())


def _build_overlap_message(
    conflicts: list[Medication],
    name: str,
    dose: str,
    frequency: str,
    times: list[str],
    start_date: date,
    end_date: date,
) -> str:
    requested_times = "、".join(times)
    conflict_lines = []
    for index, conflict in enumerate(conflicts, start=1):
        existing_times = "、".join(conflict.times or [])
        conflict_lines.append(
            f"{index}. ID {conflict.id}，{conflict.dose}，{existing_times}，{conflict.start_date} 至 {conflict.end_date}"
        )
    return (
        f"已存在 {len(conflicts)} 条重叠的{name}用药计划：\n"
        + "\n".join(conflict_lines)
        + "\n"
        f"你这次要新增的是：{dose}，{requested_times}，{start_date} 至 {end_date}。"
        "同一药品的用药时间线有重叠，我不会自动复用旧提醒时间或直接新增计划。"
        "请回复：保留旧计划、保留新计划，或都不保留重新添加。"
    )


def _format_medication_names(medications: list[Medication]) -> str:
    names = [f"{medication.name} ID {medication.id}" for medication in medications]
    return "、".join(names)


def _cancel_open_reminders_for_medication(
    db: Session,
    user_id: int,
    medication_id: int,
) -> int:
    open_statuses = {
        ReminderStatus.PENDING.value,
        ReminderStatus.SENT.value,
        ReminderStatus.SNOOZED.value,
    }
    reminder_logs = db.scalars(
        select(ReminderLog).where(
            ReminderLog.user_id == user_id,
            ReminderLog.medication_id == medication_id,
            ReminderLog.status.in_(open_statuses),
        )
    ).all()

    for reminder_log in reminder_logs:
        reminder_log.status = ReminderStatus.MISSED.value
        reminder_log.response_text = "Medication plan deleted; reminder cancelled."
    return len(reminder_logs)


def _validate_frequency(frequency: str) -> str:
    try:
        return MedicationFrequency(frequency).value
    except ValueError as exc:
        allowed = ", ".join(item.value for item in MedicationFrequency)
        raise ValueError(f"Invalid medication frequency: {frequency}. Allowed values: {allowed}.") from exc


def _validate_times(times: list[str]) -> list[str]:
    if not times:
        raise ValueError("Medication times must not be empty.")

    normalized_times = [time.strip() for time in times]
    invalid_times = [time for time in normalized_times if not TIME_PATTERN.match(time)]
    if invalid_times:
        raise ValueError(f"Invalid medication time format: {invalid_times[0]}. Expected HH:MM.")

    return normalized_times


def _resolve_course_dates(
    user: User,
    start_date: date | None,
    end_date: date | None,
    medication_days: int | None,
) -> tuple[date, date]:
    if medication_days is not None:
        if medication_days < 1:
            raise ValueError("Medication days must be at least 1.")
        course_start = start_date or _today_for_user(user)
        course_end = course_start + timedelta(days=medication_days - 1)
        if end_date is not None and end_date != course_end:
            raise ValueError("end_date conflicts with medication_days.")
        return course_start, course_end

    if start_date is None or end_date is None:
        raise ValueError("Medication days are required. Provide medication_days or both start_date and end_date.")
    if end_date < start_date:
        raise ValueError("Medication end_date must be on or after start_date.")
    return start_date, end_date


def _today_for_user(user: User) -> date:
    timezone_name = user.timezone or "UTC"
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        tz = timezone.utc
    return datetime.now(timezone.utc).astimezone(tz).date()


def _normalize_requested_medication(requested_medication: dict[str, Any]) -> dict[str, Any]:
    requested = dict(requested_medication)
    for field in ("name", "dose", "frequency", "times", "start_date", "end_date"):
        if requested.get(field) is None:
            raise ValueError(f"Requested medication is missing {field}.")

    if isinstance(requested["start_date"], str):
        requested["start_date"] = date.fromisoformat(requested["start_date"])
    if isinstance(requested["end_date"], str):
        requested["end_date"] = date.fromisoformat(requested["end_date"])
    if not isinstance(requested["times"], list):
        raise ValueError("Requested medication times must be a list.")
    return requested
