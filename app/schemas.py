from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ToolCallSummary(BaseModel):
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None


class ChatRequest(BaseModel):
    user_id: int
    message: str = Field(min_length=1)
    channel: Literal["feishu", "cli"] = "feishu"


class ChatResponse(BaseModel):
    user_id: int
    reply: str
    tool_calls: List[ToolCallSummary] = Field(default_factory=list)
    interrupted: bool = False
    interrupt_reason: Optional[str] = None
