from __future__ import annotations

import base64
import hashlib
import json
import time
from binascii import Error as Base64Error
from json import JSONDecodeError
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User

_TOKEN_CACHE: dict[str, Any] = {
    "token": None,
    "expires_at": 0.0,
}


def verify_feishu_token(payload_token: str | None) -> bool:
    expected = get_settings().feishu_verification_token
    if not expected:
        return True
    return payload_token == expected


def extract_text_from_content(content: str) -> str | None:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None

    text = data.get("text")
    if not isinstance(text, str):
        return None

    stripped = text.strip()
    return stripped or None


def decrypt_feishu_payload(encrypted_payload: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.feishu_encrypt_key:
        raise RuntimeError("FEISHU_ENCRYPT_KEY is required for encrypted Feishu events")

    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
    except ImportError as exc:
        raise RuntimeError("cryptography is required for encrypted Feishu events") from exc

    key = hashlib.sha256(settings.feishu_encrypt_key.encode("utf-8")).digest()
    try:
        encrypted_data = base64.b64decode(encrypted_payload)
        iv = encrypted_data[:16]
        ciphertext = encrypted_data[16:]
        if len(iv) != 16 or not ciphertext:
            raise ValueError("Encrypted Feishu payload is missing iv or ciphertext")

        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded_data = decryptor.update(ciphertext) + decryptor.finalize()

        unpadder = PKCS7(128).unpadder()
        plaintext = unpadder.update(padded_data) + unpadder.finalize()
        data = json.loads(plaintext.decode("utf-8"))
    except (Base64Error, UnicodeDecodeError, ValueError, JSONDecodeError) as exc:
        raise RuntimeError("Failed to decrypt Feishu encrypted payload") from exc

    if not isinstance(data, dict):
        raise RuntimeError("Encrypted Feishu payload did not decode to an object")
    return data


def get_tenant_access_token() -> str:
    cached_token = _TOKEN_CACHE.get("token")
    if cached_token and float(_TOKEN_CACHE.get("expires_at") or 0) > time.time():
        return str(cached_token)

    settings = get_settings()
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise RuntimeError("FEISHU_APP_ID and FEISHU_APP_SECRET are required")

    response = httpx.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={
            "app_id": settings.feishu_app_id,
            "app_secret": settings.feishu_app_secret,
        },
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("code") not in (0, None):
        raise RuntimeError(data.get("msg") or "Failed to get Feishu tenant access token")

    token = data.get("tenant_access_token")
    if not token:
        raise RuntimeError("Feishu response did not include tenant_access_token")

    expire_seconds = int(data.get("expire") or 7200)
    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expires_at"] = time.time() + max(expire_seconds - 60, 0)
    return str(token)


def send_text_message(
    receive_id: str,
    text: str,
    receive_id_type: str = "open_id",
) -> dict[str, Any]:
    token = get_tenant_access_token()
    response = httpx.post(
        "https://open.feishu.cn/open-apis/im/v1/messages",
        params={"receive_id_type": receive_id_type},
        headers={"Authorization": f"Bearer {token}"},
        json={
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        },
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("code") not in (0, None):
        raise RuntimeError(data.get("msg") or "Failed to send Feishu message")
    return data


def get_or_create_user_from_feishu(
    db: Session,
    open_id: str,
    user_id: str | None = None,
    chat_id: str | None = None,
    display_name: str | None = None,
) -> User:
    user = (
        db.query(User)
        .filter(User.feishu_open_id == open_id)
        .one_or_none()
    )
    if user is None and user_id:
        user = (
            db.query(User)
            .filter(User.feishu_user_id == user_id)
            .one_or_none()
        )

    if user is None:
        user = User(
            feishu_open_id=open_id,
            feishu_user_id=user_id,
            feishu_chat_id=chat_id,
            display_name=display_name,
        )
        db.add(user)
    else:
        user.feishu_open_id = open_id
        if user_id:
            user.feishu_user_id = user_id
        if chat_id:
            user.feishu_chat_id = chat_id
        if display_name:
            user.display_name = display_name

    db.commit()
    db.refresh(user)
    return user
