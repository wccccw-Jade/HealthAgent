from __future__ import annotations

import httpx
import pytest

from app.services import feishu as feishu_service


class FakeSettings:
    feishu_verification_token = "test-token"
    feishu_app_id = "cli_test"
    feishu_app_secret = "secret"
    feishu_encrypt_key = "encrypt-key"


class FakeResponse:
    def __init__(self, data: dict, status_error: Exception | None = None) -> None:
        self._data = data
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error

    def json(self) -> dict:
        return self._data


def setup_function() -> None:
    feishu_service._TOKEN_CACHE["token"] = None
    feishu_service._TOKEN_CACHE["expires_at"] = 0.0


def teardown_function() -> None:
    feishu_service._TOKEN_CACHE["token"] = None
    feishu_service._TOKEN_CACHE["expires_at"] = 0.0


def test_post_with_retry_succeeds_after_transient_error(monkeypatch) -> None:
    calls = []

    def fake_post(url: str, **kwargs):
        calls.append((url, kwargs))
        if len(calls) == 1:
            raise httpx.TransportError("temporary failure")
        return FakeResponse({"code": 0})

    monkeypatch.setattr(feishu_service.httpx, "post", fake_post)
    monkeypatch.setattr(feishu_service.time, "sleep", lambda seconds: None)

    response = feishu_service._post_with_retry("https://example.test", attempts=2)

    assert response.json() == {"code": 0}
    assert len(calls) == 2


def test_post_with_retry_raises_after_repeated_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        feishu_service.httpx,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.TransportError("down")),
    )
    monkeypatch.setattr(feishu_service.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="Feishu request failed after 2 attempts"):
        feishu_service._post_with_retry("https://example.test", attempts=2)


def test_send_text_message_raises_on_feishu_business_error(monkeypatch) -> None:
    monkeypatch.setattr(feishu_service, "get_settings", lambda: FakeSettings())
    responses = [
        FakeResponse({"code": 0, "tenant_access_token": "tenant-token", "expire": 7200}),
        FakeResponse({"code": 999, "msg": "bad request"}),
    ]

    def fake_post_with_retry(*args, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(feishu_service, "_post_with_retry", fake_post_with_retry)

    with pytest.raises(RuntimeError, match="bad request"):
        feishu_service.send_text_message("ou_test", "hello")

    assert responses == []
