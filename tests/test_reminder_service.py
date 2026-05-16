from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.models import Medication, ReminderLog, ReminderStatus, User
from app.services.reminder import (
    create_due_reminder_logs,
    handle_reminder_feedback,
    handle_reminder_query,
    mark_reminder_taken,
    send_pending_reminders,
    snooze_reminder,
)


def _create_user(db_session, user_id: int = 1, open_id: str | None = "ou_test") -> User:
    user = User(
        id=user_id,
        feishu_open_id=open_id,
        timezone="America/Chicago",
    )
    db_session.add(user)
    db_session.commit()
    return user


def _create_medication(
    db_session,
    user_id: int = 1,
    name: str = "二甲双胍",
    dose: str = "2 片",
    times: list[str] | None = None,
    is_active: bool = True,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Medication:
    medication = Medication(
        user_id=user_id,
        name=name,
        dose=dose,
        frequency="daily",
        times=times or ["08:00"],
        instructions="饭后",
        start_date=start_date or date(2026, 5, 16),
        end_date=end_date or date(2026, 5, 22),
        is_active=is_active,
    )
    db_session.add(medication)
    db_session.commit()
    db_session.refresh(medication)
    return medication


def _create_sent_log(
    db_session,
    user_id: int = 1,
    medication_id: int | None = None,
    scheduled_for: datetime | None = None,
    sent_at: datetime | None = None,
) -> ReminderLog:
    medication_id = medication_id or _create_medication(db_session, user_id=user_id).id
    current = datetime(2026, 5, 16, 13, 0, tzinfo=timezone.utc)
    log = ReminderLog(
        user_id=user_id,
        medication_id=medication_id,
        scheduled_for=scheduled_for or current,
        sent_at=sent_at or current,
        status=ReminderStatus.SENT.value,
    )
    db_session.add(log)
    db_session.commit()
    db_session.refresh(log)
    return log


def test_create_due_reminder_logs_creates_today_logs_once(db_session) -> None:
    _create_user(db_session)
    medication = _create_medication(db_session, times=["08:00", "20:00"])
    now = datetime(2026, 5, 16, 13, 5, tzinfo=timezone.utc)

    created = create_due_reminder_logs(db_session, now=now)
    created_again = create_due_reminder_logs(db_session, now=now)

    assert len(created) == 2
    assert created_again == []
    logs = db_session.query(ReminderLog).order_by(ReminderLog.id).all()
    assert [log.medication_id for log in logs] == [medication.id, medication.id]
    assert {log.status for log in logs} == {ReminderStatus.PENDING.value}


def test_create_due_reminder_logs_skips_inactive_and_out_of_range(db_session) -> None:
    _create_user(db_session)
    _create_medication(db_session, name="inactive", is_active=False)
    _create_medication(db_session, name="future", start_date=date(2026, 5, 17))
    _create_medication(db_session, name="expired", end_date=date(2026, 5, 15))

    created = create_due_reminder_logs(
        db_session,
        now=datetime(2026, 5, 16, 13, 5, tzinfo=timezone.utc),
    )

    assert created == []
    assert db_session.query(ReminderLog).count() == 0


def test_create_due_reminder_logs_does_not_create_before_start_date(db_session) -> None:
    _create_user(db_session)
    _create_medication(
        db_session,
        name="布洛芬",
        times=["09:00"],
        start_date=date(2026, 5, 17),
        end_date=date(2026, 5, 17),
    )

    created = create_due_reminder_logs(
        db_session,
        now=datetime(2026, 5, 16, 20, 0, tzinfo=timezone.utc),
    )

    assert created == []
    assert db_session.query(ReminderLog).count() == 0


def test_send_pending_reminders_sends_and_marks_sent(db_session) -> None:
    _create_user(db_session)
    medication = _create_medication(db_session)
    log = ReminderLog(
        user_id=1,
        medication_id=medication.id,
        scheduled_for=datetime(2026, 5, 16, 13, 0, tzinfo=timezone.utc),
        status=ReminderStatus.PENDING.value,
    )
    db_session.add(log)
    db_session.commit()
    sent_messages = []

    sent = send_pending_reminders(
        db_session,
        now=datetime(2026, 5, 16, 13, 1, tzinfo=timezone.utc),
        sender=lambda open_id, text: sent_messages.append((open_id, text)),
    )

    db_session.refresh(log)
    assert sent == [log.id]
    assert log.status == ReminderStatus.SENT.value
    assert log.sent_at is not None
    assert sent_messages == [("ou_test", "该吃药了：二甲双胍，2 片，饭后。\n回复「已吃」或「推迟 30 分钟」。")]


def test_send_pending_reminders_marks_failed_without_open_id(db_session) -> None:
    _create_user(db_session, open_id=None)
    medication = _create_medication(db_session)
    log = ReminderLog(
        user_id=1,
        medication_id=medication.id,
        scheduled_for=datetime(2026, 5, 16, 13, 0, tzinfo=timezone.utc),
        status=ReminderStatus.PENDING.value,
    )
    db_session.add(log)
    db_session.commit()

    sent = send_pending_reminders(
        db_session,
        now=datetime(2026, 5, 16, 13, 1, tzinfo=timezone.utc),
        sender=lambda open_id, text: None,
    )

    db_session.refresh(log)
    assert sent == []
    assert log.status == ReminderStatus.FAILED.value
    assert "open_id" in log.response_text


def test_mark_reminder_taken_updates_single_sent_log(db_session) -> None:
    _create_user(db_session)
    log = _create_sent_log(db_session)

    result = mark_reminder_taken(
        db_session,
        user_id=1,
        now=datetime(2026, 5, 16, 13, 10, tzinfo=timezone.utc),
    )

    db_session.refresh(log)
    assert result["ok"] is True
    assert result["reminder_log_id"] == log.id
    assert log.status == ReminderStatus.TAKEN.value
    assert log.response_text == "已吃"
    assert log.medication.is_active is True
    assert result["course_completed"] is False


def test_mark_reminder_taken_deactivates_medication_when_course_completed(db_session) -> None:
    _create_user(db_session)
    medication = _create_medication(db_session, end_date=date(2026, 5, 16))
    log = _create_sent_log(db_session, medication_id=medication.id)

    result = mark_reminder_taken(
        db_session,
        user_id=1,
        now=datetime(2026, 5, 16, 13, 10, tzinfo=timezone.utc),
    )

    db_session.refresh(medication)
    db_session.refresh(log)
    assert result["ok"] is True
    assert result["course_completed"] is True
    assert log.status == ReminderStatus.TAKEN.value
    assert medication.is_active is False


def test_mark_reminder_taken_returns_ambiguous_for_multiple_sent_logs(db_session) -> None:
    _create_user(db_session)
    first = _create_medication(db_session, name="二甲双胍")
    second = _create_medication(db_session, name="阿托伐他汀", dose="20mg")
    _create_sent_log(db_session, medication_id=first.id)
    _create_sent_log(
        db_session,
        medication_id=second.id,
        scheduled_for=datetime(2026, 5, 16, 13, 5, tzinfo=timezone.utc),
        sent_at=datetime(2026, 5, 16, 13, 5, tzinfo=timezone.utc),
    )

    result = mark_reminder_taken(db_session, user_id=1)

    assert result["ok"] is False
    assert result["reason"] == "ambiguous"
    assert "二甲双胍" in result["reply"]
    assert "阿托伐他汀" in result["reply"]
    assert {log.status for log in db_session.query(ReminderLog).all()} == {ReminderStatus.SENT.value}


def test_snooze_reminder_marks_original_and_creates_pending_log(db_session) -> None:
    _create_user(db_session)
    log = _create_sent_log(db_session)
    now = datetime(2026, 5, 16, 13, 10, tzinfo=timezone.utc)

    result = snooze_reminder(db_session, user_id=1, minutes=30, now=now)

    db_session.refresh(log)
    logs = db_session.query(ReminderLog).order_by(ReminderLog.id).all()
    assert result["ok"] is True
    assert log.status == ReminderStatus.SNOOZED.value
    expected_snoozed_until = (now + timedelta(minutes=30)).replace(tzinfo=None)
    assert log.snoozed_until == expected_snoozed_until
    assert len(logs) == 2
    assert logs[1].status == ReminderStatus.PENDING.value
    assert logs[1].scheduled_for == expected_snoozed_until


def test_handle_reminder_feedback_only_matches_short_commands(db_session) -> None:
    _create_user(db_session)
    log = _create_sent_log(db_session)

    taken = handle_reminder_feedback(db_session, user_id=1, text="已吃")
    ordinary = handle_reminder_feedback(db_session, user_id=1, text="列一下我的药")

    db_session.refresh(log)
    assert taken["ok"] is True
    assert log.status == ReminderStatus.TAKEN.value
    assert ordinary is None


def test_handle_reminder_feedback_matches_named_taken_without_agent(db_session) -> None:
    _create_user(db_session)
    first = _create_medication(db_session, name="二甲双胍")
    second = _create_medication(db_session, name="布洛芬")
    first_log = _create_sent_log(db_session, medication_id=first.id)
    second_log = _create_sent_log(
        db_session,
        medication_id=second.id,
        scheduled_for=datetime(2026, 5, 16, 13, 5, tzinfo=timezone.utc),
        sent_at=datetime(2026, 5, 16, 13, 5, tzinfo=timezone.utc),
    )

    result = handle_reminder_feedback(db_session, user_id=1, text="布洛芬已吃")

    db_session.refresh(first_log)
    db_session.refresh(second_log)
    assert result["ok"] is True
    assert first_log.status == ReminderStatus.SENT.value
    assert second_log.status == ReminderStatus.TAKEN.value


def test_handle_reminder_feedback_named_taken_without_sent_log_is_not_agent_text(db_session) -> None:
    _create_user(db_session)
    medication = _create_medication(db_session, name="布洛芬")

    result = handle_reminder_feedback(db_session, user_id=1, text="布洛芬已吃")

    db_session.refresh(medication)
    assert result["ok"] is False
    assert result["reason"] == "no_sent_reminder"
    assert medication.is_active is True


def test_handle_reminder_query_returns_sent_logs_only(db_session) -> None:
    _create_user(db_session)
    sent_medication = _create_medication(db_session, name="布洛芬", dose="1 粒")
    pending_medication = _create_medication(db_session, name="二甲双胍", dose="1 片")
    _create_sent_log(db_session, medication_id=sent_medication.id)
    db_session.add(
        ReminderLog(
            user_id=1,
            medication_id=pending_medication.id,
            scheduled_for=datetime(2026, 5, 16, 14, 0, tzinfo=timezone.utc),
            status=ReminderStatus.PENDING.value,
        )
    )
    db_session.commit()

    result = handle_reminder_query(db_session, user_id=1, text="看一下待确认")

    assert result["ok"] is True
    assert result["reason"] == "sent_reminders"
    assert "布洛芬" in result["reply"]
    assert "二甲双胍" not in result["reply"]
    assert len(result["reminders"]) == 1
    assert result["reminders"][0]["status"] == ReminderStatus.SENT.value


def test_handle_reminder_query_returns_empty_message(db_session) -> None:
    _create_user(db_session)

    result = handle_reminder_query(db_session, user_id=1, text="有哪些未确认提醒")
    ordinary = handle_reminder_query(db_session, user_id=1, text="列一下我的药")

    assert result["ok"] is True
    assert result["reason"] == "no_sent_reminders"
    assert result["reminders"] == []
    assert "没有待确认" in result["reply"]
    assert ordinary is None


def test_handle_reminder_query_lists_pending_and_sent_reminders(db_session) -> None:
    _create_user(db_session)
    pending_medication = _create_medication(db_session, name="布洛芬", dose="1 粒")
    sent_medication = _create_medication(db_session, name="维C", dose="2 片")
    db_session.add(
        ReminderLog(
            user_id=1,
            medication_id=pending_medication.id,
            scheduled_for=datetime(2026, 5, 17, 14, 0, tzinfo=timezone.utc),
            status=ReminderStatus.PENDING.value,
        )
    )
    _create_sent_log(db_session, medication_id=sent_medication.id)
    db_session.commit()

    result = handle_reminder_query(db_session, user_id=1, text="看看提醒")

    assert result["ok"] is True
    assert result["reason"] == "open_reminders"
    assert "布洛芬" in result["reply"]
    assert "待发送" in result["reply"]
    assert "维C" in result["reply"]
    assert "待确认" in result["reply"]
