from __future__ import annotations

from typing import Any


CONFIRM_WORDS = {"确认", "确定", "yes", "y", "ok", "confirm"}
CANCEL_WORDS = {"取消", "不用了", "算了", "no", "n", "cancel"}


def normalize_decision(message: str) -> str | None:
    text = message.strip().lower()
    if text in CONFIRM_WORDS:
        return "confirm"
    if text in CANCEL_WORDS:
        return "cancel"
    return None


def needs_human_review(tool_name: str, args: dict[str, Any]) -> bool:
    if tool_name == "delete_medication":
        return True
    if tool_name == "update_medication" and args.get("dose") is not None:
        return True
    if tool_name == "update_medication" and args.get("times") is not None:
        return True
    return False


def review_reason_for(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name == "delete_medication":
        return "delete_medication"
    if tool_name == "update_medication" and args.get("dose") is not None:
        return "dose_change"
    if tool_name == "update_medication" and args.get("times") is not None:
        return "time_change"
    return "human_review"


def build_pending_action(tool_call: dict[str, Any]) -> dict[str, Any]:
    args = dict(tool_call.get("args") or {})
    tool_name = tool_call["name"]
    return {
        "tool_call_id": tool_call.get("id"),
        "tool_name": tool_name,
        "arguments": args,
        "review_reason": review_reason_for(tool_name, args),
    }


def build_review_prompt(pending_action: dict[str, Any]) -> str:
    reason = pending_action["review_reason"]
    args = pending_action["arguments"]
    medication_id = args.get("medication_id")

    if reason == "delete_medication":
        return (
            f"这个操作会删除用药计划 ID {medication_id}。"
            "请回复“确认”执行，或回复“取消”放弃。"
        )
    if reason == "dose_change":
        return (
            f"这个操作会把用药计划 ID {medication_id} 的剂量改为 {args.get('dose')}。"
            "如果这不是医生或药师建议的调整，请先咨询专业人员。"
            "请回复“确认”执行，或回复“取消”放弃。"
        )
    if reason == "time_change":
        return (
            f"这个操作会修改用药计划 ID {medication_id} 的提醒时间。"
            "请回复“确认”执行，或回复“取消”放弃。"
        )
    return "这个操作需要确认。请回复“确认”执行，或回复“取消”放弃。"
