import pytest

from app.agent import tools
from app.models import Medication, User
from app.services.medication import (
    add_medication,
    delete_medication,
    list_medications,
    update_medication,
)


def test_add_medication_creates_user_and_medication(db_session) -> None:
    result = add_medication(
        db=db_session,
        user_id=1,
        name="二甲双胍",
        dose="2 片",
        frequency="daily",
        times=["08:00"],
        instructions="饭后",
    )

    assert result["ok"] is True
    assert result["medication"]["user_id"] == 1
    assert result["medication"]["name"] == "二甲双胍"
    assert result["medication"]["dose"] == "2 片"
    assert result["medication"]["frequency"] == "daily"
    assert result["medication"]["times"] == ["08:00"]
    assert result["medication"]["instructions"] == "饭后"
    assert result["medication"]["is_active"] is True
    assert db_session.get(User, 1) is not None
    assert db_session.get(Medication, result["medication"]["id"]) is not None


def test_list_medications_filters_by_user(db_session) -> None:
    add_medication(
        db=db_session,
        user_id=1,
        name="二甲双胍",
        dose="2 片",
        frequency="daily",
        times=["08:00"],
    )
    add_medication(
        db=db_session,
        user_id=2,
        name="阿托伐他汀",
        dose="20mg",
        frequency="daily",
        times=["20:00"],
    )

    medications = list_medications(db=db_session, user_id=1)

    assert len(medications) == 1
    assert medications[0]["user_id"] == 1
    assert medications[0]["name"] == "二甲双胍"


def test_list_medications_hides_inactive_by_default(db_session) -> None:
    created = add_medication(
        db=db_session,
        user_id=1,
        name="二甲双胍",
        dose="2 片",
        frequency="daily",
        times=["08:00"],
    )
    medication_id = created["medication"]["id"]

    delete_medication(db=db_session, user_id=1, medication_id=medication_id)

    assert list_medications(db=db_session, user_id=1) == []
    all_medications = list_medications(db=db_session, user_id=1, active_only=False)
    assert len(all_medications) == 1
    assert all_medications[0]["is_active"] is False


def test_update_medication_instructions_does_not_require_review(db_session) -> None:
    created = add_medication(
        db=db_session,
        user_id=1,
        name="二甲双胍",
        dose="2 片",
        frequency="daily",
        times=["08:00"],
    )

    result = update_medication(
        db=db_session,
        user_id=1,
        medication_id=created["medication"]["id"],
        instructions="饭后",
    )

    assert result["ok"] is True
    assert result["requires_review"] is False
    assert result["review_reason"] is None
    assert result["medication"]["instructions"] == "饭后"


def test_update_medication_dose_requires_review(db_session) -> None:
    created = add_medication(
        db=db_session,
        user_id=1,
        name="二甲双胍",
        dose="1 片",
        frequency="daily",
        times=["08:00"],
    )

    result = update_medication(
        db=db_session,
        user_id=1,
        medication_id=created["medication"]["id"],
        dose="2 片",
    )

    assert result["ok"] is True
    assert result["requires_review"] is True
    assert result["review_reason"] == "dose_change"
    assert result["medication"]["dose"] == "2 片"


def test_update_medication_times_requires_review(db_session) -> None:
    created = add_medication(
        db=db_session,
        user_id=1,
        name="二甲双胍",
        dose="2 片",
        frequency="daily",
        times=["08:00"],
    )

    result = update_medication(
        db=db_session,
        user_id=1,
        medication_id=created["medication"]["id"],
        times=["09:00"],
    )

    assert result["ok"] is True
    assert result["requires_review"] is True
    assert result["review_reason"] == "time_change"
    assert result["medication"]["times"] == ["09:00"]


def test_delete_medication_soft_deletes_and_requires_review(db_session) -> None:
    created = add_medication(
        db=db_session,
        user_id=1,
        name="二甲双胍",
        dose="2 片",
        frequency="daily",
        times=["08:00"],
    )

    result = delete_medication(
        db=db_session,
        user_id=1,
        medication_id=created["medication"]["id"],
    )

    assert result["ok"] is True
    assert result["requires_review"] is True
    assert result["review_reason"] == "delete_medication"
    assert result["medication"]["is_active"] is False


def test_add_medication_rejects_invalid_frequency(db_session) -> None:
    with pytest.raises(ValueError, match="Invalid medication frequency"):
        add_medication(
            db=db_session,
            user_id=1,
            name="二甲双胍",
            dose="2 片",
            frequency="every_day",
            times=["08:00"],
        )


def test_add_medication_rejects_invalid_time_format(db_session) -> None:
    with pytest.raises(ValueError, match="Invalid medication time format"):
        add_medication(
            db=db_session,
            user_id=1,
            name="二甲双胍",
            dose="2 片",
            frequency="daily",
            times=["8:00"],
        )


def test_tool_functions_use_session_lifecycle(monkeypatch, test_session_factory) -> None:
    monkeypatch.setattr(tools, "SessionLocal", test_session_factory)

    created = tools.add_medication(
        user_id=1,
        name="二甲双胍",
        dose="2 片",
        frequency="daily",
        times=["08:00"],
        instructions="饭后",
    )
    medications = tools.list_medications(user_id=1)

    assert created["ok"] is True
    assert len(medications) == 1
    assert medications[0]["name"] == "二甲双胍"
