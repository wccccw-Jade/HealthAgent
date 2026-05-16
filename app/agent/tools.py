from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from langchain_core.tools import tool

from app.database import SessionLocal
from app.services.medication import (
    add_medication as add_medication_service,
    delete_medication as delete_medication_service,
    list_medications as list_medications_service,
    resolve_medication_plan_conflict as resolve_medication_plan_conflict_service,
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
    medication_days: int | None = None,
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
            medication_days=medication_days,
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


def resolve_medication_plan_conflict(
    user_id: int,
    decision: Literal["keep_existing", "keep_requested", "reset"],
    requested_medication: dict,
    conflicting_medication_id: int | None = None,
    conflicting_medication_ids: list[int] | None = None,
) -> dict:
    with SessionLocal() as db:
        return resolve_medication_plan_conflict_service(
            db=db,
            user_id=user_id,
            decision=decision,
            conflicting_medication_id=conflicting_medication_id,
            conflicting_medication_ids=conflicting_medication_ids,
            requested_medication=requested_medication,
        )


@tool("add_medication")
def add_medication_tool(
    user_id: int,
    name: str,
    dose: str,
    frequency: MedicationFrequencyLiteral,
    times: list[str],
    instructions: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    medication_days: Optional[int] = None,
) -> dict:
    """Add a medication reminder plan for a user. medication_days is required unless start_date and end_date are provided."""
    return add_medication(
        user_id=user_id,
        name=name,
        dose=dose,
        frequency=frequency,
        times=times,
        instructions=instructions,
        start_date=start_date,
        end_date=end_date,
        medication_days=medication_days,
    )


@tool("list_medications")
def list_medications_tool(
    user_id: int,
    active_only: bool = True,
) -> list[dict]:
    """List a user's medication reminder plans."""
    return list_medications(user_id=user_id, active_only=active_only)


@tool("update_medication")
def update_medication_tool(
    user_id: int,
    medication_id: int,
    name: Optional[str] = None,
    dose: Optional[str] = None,
    frequency: Optional[MedicationFrequencyLiteral] = None,
    times: Optional[list[str]] = None,
    instructions: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    is_active: Optional[bool] = None,
) -> dict:
    """Update a medication reminder plan. Dose and time changes require user review."""
    return update_medication(
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


@tool("delete_medication")
def delete_medication_tool(
    user_id: int,
    medication_id: int,
) -> dict:
    """Soft-delete a medication reminder plan after the user asks to remove it."""
    return delete_medication(user_id=user_id, medication_id=medication_id)


MEDICATION_TOOLS = [
    add_medication_tool,
    list_medications_tool,
    update_medication_tool,
    delete_medication_tool,
]

TOOL_FUNCTIONS = {
    "add_medication": add_medication,
    "list_medications": list_medications,
    "update_medication": update_medication,
    "delete_medication": delete_medication,
}
