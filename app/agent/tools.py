from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from langchain_core.tools import tool

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
) -> dict:
    """Add a medication reminder plan for a user."""
    return add_medication(
        user_id=user_id,
        name=name,
        dose=dose,
        frequency=frequency,
        times=times,
        instructions=instructions,
        start_date=start_date,
        end_date=end_date,
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
