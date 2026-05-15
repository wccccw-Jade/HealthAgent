from fastapi.testclient import TestClient

from app.schemas import ChatResponse
from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_plain_reply(monkeypatch) -> None:
    def fake_generate_plain_reply(user_id: int, message: str, channel: str) -> ChatResponse:
        assert channel == "cli"
        return ChatResponse(
            user_id=user_id,
            reply=f"收到：{message}",
            tool_calls=[],
            interrupted=False,
            interrupt_reason=None,
        )

    monkeypatch.setattr("app.api.chat.generate_plain_reply", fake_generate_plain_reply)

    response = client.post(
        "/chat",
        json={
            "user_id": 1,
            "message": "我每天早上8点吃二甲双胍2片",
            "channel": "cli",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == 1
    assert data["reply"]
    assert data["tool_calls"] == []
    assert data["interrupted"] is False
    assert data["interrupt_reason"] is None


def test_chat_rejects_empty_message() -> None:
    response = client.post(
        "/chat",
        json={
            "user_id": 1,
            "message": "",
            "channel": "cli",
        },
    )

    assert response.status_code == 422


def test_chat_defaults_to_feishu_channel(monkeypatch) -> None:
    seen = {}

    def fake_generate_plain_reply(user_id: int, message: str, channel: str) -> ChatResponse:
        seen["channel"] = channel
        return ChatResponse(user_id=user_id, reply="ok")

    monkeypatch.setattr("app.api.chat.generate_plain_reply", fake_generate_plain_reply)

    response = client.post(
        "/chat",
        json={
            "user_id": 1,
            "message": "列一下我的药",
        },
    )

    assert response.status_code == 200
    assert seen["channel"] == "feishu"


def test_chat_rejects_unsupported_channel() -> None:
    response = client.post(
        "/chat",
        json={
            "user_id": 1,
            "message": "列一下我的药",
            "channel": "telegram",
        },
    )

    assert response.status_code == 422
