from __future__ import annotations

import re
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Medication, MedicationFrequency, User

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
) -> dict[str, Any]:
    frequency_value = _validate_frequency(frequency)
    normalized_times = _validate_times(times)
    user = _get_or_create_user(db, user_id)

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
    db.commit()
    db.refresh(medication)

    return {
        "ok": True,
        "requires_review": True,
        "review_reason": "delete_medication",
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
