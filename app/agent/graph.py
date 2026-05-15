from __future__ import annotations

import ast
import json
import sqlite3
from collections.abc import Iterator
from functools import lru_cache
from typing import Any, Literal, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.review import (
    build_pending_action,
    build_review_prompt,
    needs_human_review,
    normalize_decision,
)
from app.agent.rules import fallback_tool_call, preferred_tool_name
from app.agent.state import MedicationAgentState
from app.agent.tools import MEDICATION_TOOLS, TOOL_FUNCTIONS
from app.config import get_settings
from app.schemas import ChatResponse, ToolCallSummary


class MissingOpenAIConfigError(RuntimeError):
    pass


class ChatModel(Protocol):
    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "ChatModel":
        ...

    def invoke(self, messages: list[BaseMessage]) -> BaseMessage:
        ...


def build_checkpointer() -> Any:
    settings = get_settings()

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ModuleNotFoundError:
        return InMemorySaver()

    connection = sqlite3.connect(settings.langgraph_checkpoint_db, check_same_thread=False)
    return SqliteSaver(connection)


def build_model() -> ChatModel:
    settings = get_settings()
    if not settings.openai_api_key:
        raise MissingOpenAIConfigError("OPENAI_API_KEY is not configured.")

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=settings.openai_api_key,
    )


def build_graph(model: ChatModel | None = None, checkpointer: Any | None = None):
    llm = model or build_model()

    def agent_node(state: MedicationAgentState) -> dict[str, Any]:
        system_message = SystemMessage(
            content=SYSTEM_PROMPT.format(user_id=state["user_id"])
        )
        latest_user_message = _latest_human_content(state["messages"])
        if _latest_turn_has_tool_message(state["messages"]):
            model_with_tools = llm.bind_tools(MEDICATION_TOOLS, tool_choice="none")
        else:
            tool_name = preferred_tool_name(state["user_id"], latest_user_message)
            if tool_name is None:
                model_with_tools = llm.bind_tools(MEDICATION_TOOLS, tool_choice="auto")
            else:
                model_with_tools = llm.bind_tools(
                    MEDICATION_TOOLS,
                    tool_choice=tool_name,
                )
        response = model_with_tools.invoke([system_message, *_messages_for_model(state["messages"])])
        final_reply = response.content if isinstance(response.content, str) else None
        return {
            "messages": [response],
            "final_reply": final_reply,
            "interrupted": False,
            "interrupt_reason": None,
            "review_decision": None,
        }

    def route_after_agent(state: MedicationAgentState) -> Literal["review_gate", "tools", "fallback", "__end__"]:
        last_message = state["messages"][-1]
        if not isinstance(last_message, AIMessage):
            return "__end__"
        if not last_message.tool_calls:
            if _latest_turn_has_tool_message(state["messages"]):
                return "__end__"
            latest_user_message = _latest_human_content(state["messages"])
            if fallback_tool_call(state["user_id"], latest_user_message) is not None:
                return "fallback"
            return "__end__"

        for tool_call in last_message.tool_calls:
            if needs_human_review(tool_call["name"], dict(tool_call.get("args") or {})):
                return "review_gate"
        return "tools"

    def fallback_node(state: MedicationAgentState) -> dict[str, Any]:
        latest_user_message = _latest_human_content(state["messages"])
        tool_call = fallback_tool_call(state["user_id"], latest_user_message)
        if tool_call is None:
            return {}
        return {
            "messages": [AIMessage(content="", tool_calls=[tool_call])],
            "final_reply": None,
        }

    def review_gate_node(state: MedicationAgentState) -> dict[str, Any]:
        last_message = state["messages"][-1]
        if not isinstance(last_message, AIMessage):
            return {}

        for tool_call in last_message.tool_calls:
            if needs_human_review(tool_call["name"], dict(tool_call.get("args") or {})):
                pending_action = build_pending_action(tool_call)
                prompt = build_review_prompt(pending_action)
                pending_result = {"pending": True}
                return {
                    "messages": [
                        ToolMessage(
                            content=json.dumps(pending_result, ensure_ascii=False),
                            tool_call_id=pending_action["tool_call_id"],
                        )
                    ],
                    "pending_action": pending_action,
                    "tool_calls": [
                        {
                            "name": pending_action["tool_name"],
                            "arguments": pending_action["arguments"],
                            "result": pending_result,
                        }
                    ],
                    "final_reply": prompt,
                    "interrupted": True,
                    "interrupt_reason": pending_action["review_reason"],
                }

        return {}

    def human_review_node(state: MedicationAgentState) -> dict[str, Any]:
        pending_action = state.get("pending_action")
        if not pending_action:
            return {
                "final_reply": "没有待确认的操作。",
                "interrupted": False,
                "interrupt_reason": None,
                "review_decision": None,
            }

        prompt = build_review_prompt(pending_action)
        decision = interrupt(
            {
                "prompt": prompt,
                "pending_action": pending_action,
                "expected_replies": ["确认", "取消"],
            }
        )
        if isinstance(decision, dict):
            decision_value = decision.get("decision") or decision.get("value")
        else:
            decision_value = decision
        normalized_decision = normalize_decision(str(decision_value or ""))

        if normalized_decision == "cancel":
            return {
                "pending_action": None,
                "tool_calls": [],
                "final_reply": "已取消，本次不会修改你的用药计划。",
                "interrupted": False,
                "interrupt_reason": None,
                "review_decision": None,
            }

        if normalized_decision != "confirm":
            return {
                "final_reply": prompt,
                "interrupted": True,
                "interrupt_reason": pending_action["review_reason"],
                "review_decision": None,
            }

        try:
            result = _execute_pending_action(pending_action)
        except ValueError as exc:
            return {
                "pending_action": None,
                "tool_calls": [
                    {
                        "name": pending_action["tool_name"],
                        "arguments": pending_action["arguments"],
                        "result": {"ok": False, "error": str(exc)},
                    }
                ],
                "final_reply": f"确认操作失败：{exc}",
                "interrupted": False,
                "interrupt_reason": None,
                "review_decision": None,
            }
        return {
            "pending_action": None,
            "tool_calls": [
                {
                    "name": pending_action["tool_name"],
                    "arguments": pending_action["arguments"],
                    "result": result,
                }
            ],
            "final_reply": _format_review_success(pending_action, result),
            "interrupted": False,
            "interrupt_reason": None,
            "review_decision": None,
        }

    graph = StateGraph(MedicationAgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("fallback", fallback_node)
    graph.add_node("tools", ToolNode(MEDICATION_TOOLS))
    graph.add_node("review_gate", review_gate_node)
    graph.add_node("human_review", human_review_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {
            "review_gate": "review_gate",
            "tools": "tools",
            "fallback": "fallback",
            "__end__": END,
        },
    )
    graph.add_conditional_edges(
        "fallback",
        route_after_agent,
        {
            "review_gate": "review_gate",
            "tools": "tools",
            "fallback": END,
            "__end__": END,
        },
    )
    graph.add_edge("review_gate", "human_review")
    graph.add_edge("human_review", END)
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer or build_checkpointer())


@lru_cache
def get_graph():
    return build_graph()


def run_agent_turn(
    user_id: int,
    user_message: str,
    channel: Literal["feishu", "cli"] = "feishu",
) -> ChatResponse:
    try:
        graph = get_graph()
    except MissingOpenAIConfigError:
        return ChatResponse(
            user_id=user_id,
            reply="当前未配置 OPENAI_API_KEY，无法启用用药 Agent。请配置后重试。",
            tool_calls=[],
            interrupted=False,
            interrupt_reason=None,
        )

    try:
        config = {"configurable": {"thread_id": f"user:{user_id}"}}
        decision = normalize_decision(user_message)

        if decision is not None:
            snapshot = graph.get_state(config)
            if not getattr(snapshot, "next", None):
                return ChatResponse(
                    user_id=user_id,
                    reply="没有待确认的操作。",
                    tool_calls=[],
                    interrupted=False,
                    interrupt_reason=None,
                )
            result = graph.invoke(Command(resume=decision), config=config)
            return _chat_response_from_result(
                user_id=user_id,
                result=result,
                user_message=user_message,
                prefer_state_tool_calls=True,
            )

        result = graph.invoke(_initial_state(user_id, user_message, channel), config=config)
        return _chat_response_from_result(
            user_id=user_id,
            result=result,
            user_message=user_message,
        )
    except Exception as exc:
        return ChatResponse(
            user_id=user_id,
            reply=f"Agent 执行失败：{type(exc).__name__}: {exc}",
            tool_calls=[],
            interrupted=False,
            interrupt_reason=None,
        )


def stream_agent_turn(
    user_id: int,
    user_message: str,
    channel: Literal["feishu", "cli"] = "cli",
) -> Iterator[str]:
    graph = get_graph()
    config = {"configurable": {"thread_id": f"user:{user_id}"}}
    decision = normalize_decision(user_message)

    if decision is not None:
        snapshot = graph.get_state(config)
        if not getattr(snapshot, "next", None):
            yield "没有待确认的操作。"
            return
        stream_input: Any = Command(resume=decision)
    else:
        stream_input = _initial_state(user_id, user_message, channel)

    seen_chunks: set[str] = set()
    for event in graph.stream(stream_input, config=config, stream_mode="values"):
        chunk = _stream_text_from_event(event)
        if chunk and chunk not in seen_chunks:
            seen_chunks.add(chunk)
            yield chunk


def _initial_state(
    user_id: int,
    user_message: str,
    channel: Literal["feishu", "cli"],
) -> MedicationAgentState:
    return {
        "user_id": user_id,
        "channel": channel,
        "messages": [HumanMessage(content=user_message)],
        "pending_action": None,
        "tool_calls": [],
        "final_reply": None,
        "interrupted": False,
        "interrupt_reason": None,
        "review_decision": None,
    }


def _chat_response_from_result(
    user_id: int,
    result: dict[str, Any],
    user_message: str,
    prefer_state_tool_calls: bool = False,
) -> ChatResponse:
    turn_messages = _messages_for_latest_turn(result.get("messages", []), user_message)
    state_tool_calls = _tool_calls_from_state(result.get("tool_calls") or [])
    if prefer_state_tool_calls:
        tool_calls = state_tool_calls
    else:
        tool_calls = state_tool_calls or _summarize_tool_calls(turn_messages)
    interrupted = bool(result.get("interrupted"))
    interrupt_reason = result.get("interrupt_reason")
    tool_reply = None if interrupted else _reply_from_tool_calls(tool_calls)
    reply = tool_reply or result.get("final_reply") or _final_reply(turn_messages, interrupted, interrupt_reason)

    return ChatResponse(
        user_id=user_id,
        reply=reply,
        tool_calls=tool_calls,
        interrupted=interrupted,
        interrupt_reason=interrupt_reason,
    )


def _messages_for_latest_turn(
    messages: list[BaseMessage],
    user_message: str,
) -> list[BaseMessage]:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, HumanMessage) and message.content == user_message:
            return messages[index + 1 :]
    return messages


def _messages_for_model(messages: list[BaseMessage]) -> list[BaseMessage]:
    repaired: list[BaseMessage] = []
    missing_tool_responses: list[ToolMessage] = []

    for message in messages:
        if missing_tool_responses and not isinstance(message, ToolMessage):
            repaired.extend(missing_tool_responses)
            missing_tool_responses = []

        repaired.append(message)

        if isinstance(message, AIMessage) and message.tool_calls:
            missing_tool_responses = [
                ToolMessage(
                    content=json.dumps({"pending": True}, ensure_ascii=False),
                    tool_call_id=tool_call["id"],
                )
                for tool_call in message.tool_calls
            ]
        elif isinstance(message, ToolMessage):
            missing_tool_responses = [
                tool_message
                for tool_message in missing_tool_responses
                if tool_message.tool_call_id != message.tool_call_id
            ]

    repaired.extend(missing_tool_responses)
    return repaired


def _latest_human_content(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage) and isinstance(message.content, str):
            return message.content
    return ""


def _latest_turn_has_tool_message(messages: list[BaseMessage]) -> bool:
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            return True
        if isinstance(message, HumanMessage):
            return False
    return False


def _summarize_tool_calls(messages: list[BaseMessage]) -> list[ToolCallSummary]:
    summaries: list[ToolCallSummary] = []
    by_id: dict[str, ToolCallSummary] = {}

    for message in messages:
        if isinstance(message, AIMessage):
            for tool_call in message.tool_calls:
                summary = ToolCallSummary(
                    name=tool_call["name"],
                    arguments=dict(tool_call.get("args") or {}),
                    result=None,
                )
                summaries.append(summary)
                by_id[tool_call["id"]] = summary
        elif isinstance(message, ToolMessage):
            summary = by_id.get(message.tool_call_id)
            if summary is not None:
                parsed = _parse_tool_result(message.content)
                summary.result = parsed if isinstance(parsed, dict) else {"value": parsed}

    return summaries


def _tool_calls_from_state(tool_calls: list[dict[str, Any]]) -> list[ToolCallSummary]:
    return [
        ToolCallSummary(
            name=tool_call["name"],
            arguments=dict(tool_call.get("arguments") or {}),
            result=tool_call.get("result"),
        )
        for tool_call in tool_calls
    ]


def _parse_tool_result(content: Any) -> Any:
    if not isinstance(content, str):
        return content

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    try:
        return ast.literal_eval(content)
    except (SyntaxError, ValueError):
        return {"raw": content}


def _review_status(tool_calls: list[ToolCallSummary]) -> tuple[bool, str | None]:
    for tool_call in tool_calls:
        result = tool_call.result or {}
        if result.get("requires_review") is True:
            return True, result.get("review_reason")
    return False, None


def _final_reply(
    messages: list[BaseMessage],
    interrupted: bool,
    interrupt_reason: str | None,
) -> str:
    if interrupted:
        return (
            "这个操作涉及用药计划的高风险变更，需要你确认后再继续。"
            f"原因：{interrupt_reason or '需要确认'}。请回复“确认”或“取消”。"
        )

    for message in reversed(messages):
        if isinstance(message, AIMessage) and isinstance(message.content, str) and message.content:
            return message.content

    return "已处理。"


def _reply_from_tool_calls(tool_calls: list[ToolCallSummary]) -> str | None:
    if not tool_calls:
        return None

    latest = tool_calls[-1]
    result = latest.result or {}
    if result.get("pending") is True or result.get("ok") is False:
        return None

    if latest.name == "list_medications":
        medications = result.get("value")
        if not medications:
            return "当前没有记录的用药计划。"
        lines = ["你当前记录的用药计划："]
        for medication in medications:
            times = "、".join(medication.get("times") or [])
            instructions = medication.get("instructions") or "无特殊说明"
            lines.append(
                f"- {medication.get('name')}：{medication.get('dose')}，{times}，{instructions}"
            )
        return "\n".join(lines)

    medication = result.get("medication")
    if isinstance(medication, dict):
        if latest.name == "add_medication":
            times = "、".join(medication.get("times") or [])
            instructions = medication.get("instructions") or "无特殊说明"
            return (
                f"已添加用药计划：{medication.get('name')}，"
                f"{medication.get('dose')}，{times}，{instructions}。"
            )
        if latest.name == "update_medication":
            return f"已更新用药计划：{medication.get('name')}。"
        if latest.name == "delete_medication":
            return f"已删除用药计划：{medication.get('name')}。"

    return None


def _execute_pending_action(pending_action: dict[str, Any]) -> dict[str, Any]:
    tool_name = pending_action["tool_name"]
    tool_function = TOOL_FUNCTIONS[tool_name]
    result = tool_function(**pending_action["arguments"])
    return result if isinstance(result, dict) else {"value": result}


def _format_review_success(pending_action: dict[str, Any], result: dict[str, Any]) -> str:
    reason = pending_action.get("review_reason")
    medication = result.get("medication") or {}

    if reason == "delete_medication":
        name = medication.get("name") or f"ID {pending_action['arguments'].get('medication_id')}"
        return f"已删除用药计划：{name}。"
    if reason == "dose_change":
        name = medication.get("name") or f"ID {pending_action['arguments'].get('medication_id')}"
        dose = medication.get("dose") or pending_action["arguments"].get("dose")
        return f"已确认并更新：{name} 的剂量现在是 {dose}。"
    if reason == "time_change":
        name = medication.get("name") or f"ID {pending_action['arguments'].get('medication_id')}"
        times = medication.get("times") or pending_action["arguments"].get("times")
        return f"已确认并更新：{name} 的提醒时间现在是 {times}。"
    return "已确认并完成操作。"


def _stream_text_from_event(event: dict[str, Any]) -> str | None:
    final_reply = event.get("final_reply")
    if isinstance(final_reply, str) and final_reply:
        return final_reply

    messages = event.get("messages") or []
    if messages:
        last_message = messages[-1]
        if isinstance(last_message, AIMessage) and isinstance(last_message.content, str):
            return last_message.content or None

    interrupts = event.get("__interrupt__")
    if interrupts:
        first_interrupt = interrupts[0]
        value = getattr(first_interrupt, "value", None)
        if isinstance(value, dict):
            prompt = value.get("prompt")
            if isinstance(prompt, str):
                return prompt
    return None
