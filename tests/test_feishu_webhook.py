from __future__ import annotations

import base64
import hashlib
import json

from fastapi.testclient import TestClient

from app.database import get_db
from app.api import feishu as feishu_api
from app.main import app
from app.models import User
from app.schemas import ChatResponse
from app.services import feishu as feishu_service

client = TestClient(app)


class FakeSettings:
    feishu_verification_token = "test-token"
    feishu_app_id = "cli_test"
    feishu_app_secret = "secret"
    feishu_encrypt_key = "encrypt-key"


def _override_db(db_session):
    def override():
        yield db_session

    app.dependency_overrides[get_db] = override


def _payload(text: str = "列一下我的药", message_id: str = "om_test") -> dict:
    return {
        "schema": "2.0",
        "header": {
            "event_type": "im.message.receive_v1",
            "token": "test-token",
        },
        "event": {
            "sender": {
                "sender_id": {
                    "open_id": "ou_test",
                    "user_id": "user_test",
                }
            },
            "message": {
                "message_id": message_id,
                "chat_id": "oc_test",
                "chat_type": "p2p",
                "message_type": "text",
                "content": f'{{"text":"{text}"}}',
            },
        },
    }


def setup_function() -> None:
    app.dependency_overrides.clear()
    feishu_api._PROCESSED_MESSAGE_IDS.clear()


def teardown_function() -> None:
    app.dependency_overrides.clear()
    feishu_api._PROCESSED_MESSAGE_IDS.clear()


def test_url_verification_returns_challenge(monkeypatch) -> None:
    monkeypatch.setattr(feishu_service, "get_settings", lambda: FakeSettings())

    response = client.post(
        "/feishu/webhook",
        json={
            "challenge": "challenge-value",
            "token": "test-token",
            "type": "url_verification",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge-value"}


def test_encrypted_url_verification_returns_challenge(monkeypatch) -> None:
    monkeypatch.setattr(feishu_service, "get_settings", lambda: FakeSettings())
    encrypted_payload = _encrypt_payload(
        {
            "challenge": "challenge-value",
            "token": "test-token",
            "type": "url_verification",
        }
    )

    response = client.post(
        "/feishu/webhook",
        json={"encrypt": encrypted_payload},
    )

    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge-value"}


def test_invalid_encrypted_url_verification_returns_json_error(monkeypatch) -> None:
    monkeypatch.setattr(feishu_service, "get_settings", lambda: FakeSettings())

    response = client.post(
        "/feishu/webhook",
        json={"encrypt": "invalid-encrypted-value"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Failed to decrypt Feishu encrypted payload"}


def test_url_verification_rejects_invalid_token(monkeypatch) -> None:
    monkeypatch.setattr(feishu_service, "get_settings", lambda: FakeSettings())

    response = client.post(
        "/feishu/webhook",
        json={
            "challenge": "challenge-value",
            "token": "wrong-token",
            "type": "url_verification",
        },
    )

    assert response.status_code == 401


def test_non_text_message_is_ignored(monkeypatch, db_session) -> None:
    _override_db(db_session)
    monkeypatch.setattr(feishu_service, "get_settings", lambda: FakeSettings())
    sent_messages = []

    monkeypatch.setattr("app.api.feishu.send_text_message", lambda *args, **kwargs: sent_messages.append(args))

    payload = _payload()
    payload["event"]["message"]["message_type"] = "image"

    response = client.post("/feishu/webhook", json=payload)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "ignored": True}
    assert sent_messages == []
    assert db_session.query(User).count() == 0


def test_bot_sender_message_is_ignored(monkeypatch, db_session) -> None:
    _override_db(db_session)
    monkeypatch.setattr(feishu_service, "get_settings", lambda: FakeSettings())
    sent_messages = []

    monkeypatch.setattr("app.api.feishu.send_text_message", lambda *args, **kwargs: sent_messages.append(args))

    payload = _payload("已添加用药计划：二甲双胍，1 片，08:00，饭后。")
    payload["event"]["sender"]["sender_type"] = "app"

    response = client.post("/feishu/webhook", json=payload)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "ignored": True}
    assert sent_messages == []
    assert db_session.query(User).count() == 0


def test_text_message_binds_user_and_sends_agent_reply(monkeypatch, db_session) -> None:
    _override_db(db_session)
    monkeypatch.setattr(feishu_service, "get_settings", lambda: FakeSettings())
    seen = {}
    sent_messages = []

    def fake_handle_user_message(user_id: int, message: str, channel: str) -> ChatResponse:
        seen["user_id"] = user_id
        seen["message"] = message
        seen["channel"] = channel
        return ChatResponse(user_id=user_id, reply="测试回复")

    def fake_send_text_message(receive_id: str, text: str, receive_id_type: str = "open_id") -> dict:
        sent_messages.append((receive_id, text, receive_id_type))
        return {"code": 0}

    monkeypatch.setattr("app.api.feishu.handle_user_message", fake_handle_user_message)
    monkeypatch.setattr("app.api.feishu.send_text_message", fake_send_text_message)

    response = client.post("/feishu/webhook", json=_payload())

    assert response.status_code == 200
    assert response.json() == {"ok": True}

    user = db_session.query(User).one()
    assert user.feishu_open_id == "ou_test"
    assert user.feishu_user_id == "user_test"
    assert user.feishu_chat_id == "oc_test"

    assert seen == {
        "user_id": user.id,
        "message": "列一下我的药",
        "channel": "feishu",
    }
    assert sent_messages == [("ou_test", "测试回复", "open_id")]


def test_duplicate_message_id_is_processed_once(monkeypatch, db_session) -> None:
    _override_db(db_session)
    monkeypatch.setattr(feishu_service, "get_settings", lambda: FakeSettings())
    seen = []
    sent_messages = []

    def fake_handle_user_message(user_id: int, message: str, channel: str) -> ChatResponse:
        seen.append((user_id, message, channel))
        return ChatResponse(user_id=user_id, reply="测试回复")

    monkeypatch.setattr("app.api.feishu.handle_user_message", fake_handle_user_message)
    monkeypatch.setattr(
        "app.api.feishu.send_text_message",
        lambda receive_id, text, receive_id_type="open_id": sent_messages.append((receive_id, text, receive_id_type)),
    )

    payload = _payload("我接下来要吃3天布洛芬，每天一粒，一天一次，15:30的时候提醒我")
    first = client.post("/feishu/webhook", json=payload)
    second = client.post("/feishu/webhook", json=payload)

    assert first.status_code == 200
    assert first.json() == {"ok": True}
    assert second.status_code == 200
    assert second.json() == {"ok": True, "duplicate": True}
    assert len(seen) == 1
    assert sent_messages == [("ou_test", "测试回复", "open_id")]


def test_confirm_and_cancel_route_to_conversation_service(monkeypatch, db_session) -> None:
    _override_db(db_session)
    monkeypatch.setattr(feishu_service, "get_settings", lambda: FakeSettings())
    messages = []

    def fake_handle_user_message(user_id: int, message: str, channel: str) -> ChatResponse:
        messages.append((message, channel))
        return ChatResponse(user_id=user_id, reply=f"收到：{message}")

    monkeypatch.setattr("app.api.feishu.handle_user_message", fake_handle_user_message)
    monkeypatch.setattr("app.api.feishu.send_text_message", lambda *args, **kwargs: {"code": 0})

    confirm_response = client.post("/feishu/webhook", json=_payload("确认", message_id="om_confirm"))
    cancel_response = client.post("/feishu/webhook", json=_payload("取消", message_id="om_cancel"))

    assert confirm_response.status_code == 200
    assert cancel_response.status_code == 200
    assert messages == [("确认", "feishu"), ("取消", "feishu")]


def test_reminder_feedback_sends_reply_without_agent(monkeypatch, db_session) -> None:
    _override_db(db_session)
    monkeypatch.setattr(feishu_service, "get_settings", lambda: FakeSettings())
    agent_calls = []
    sent_messages = []

    monkeypatch.setattr(
        "app.api.feishu.handle_reminder_feedback",
        lambda db, user_id, text: {"ok": True, "reply": "已记录。"},
    )
    monkeypatch.setattr(
        "app.api.feishu.handle_user_message",
        lambda *args, **kwargs: agent_calls.append(args),
    )
    monkeypatch.setattr(
        "app.api.feishu.send_text_message",
        lambda receive_id, text, receive_id_type="open_id": sent_messages.append((receive_id, text, receive_id_type)),
    )

    response = client.post("/feishu/webhook", json=_payload("已吃"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert agent_calls == []
    assert sent_messages == [("ou_test", "已记录。", "open_id")]


def test_reminder_query_sends_reply_without_agent(monkeypatch, db_session) -> None:
    _override_db(db_session)
    monkeypatch.setattr(feishu_service, "get_settings", lambda: FakeSettings())
    agent_calls = []
    sent_messages = []

    monkeypatch.setattr(
        "app.api.feishu.handle_reminder_query",
        lambda db, user_id, text: {"ok": True, "reply": "你当前有以下待确认提醒：\n1. 布洛芬，1 粒，15:30"},
    )
    monkeypatch.setattr(
        "app.api.feishu.handle_reminder_feedback",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("feedback should not run")),
    )
    monkeypatch.setattr(
        "app.api.feishu.handle_user_message",
        lambda *args, **kwargs: agent_calls.append(args),
    )
    monkeypatch.setattr(
        "app.api.feishu.send_text_message",
        lambda receive_id, text, receive_id_type="open_id": sent_messages.append((receive_id, text, receive_id_type)),
    )

    response = client.post("/feishu/webhook", json=_payload("看一下待确认"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert agent_calls == []
    assert sent_messages == [("ou_test", "你当前有以下待确认提醒：\n1. 布洛芬，1 粒，15:30", "open_id")]


def test_non_reminder_text_still_routes_to_agent(monkeypatch, db_session) -> None:
    _override_db(db_session)
    monkeypatch.setattr(feishu_service, "get_settings", lambda: FakeSettings())
    messages = []

    def fake_handle_user_message(user_id: int, message: str, channel: str) -> ChatResponse:
        messages.append((message, channel))
        return ChatResponse(user_id=user_id, reply="agent reply")

    monkeypatch.setattr("app.api.feishu.handle_reminder_feedback", lambda db, user_id, text: None)
    monkeypatch.setattr("app.api.feishu.handle_user_message", fake_handle_user_message)
    monkeypatch.setattr("app.api.feishu.send_text_message", lambda *args, **kwargs: {"code": 0})

    response = client.post("/feishu/webhook", json=_payload("列一下我的药"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert messages == [("列一下我的药", "feishu")]


def _encrypt_payload(payload: dict) -> str:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7

    key = hashlib.sha256(FakeSettings.feishu_encrypt_key.encode("utf-8")).digest()
    iv = b"0123456789abcdef"
    payload_bytes = json.dumps(payload).encode("utf-8")
    padder = PKCS7(128).padder()
    padded_payload = padder.update(payload_bytes) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    encrypted_payload = encryptor.update(padded_payload) + encryptor.finalize()
    return base64.b64encode(iv + encrypted_payload).decode("utf-8")
