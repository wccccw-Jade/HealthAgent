from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_plain_reply() -> None:
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
