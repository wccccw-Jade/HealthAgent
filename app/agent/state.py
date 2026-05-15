from __future__ import annotations

from typing import Annotated, Literal, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class MedicationAgentState(TypedDict):
    user_id: int
    channel: Literal["feishu", "cli"]
    messages: Annotated[list[BaseMessage], add_messages]
    pending_action: Optional[dict]
    tool_calls: list[dict]
    final_reply: Optional[str]
    interrupted: bool
    interrupt_reason: Optional[str]
    review_decision: Optional[Literal["confirm", "cancel"]]
