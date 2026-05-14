from app.schemas import ChatResponse


def generate_plain_reply(user_id: int, message: str) -> ChatResponse:
    reply = (
        "我已经收到你的消息。当前版本还没有启用用药工具调用，"
        "但后续会支持记录、查询、修改和删除用药提醒。"
    )

    return ChatResponse(
        user_id=user_id,
        reply=reply,
        tool_calls=[],
        interrupted=False,
        interrupt_reason=None,
    )
