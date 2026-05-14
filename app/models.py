from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MedicationFrequency(str, Enum):
    DAILY = "daily"
    TWICE_DAILY = "twice_daily"
    WEEKLY = "weekly"
    CUSTOM = "custom"


class ReminderStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    TAKEN = "taken"
    SNOOZED = "snoozed"
    MISSED = "missed"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_user_id = Column(String, unique=True, nullable=True)
    telegram_chat_id = Column(String, unique=True, nullable=True)
    display_name = Column(String, nullable=True)
    timezone = Column(String, nullable=False, default="America/Chicago")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    medications = relationship("Medication", back_populates="user")
    reminder_logs = relationship("ReminderLog", back_populates="user")


class Medication(Base):
    __tablename__ = "medications"

    id = Column(Integer, primary_key=True)
    user_id = Column(ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    dose = Column(String, nullable=False)
    frequency = Column(String, nullable=False)
    times = Column(JSON, nullable=False)
    instructions = Column(Text, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    user = relationship("User", back_populates="medications")
    reminder_logs = relationship("ReminderLog", back_populates="medication")


class ReminderLog(Base):
    __tablename__ = "reminder_logs"
    __table_args__ = (
        UniqueConstraint("user_id", "medication_id", "scheduled_for", name="uq_reminder_scheduled"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(ForeignKey("users.id"), nullable=False, index=True)
    medication_id = Column(ForeignKey("medications.id"), nullable=False, index=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=False, default=ReminderStatus.PENDING.value)
    response_text = Column(Text, nullable=True)
    snoozed_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    user = relationship("User", back_populates="reminder_logs")
    medication = relationship("Medication", back_populates="reminder_logs")
