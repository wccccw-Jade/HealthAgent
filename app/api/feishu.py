from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.conversation_service import handle_user_message
from app.services.feishu import (
    decrypt_feishu_payload,
    extract_text_from_content,
    get_or_create_user_from_feishu,
    send_text_message,
    verify_feishu_token,
)
from app.services.reminder import handle_reminder_feedback, handle_reminder_query

router = APIRouter(prefix="/feishu", tags=["feishu"])
_PROCESSED_MESSAGE_IDS: dict[str, float] = {}
_MESSAGE_ID_TTL_SECONDS = 300


@router.post("/webhook")
def feishu_webhook(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    encrypted_payload = payload.get("encrypt")
    if isinstance(encrypted_payload, str):
        try:
            payload = decrypt_feishu_payload(encrypted_payload)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.get("type") == "url_verification":
        if not verify_feishu_token(payload.get("token")):
            raise HTTPException(status_code=401, detail="Invalid Feishu token")
        return {"challenge": payload.get("challenge")}

    if not verify_feishu_token(_payload_token(payload)):
        raise HTTPException(status_code=401, detail="Invalid Feishu token")

    event = payload.get("event")
    if not isinstance(event, dict):
        return {"ok": True, "ignored": True}

    sender = event.get("sender") or {}
    message = event.get("message") or {}
    if not isinstance(sender, dict) or not isinstance(message, dict):
        return {"ok": True, "ignored": True}

    sender_type = sender.get("sender_type")
    if isinstance(sender_type, str) and sender_type != "user":
        return {"ok": True, "ignored": True}

    if message.get("message_type") != "text":
        return {"ok": True, "ignored": True}

    sender_id = sender.get("sender_id") or {}
    if not isinstance(sender_id, dict):
        return {"ok": True, "ignored": True}

    open_id = sender_id.get("open_id")
    if not open_id:
        return {"ok": True, "ignored": True}

    content = message.get("content")
    if not isinstance(content, str):
        return {"ok": True, "ignored": True}

    text = extract_text_from_content(content)
    if text is None:
        return {"ok": True, "ignored": True}

    message_id = message.get("message_id")
    if isinstance(message_id, str) and _is_duplicate_message(message_id):
        return {"ok": True, "duplicate": True}

    user = get_or_create_user_from_feishu(
        db=db,
        open_id=open_id,
        user_id=sender_id.get("user_id"),
        chat_id=message.get("chat_id"),
        display_name=_display_name(sender_id),
    )

    query_result = handle_reminder_query(db=db, user_id=user.id, text=text)
    if query_result is not None:
        send_text_message(open_id, query_result["reply"])
        return {"ok": True}

    feedback = handle_reminder_feedback(db=db, user_id=user.id, text=text)
    if feedback is not None:
        send_text_message(open_id, feedback["reply"])
        return {"ok": True}

    response = handle_user_message(
        user_id=user.id,
        message=text,
        channel="feishu",
    )
    send_text_message(open_id, response.reply)
    return {"ok": True}


def _payload_token(payload: dict[str, Any]) -> str | None:
    header = payload.get("header") or {}
    if not isinstance(header, dict):
        header = {}
    return payload.get("token") or header.get("token")


def _display_name(sender_id: dict[str, Any]) -> str | None:
    for key in ("union_id", "user_id", "open_id"):
        value = sender_id.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _is_duplicate_message(message_id: str) -> bool:
    now = time.monotonic()
    expired_ids = [
        stored_message_id
        for stored_message_id, seen_at in _PROCESSED_MESSAGE_IDS.items()
        if now - seen_at > _MESSAGE_ID_TTL_SECONDS
    ]
    for stored_message_id in expired_ids:
        _PROCESSED_MESSAGE_IDS.pop(stored_message_id, None)

    if message_id in _PROCESSED_MESSAGE_IDS:
        return True
    _PROCESSED_MESSAGE_IDS[message_id] = now
    return False
