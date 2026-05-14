from __future__ import annotations

from datetime import date
from typing import Literal

from app.database import SessionLocal
from app.services.medication import (
    add_medication as add_medication_service,
    delete_medication as delete_medication_service,
    list_medications as list_medications_service,
    update_medication as update_medication_service,
)

MedicationFrequencyLiteral = Literal["daily", "twice_daily", "weekly", "custom"]


def add_medication(
    user_id: int,
    name: str,
    dose: str,
    frequency: MedicationFrequencyLiteral,
    times: list[str],
    instructions: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    with SessionLocal() as db:
        return add_medication_service(
            db=db,
            user_id=user_id,
            name=name,
            dose=dose,
            frequency=frequency,
            times=times,
            instructions=instructions,
            start_date=start_date,
            end_date=end_date,
        )


def list_medications(
    user_id: int,
    active_only: bool = True,
) -> list[dict]:
    with SessionLocal() as db:
        return list_medications_service(
            db=db,
            user_id=user_id,
            active_only=active_only,
        )


def update_medication(
    user_id: int,
    medication_id: int,
    name: str | None = None,
    dose: str | None = None,
    frequency: MedicationFrequencyLiteral | None = None,
    times: list[str] | None = None,
    instructions: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    is_active: bool | None = None,
) -> dict:
    with SessionLocal() as db:
        return update_medication_service(
            db=db,
            user_id=user_id,
            medication_id=medication_id,
            name=name,
            dose=dose,
            frequency=frequency,
            times=times,
            instructions=instructions,
            start_date=start_date,
            end_date=end_date,
            is_active=is_active,
        )


def delete_medication(
    user_id: int,
    medication_id: int,
) -> dict:
    with SessionLocal() as db:
        return delete_medication_service(
            db=db,
            user_id=user_id,
            medication_id=medication_id,
        )
