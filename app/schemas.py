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


class FeishuEventSender(BaseModel):
    sender_id: Dict[str, Any] = Field(default_factory=dict)
    sender_type: Optional[str] = None
    tenant_key: Optional[str] = None


class FeishuEventMessage(BaseModel):
    message_id: str
    root_id: Optional[str] = None
    parent_id: Optional[str] = None
    create_time: Optional[str] = None
    chat_id: Optional[str] = None
    chat_type: Optional[str] = None
    message_type: str
    content: str


class FeishuMessageEvent(BaseModel):
    sender: FeishuEventSender
    message: FeishuEventMessage


class FeishuEventCallback(BaseModel):
    schema_: Optional[str] = Field(default=None, alias="schema")
    header: Optional[Dict[str, Any]] = None
    event: Optional[FeishuMessageEvent] = None
    challenge: Optional[str] = None
    token: Optional[str] = None
    type: Optional[str] = None
