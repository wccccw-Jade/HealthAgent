from typing import Literal

from app.agent.graph import run_agent_turn
from app.schemas import ChatResponse


def handle_user_message(
    user_id: int,
    message: str,
    channel: Literal["feishu", "cli"] = "feishu",
) -> ChatResponse:
    return run_agent_turn(
        user_id=user_id,
        user_message=message,
        channel=channel,
    )


def generate_plain_reply(
    user_id: int,
    message: str,
    channel: Literal["feishu", "cli"] = "feishu",
) -> ChatResponse:
    return handle_user_message(
        user_id=user_id,
        message=message,
        channel=channel,
    )
