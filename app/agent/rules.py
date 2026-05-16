from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from app.agent.tools import list_medications

CLOCK_TIME_PATTERN = re.compile(r"([01]?\d|2[0-3])[:：]([0-5]\d)")
CHINESE_HOUR_PATTERN = re.compile(r"(早上|上午|中午|下午|晚上)?\s*(\d{1,2}|[一二两三四五六七八九十]+)\s*点")
DOSE_PATTERN = re.compile(r"(\d+(?:\.\d+)?|[一二两三四五六七八九十]+)\s*(片|粒|颗|mg|毫克|ml|毫升)")
DAYS_PATTERN = re.compile(r"(?:连续|用药|吃|服用)?\s*(\d+|[一二两三四五六七八九十]+)\s*天")


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
    medication_days = _extract_medication_days(text)
    start_date = _extract_start_date(text)
    if medication_days is None and start_date is not None:
        medication_days = 1
    if name is None or dose is None or time is None or medication_days is None:
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
        "medication_days": medication_days,
        "start_date": start_date,
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
    if not value.replace(".", "", 1).isdigit():
        parsed_value = _chinese_number_to_int(value)
        if parsed_value is None:
            return None
        value = str(parsed_value)
    return f"{value} {unit}"


def _extract_time(text: str) -> str | None:
    clock_match = CLOCK_TIME_PATTERN.search(text)
    if clock_match:
        hour, minute = clock_match.groups()
        return f"{int(hour):02d}:{minute}"

    match = CHINESE_HOUR_PATTERN.search(text)
    if not match:
        return None

    period, hour_text = match.groups()
    hour = int(hour_text) if hour_text.isdigit() else int(_chinese_number_to_int(hour_text) or -1)
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


def _extract_medication_days(text: str) -> int | None:
    match = DAYS_PATTERN.search(text)
    if not match:
        return None
    value = match.group(1)
    if value.isdigit():
        return int(value)
    return _chinese_number_to_int(value)


def _chinese_number_to_int(value: str) -> int | None:
    digits = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if value == "十":
        return 10
    if value.startswith("十"):
        tail = value[1:]
        return 10 + digits.get(tail, 0)
    if value.endswith("十"):
        head = value[:-1]
        return digits.get(head, 0) * 10
    if "十" in value:
        head, tail = value.split("十", 1)
        return digits.get(head, 0) * 10 + digits.get(tail, 0)
    return digits.get(value)


def _extract_start_date(text: str) -> date | None:
    today = date.today()
    if "后天" in text:
        return today + timedelta(days=2)
    if "明天" in text or "明日" in text:
        return today + timedelta(days=1)
    if "今天" in text or "今日" in text:
        return today
    return None
