from app.schemas import ChatResponse
from app.agent.graph import run_agent_turn


def generate_plain_reply(
    user_id: int,
    message: str,
    channel: str = "feishu",
) -> ChatResponse:
    return run_agent_turn(
        user_id=user_id,
        user_message=message,
        channel=channel,
    )
