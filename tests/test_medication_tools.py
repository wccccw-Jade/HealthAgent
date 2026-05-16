from datetime import datetime, timezone

import pytest

from app.agent import tools
from app.models import Medication, ReminderLog, ReminderStatus, User
from app.services.medication import (
    add_medication,
    delete_medication,
    list_medications,
    resolve_medication_plan_conflict,
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
        medication_days=7,
        instructions="饭后",
    )

    assert result["ok"] is True
    assert result["medication"]["user_id"] == 1
    assert result["medication"]["name"] == "二甲双胍"
    assert result["medication"]["dose"] == "2 片"
    assert result["medication"]["frequency"] == "daily"
    assert result["medication"]["times"] == ["08:00"]
    assert result["medication"]["instructions"] == "饭后"
    assert result["medication"]["start_date"] is not None
    assert result["medication"]["end_date"] is not None
    assert result["medication"]["is_active"] is True
    assert db_session.get(User, 1) is not None
    assert db_session.get(Medication, result["medication"]["id"]) is not None


def test_add_medication_is_idempotent_for_same_active_plan(db_session) -> None:
    first = add_medication(
        db=db_session,
        user_id=1,
        name="布洛芬",
        dose="1 粒",
        frequency="daily",
        times=["15:30"],
        medication_days=3,
    )
    second = add_medication(
        db=db_session,
        user_id=1,
        name="布洛芬",
        dose="1 粒",
        frequency="daily",
        times=["15:30"],
        medication_days=3,
    )

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["medication"]["id"] == first["medication"]["id"]
    assert db_session.query(Medication).count() == 1


def test_add_medication_rejects_overlapping_same_drug_plan(db_session) -> None:
    first = add_medication(
        db=db_session,
        user_id=1,
        name="布洛芬",
        dose="1 粒",
        frequency="daily",
        times=["15:36"],
        medication_days=3,
    )
    second = add_medication(
        db=db_session,
        user_id=1,
        name="布洛芬",
        dose="1 粒",
        frequency="daily",
        times=["15:36"],
        medication_days=2,
    )

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["reason"] == "overlapping_medication_plan"
    assert "重叠" in second["message"]
    assert "保留旧计划" in second["message"]
    assert "保留新计划" in second["message"]
    assert second["conflicting_medication"]["id"] == first["medication"]["id"]
    assert db_session.query(Medication).count() == 1


def test_add_medication_reports_all_overlapping_same_drug_plans(db_session) -> None:
    first = Medication(
        user_id=1,
        name="布洛芬",
        dose="1 粒",
        frequency="daily",
        times=["15:36"],
        start_date=datetime(2026, 5, 16, tzinfo=timezone.utc).date(),
        end_date=datetime(2026, 5, 18, tzinfo=timezone.utc).date(),
        is_active=True,
    )
    second = Medication(
        user_id=1,
        name="布洛芬",
        dose="2 粒",
        frequency="daily",
        times=["15:36"],
        start_date=datetime(2026, 5, 17, tzinfo=timezone.utc).date(),
        end_date=datetime(2026, 5, 19, tzinfo=timezone.utc).date(),
        is_active=True,
    )
    db_session.add(User(id=1))
    db_session.add_all([first, second])
    db_session.commit()

    result = add_medication(
        db=db_session,
        user_id=1,
        name="布洛芬",
        dose="1 粒",
        frequency="daily",
        times=["09:00"],
        start_date=datetime(2026, 5, 17, tzinfo=timezone.utc).date(),
        end_date=datetime(2026, 5, 17, tzinfo=timezone.utc).date(),
    )

    assert result["ok"] is False
    assert result["reason"] == "overlapping_medication_plan"
    assert [item["id"] for item in result["conflicting_medications"]] == [first.id, second.id]
    assert f"ID {first.id}" in result["message"]
    assert f"ID {second.id}" in result["message"]


def test_add_medication_allows_same_drug_after_existing_course_ends(db_session) -> None:
    first = add_medication(
        db=db_session,
        user_id=1,
        name="布洛芬",
        dose="1 粒",
        frequency="daily",
        times=["15:36"],
        start_date=datetime(2026, 5, 16, tzinfo=timezone.utc).date(),
        end_date=datetime(2026, 5, 18, tzinfo=timezone.utc).date(),
    )
    second = add_medication(
        db=db_session,
        user_id=1,
        name="布洛芬",
        dose="1 粒",
        frequency="daily",
        times=["15:36"],
        start_date=datetime(2026, 5, 19, tzinfo=timezone.utc).date(),
        end_date=datetime(2026, 5, 20, tzinfo=timezone.utc).date(),
    )

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["duplicate"] is False
    assert db_session.query(Medication).count() == 2


def test_resolve_conflict_keep_existing_does_not_add_requested(db_session) -> None:
    first = add_medication(
        db=db_session,
        user_id=1,
        name="布洛芬",
        dose="1 粒",
        frequency="daily",
        times=["15:36"],
        medication_days=3,
    )
    conflict = add_medication(
        db=db_session,
        user_id=1,
        name="布洛芬",
        dose="1 粒",
        frequency="daily",
        times=["15:00"],
        medication_days=2,
    )

    result = resolve_medication_plan_conflict(
        db=db_session,
        user_id=1,
        decision="keep_existing",
        conflicting_medication_id=conflict["conflicting_medication"]["id"],
        requested_medication=conflict["requested_medication"],
    )

    assert result["ok"] is True
    assert result["decision"] == "keep_existing"
    assert result["medication"]["id"] == first["medication"]["id"]
    assert db_session.query(Medication).count() == 1


def test_resolve_conflict_keep_requested_replaces_existing(db_session) -> None:
    first = add_medication(
        db=db_session,
        user_id=1,
        name="布洛芬",
        dose="1 粒",
        frequency="daily",
        times=["15:36"],
        medication_days=3,
    )
    conflict = add_medication(
        db=db_session,
        user_id=1,
        name="布洛芬",
        dose="1 粒",
        frequency="daily",
        times=["15:00"],
        medication_days=2,
    )

    result = resolve_medication_plan_conflict(
        db=db_session,
        user_id=1,
        decision="keep_requested",
        conflicting_medication_id=conflict["conflicting_medication"]["id"],
        requested_medication=conflict["requested_medication"],
    )

    all_medications = list_medications(db=db_session, user_id=1, active_only=False)
    active_medications = list_medications(db=db_session, user_id=1)
    assert result["ok"] is True
    assert result["decision"] == "keep_requested"
    assert db_session.get(Medication, first["medication"]["id"]).is_active is False
    assert len(all_medications) == 2
    assert len(active_medications) == 1
    assert active_medications[0]["times"] == ["15:00"]


def test_resolve_conflict_keep_requested_replaces_all_conflicts(db_session) -> None:
    first = Medication(
        user_id=1,
        name="布洛芬",
        dose="1 粒",
        frequency="daily",
        times=["15:36"],
        start_date=datetime(2026, 5, 16, tzinfo=timezone.utc).date(),
        end_date=datetime(2026, 5, 18, tzinfo=timezone.utc).date(),
        is_active=True,
    )
    second = Medication(
        user_id=1,
        name="布洛芬",
        dose="2 粒",
        frequency="daily",
        times=["15:36"],
        start_date=datetime(2026, 5, 17, tzinfo=timezone.utc).date(),
        end_date=datetime(2026, 5, 19, tzinfo=timezone.utc).date(),
        is_active=True,
    )
    db_session.add(User(id=1))
    db_session.add_all([first, second])
    db_session.commit()
    conflict = add_medication(
        db=db_session,
        user_id=1,
        name="布洛芬",
        dose="1 粒",
        frequency="daily",
        times=["09:00"],
        start_date=datetime(2026, 5, 17, tzinfo=timezone.utc).date(),
        end_date=datetime(2026, 5, 17, tzinfo=timezone.utc).date(),
    )

    result = resolve_medication_plan_conflict(
        db=db_session,
        user_id=1,
        decision="keep_requested",
        conflicting_medication_ids=[item["id"] for item in conflict["conflicting_medications"]],
        requested_medication=conflict["requested_medication"],
    )

    active_medications = list_medications(db=db_session, user_id=1)
    assert result["ok"] is True
    assert result["decision"] == "keep_requested"
    assert db_session.get(Medication, first.id).is_active is False
    assert db_session.get(Medication, second.id).is_active is False
    assert len(active_medications) == 1
    assert active_medications[0]["times"] == ["09:00"]


def test_resolve_conflict_reset_deactivates_existing_without_adding(db_session) -> None:
    add_medication(
        db=db_session,
        user_id=1,
        name="布洛芬",
        dose="1 粒",
        frequency="daily",
        times=["15:36"],
        medication_days=3,
    )
    conflict = add_medication(
        db=db_session,
        user_id=1,
        name="布洛芬",
        dose="1 粒",
        frequency="daily",
        times=["15:00"],
        medication_days=2,
    )

    result = resolve_medication_plan_conflict(
        db=db_session,
        user_id=1,
        decision="reset",
        conflicting_medication_id=conflict["conflicting_medication"]["id"],
        requested_medication=conflict["requested_medication"],
    )

    assert result["ok"] is True
    assert result["decision"] == "reset"
    assert list_medications(db=db_session, user_id=1) == []
    assert db_session.query(Medication).count() == 1


def test_list_medications_filters_by_user(db_session) -> None:
    add_medication(
        db=db_session,
        user_id=1,
        name="二甲双胍",
        dose="2 片",
        frequency="daily",
        times=["08:00"],
        medication_days=7,
    )
    add_medication(
        db=db_session,
        user_id=2,
        name="阿托伐他汀",
        dose="20mg",
        frequency="daily",
        times=["20:00"],
        medication_days=7,
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
        medication_days=7,
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
        medication_days=7,
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
        medication_days=7,
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
        medication_days=7,
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
        medication_days=7,
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


def test_delete_medication_cancels_open_reminders(db_session) -> None:
    created = add_medication(
        db=db_session,
        user_id=1,
        name="二甲双胍",
        dose="2 片",
        frequency="daily",
        times=["08:00"],
        medication_days=7,
    )
    medication_id = created["medication"]["id"]
    logs = [
        ReminderLog(user_id=1, medication_id=medication_id, scheduled_for=datetime(2026, 5, 16, 8, 0, tzinfo=timezone.utc), status=ReminderStatus.PENDING.value),
        ReminderLog(user_id=1, medication_id=medication_id, scheduled_for=datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc), status=ReminderStatus.SENT.value),
        ReminderLog(user_id=1, medication_id=medication_id, scheduled_for=datetime(2026, 5, 16, 10, 0, tzinfo=timezone.utc), status=ReminderStatus.SNOOZED.value),
        ReminderLog(user_id=1, medication_id=medication_id, scheduled_for=datetime(2026, 5, 16, 11, 0, tzinfo=timezone.utc), status=ReminderStatus.TAKEN.value),
    ]
    db_session.add_all(logs)
    db_session.commit()

    result = delete_medication(
        db=db_session,
        user_id=1,
        medication_id=medication_id,
    )

    statuses = [log.status for log in db_session.query(ReminderLog).order_by(ReminderLog.id)]
    assert result["cancelled_reminder_count"] == 3
    assert statuses == [
        ReminderStatus.MISSED.value,
        ReminderStatus.MISSED.value,
        ReminderStatus.MISSED.value,
        ReminderStatus.TAKEN.value,
    ]
    assert logs[0].response_text == "Medication plan deleted; reminder cancelled."


def test_add_medication_rejects_invalid_frequency(db_session) -> None:
    with pytest.raises(ValueError, match="Invalid medication frequency"):
        add_medication(
            db=db_session,
            user_id=1,
            name="二甲双胍",
            dose="2 片",
            frequency="every_day",
            times=["08:00"],
            medication_days=7,
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
            medication_days=7,
        )


def test_add_medication_requires_course_days_or_dates(db_session) -> None:
    with pytest.raises(ValueError, match="Medication days are required"):
        add_medication(
            db=db_session,
            user_id=1,
            name="二甲双胍",
            dose="2 片",
            frequency="daily",
            times=["08:00"],
        )


def test_tool_functions_use_session_lifecycle(monkeypatch, test_session_factory) -> None:
    monkeypatch.setattr(tools, "SessionLocal", test_session_factory)

    created = tools.add_medication(
        user_id=1,
        name="二甲双胍",
        dose="2 片",
        frequency="daily",
        times=["08:00"],
        medication_days=7,
        instructions="饭后",
    )
    medications = tools.list_medications(user_id=1)

    assert created["ok"] is True
    assert len(medications) == 1
    assert medications[0]["name"] == "二甲双胍"
