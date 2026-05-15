from __future__ import annotations

import re
from typing import Any

from app.agent.tools import list_medications

CHINESE_HOUR_PATTERN = re.compile(r"(早上|上午|中午|下午|晚上)?\s*(\d{1,2})\s*点")
DOSE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(片|粒|颗|mg|毫克|ml|毫升)")


def fallback_tool_call(user_id: int, message: str) -> dict[str, Any] | None:
    text = message.strip()
    if not text:
        return None

    if _is_list_request(text):
        return _tool_call("fallback_list", "list_medications", {"user_id": user_id})

    add_args = _parse_add_medication(user_id, text)
    if add_args is not None:
        return _tool_call("fallback_add", "add_medication", add_args)

    update_args = _parse_update_dose(user_id, text)
    if update_args is not None:
        return _tool_call("fallback_update_dose", "update_medication", update_args)

    delete_args = _parse_delete_medication(user_id, text)
    if delete_args is not None:
        return _tool_call("fallback_delete", "delete_medication", delete_args)

    return None


def preferred_tool_name(user_id: int, message: str) -> str | None:
    tool_call = fallback_tool_call(user_id=user_id, message=message)
    if tool_call is None:
        return None
    return tool_call["name"]


def _tool_call(call_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": call_id,
        "name": name,
        "args": args,
    }


def _is_list_request(text: str) -> bool:
    return any(keyword in text for keyword in ["列一下", "查询", "查看", "有哪些", "现在的药", "用药计划"])


def _parse_add_medication(user_id: int, text: str) -> dict[str, Any] | None:
    if not any(keyword in text for keyword in ["吃", "服用", "记录", "添加"]):
        return None

    name = _extract_medication_name(text)
    dose = _extract_dose(text)
    time = _extract_time(text)
    if name is None or dose is None or time is None:
        return None

    frequency = "daily" if any(keyword in text for keyword in ["每天", "每日", "天天"]) else "custom"
    instructions = _extract_instructions(text)

    return {
        "user_id": user_id,
        "name": name,
        "dose": dose,
        "frequency": frequency,
        "times": [time],
        "instructions": instructions,
    }


def _parse_update_dose(user_id: int, text: str) -> dict[str, Any] | None:
    if not any(keyword in text for keyword in ["改成", "改为", "调整为"]):
        return None

    name = _extract_known_medication_name(user_id, text)
    dose = _extract_dose(text)
    if name is None or dose is None:
        return None

    medication = _find_medication_by_name(user_id, name)
    if medication is None:
        return None

    return {
        "user_id": user_id,
        "medication_id": medication["id"],
        "dose": dose,
    }


def _parse_delete_medication(user_id: int, text: str) -> dict[str, Any] | None:
    if not any(keyword in text for keyword in ["删除", "删掉", "停用", "移除"]):
        return None

    name = _extract_known_medication_name(user_id, text)
    if name is None:
        return None

    medication = _find_medication_by_name(user_id, name)
    if medication is None:
        return None

    return {
        "user_id": user_id,
        "medication_id": medication["id"],
    }


def _extract_medication_name(text: str) -> str | None:
    match = re.search(r"吃\s*([^，,。.\s]+)", text)
    if match:
        return _clean_medication_name(match.group(1))

    match = re.search(r"(?:记录|添加)\s*([^，,。.\s]+)", text)
    if match:
        candidate = match.group(1).strip()
        if candidate not in {"一个", "一下"}:
            return _clean_medication_name(candidate)
    return None


def _clean_medication_name(candidate: str) -> str | None:
    cleaned = DOSE_PATTERN.sub("", candidate).strip()
    return cleaned or None


def _extract_known_medication_name(user_id: int, text: str) -> str | None:
    medications = list_medications(user_id=user_id)
    for medication in medications:
        name = medication["name"]
        if name in text:
            return name
    return _extract_medication_name(text)


def _find_medication_by_name(user_id: int, name: str) -> dict[str, Any] | None:
    medications = list_medications(user_id=user_id)
    for medication in medications:
        if medication["name"] == name:
            return medication
    return None


def _extract_dose(text: str) -> str | None:
    match = DOSE_PATTERN.search(text)
    if not match:
        return None
    value, unit = match.groups()
    return f"{value} {unit}"


def _extract_time(text: str) -> str | None:
    match = CHINESE_HOUR_PATTERN.search(text)
    if not match:
        return None

    period, hour_text = match.groups()
    hour = int(hour_text)
    if period in {"下午", "晚上"} and hour < 12:
        hour += 12
    if period == "中午" and hour < 11:
        hour += 12
    if hour > 23:
        return None
    return f"{hour:02d}:00"


def _extract_instructions(text: str) -> str | None:
    instructions = []
    for keyword in ["饭后", "饭前", "睡前", "空腹"]:
        if keyword in text:
            instructions.append(keyword)
    return "，".join(instructions) if instructions else None
