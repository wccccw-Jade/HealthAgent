from __future__ import annotations

from collections.abc import Iterable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent import graph as graph_module
from app.agent import tools
from app.agent.graph import build_graph, run_agent_turn, stream_agent_turn
from app.services.medication import add_medication


class FakeModel:
    def __init__(self, responses: Iterable[BaseMessage]) -> None:
        self.responses = iter(responses)
        self.messages: list[list[BaseMessage]] = []
        self.bind_kwargs: list[dict] = []

    def bind_tools(self, tool_list, **kwargs):
        self.tool_list = tool_list
        self.bind_kwargs.append(kwargs)
        return self

    def invoke(self, messages: list[BaseMessage]) -> BaseMessage:
        self.messages.append(messages)
        return next(self.responses)


class RecordingGraph:
    def __init__(self) -> None:
        self.config = None

    def invoke(self, state, config):
        self.config = config
        return {
            "messages": [
                *state["messages"],
                AIMessage(content="ok"),
            ]
        }


class StreamingGraph:
    def stream(self, state, config, stream_mode):
        assert config == {"configurable": {"thread_id": "user:7"}}
        assert stream_mode == "values"
        yield {"final_reply": "第一段"}
        yield {"final_reply": "第二段"}


def test_run_agent_turn_uses_user_thread_id(monkeypatch) -> None:
    recording_graph = RecordingGraph()
    monkeypatch.setattr(graph_module, "get_graph", lambda: recording_graph)

    response = run_agent_turn(user_id=42, user_message="hello", channel="cli")

    assert response.reply == "ok"
    assert recording_graph.config == {"configurable": {"thread_id": "user:42"}}


def test_graph_lists_medications_with_tool_summary(monkeypatch, test_session_factory) -> None:
    monkeypatch.setattr(tools, "SessionLocal", test_session_factory)
    with test_session_factory() as db:
        add_medication(
            db=db,
            user_id=1,
            name="二甲双胍",
            dose="2 片",
            frequency="daily",
            times=["08:00"],
            instructions="饭后",
        )

    fake_model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_list",
                        "name": "list_medications",
                        "args": {"user_id": 1},
                    }
                ],
            ),
            AIMessage(content="你现在有：二甲双胍，2 片，08:00，饭后。"),
        ]
    )
    compiled = build_graph(model=fake_model, checkpointer=InMemorySaver())
    monkeypatch.setattr(graph_module, "get_graph", lambda: compiled)

    response = run_agent_turn(user_id=1, user_message="列一下我的药", channel="cli")

    assert "二甲双胍" in response.reply
    assert "08:00" in response.reply
    assert response.interrupted is False
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "list_medications"
    assert response.tool_calls[0].arguments == {"user_id": 1}
    assert response.tool_calls[0].result is not None
    assert response.tool_calls[0].result["value"][0]["name"] == "二甲双胍"


def test_fallback_adds_medication_when_model_does_not_call_tool(monkeypatch, test_session_factory) -> None:
    monkeypatch.setattr(tools, "SessionLocal", test_session_factory)
    fake_model = FakeModel(
        [
            AIMessage(content="我先帮你记录。"),
            AIMessage(content="已添加二甲双胍。"),
        ]
    )
    compiled = build_graph(model=fake_model, checkpointer=InMemorySaver())
    monkeypatch.setattr(graph_module, "get_graph", lambda: compiled)

    response = run_agent_turn(
        user_id=1,
        user_message="我每天早上8点吃二甲双胍2片，饭后",
        channel="cli",
    )

    assert response.interrupted is False
    assert fake_model.bind_kwargs[0]["tool_choice"] == "add_medication"
    assert response.tool_calls[0].name == "add_medication"
    assert response.tool_calls[0].result is not None
    assert response.tool_calls[0].result["medication"]["name"] == "二甲双胍"

    medications = tools.list_medications(user_id=1)
    assert medications[0]["times"] == ["08:00"]
    assert medications[0]["dose"] == "2 片"


def test_fallback_lists_medications_when_model_does_not_call_tool(monkeypatch, test_session_factory) -> None:
    monkeypatch.setattr(tools, "SessionLocal", test_session_factory)
    with test_session_factory() as db:
        add_medication(
            db=db,
            user_id=1,
            name="二甲双胍",
            dose="2 片",
            frequency="daily",
            times=["08:00"],
        )

    fake_model = FakeModel(
        [
            AIMessage(content="我来查一下。"),
            AIMessage(content="你现在有二甲双胍。"),
        ]
    )
    compiled = build_graph(model=fake_model, checkpointer=InMemorySaver())
    monkeypatch.setattr(graph_module, "get_graph", lambda: compiled)

    response = run_agent_turn(user_id=1, user_message="列一下我现在的药", channel="cli")

    assert fake_model.bind_kwargs[0]["tool_choice"] == "list_medications"
    assert response.tool_calls[0].name == "list_medications"
    assert response.tool_calls[0].result is not None
    assert response.tool_calls[0].result["value"][0]["name"] == "二甲双胍"


def test_dose_update_sets_interrupted(monkeypatch, test_session_factory) -> None:
    monkeypatch.setattr(tools, "SessionLocal", test_session_factory)
    with test_session_factory() as db:
        created = add_medication(
            db=db,
            user_id=1,
            name="二甲双胍",
            dose="1 片",
            frequency="daily",
            times=["08:00"],
        )
    medication_id = created["medication"]["id"]

    fake_model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_update",
                        "name": "update_medication",
                        "args": {
                            "user_id": 1,
                            "medication_id": medication_id,
                            "dose": "2 片",
                        },
                    }
                ],
            ),
            AIMessage(content="需要确认剂量变更。"),
        ]
    )
    compiled = build_graph(model=fake_model, checkpointer=InMemorySaver())
    monkeypatch.setattr(graph_module, "get_graph", lambda: compiled)

    response = run_agent_turn(user_id=1, user_message="把二甲双胍改成2片", channel="cli")

    assert response.interrupted is True
    assert response.interrupt_reason == "dose_change"
    assert "确认" in response.reply
    assert response.tool_calls[0].result == {"pending": True}

    medications = tools.list_medications(user_id=1)
    assert medications[0]["dose"] == "1 片"


def test_time_update_sets_interrupted_without_persisting(monkeypatch, test_session_factory) -> None:
    monkeypatch.setattr(tools, "SessionLocal", test_session_factory)
    with test_session_factory() as db:
        created = add_medication(
            db=db,
            user_id=1,
            name="二甲双胍",
            dose="2 片",
            frequency="daily",
            times=["08:00"],
        )
    medication_id = created["medication"]["id"]

    fake_model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_update_time",
                        "name": "update_medication",
                        "args": {
                            "user_id": 1,
                            "medication_id": medication_id,
                            "times": ["09:00"],
                        },
                    }
                ],
            ),
        ]
    )
    compiled = build_graph(model=fake_model, checkpointer=InMemorySaver())
    monkeypatch.setattr(graph_module, "get_graph", lambda: compiled)

    response = run_agent_turn(user_id=1, user_message="把二甲双胍改到9点提醒", channel="cli")

    assert response.interrupted is True
    assert response.interrupt_reason == "time_change"

    medications = tools.list_medications(user_id=1)
    assert medications[0]["times"] == ["08:00"]


def test_delete_sets_interrupted(monkeypatch, test_session_factory) -> None:
    monkeypatch.setattr(tools, "SessionLocal", test_session_factory)
    with test_session_factory() as db:
        created = add_medication(
            db=db,
            user_id=1,
            name="二甲双胍",
            dose="2 片",
            frequency="daily",
            times=["08:00"],
        )
    medication_id = created["medication"]["id"]

    fake_model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_delete",
                        "name": "delete_medication",
                        "args": {
                            "user_id": 1,
                            "medication_id": medication_id,
                        },
                    }
                ],
            ),
            AIMessage(content="需要确认删除。"),
        ]
    )
    compiled = build_graph(model=fake_model, checkpointer=InMemorySaver())
    monkeypatch.setattr(graph_module, "get_graph", lambda: compiled)

    response = run_agent_turn(user_id=1, user_message="删掉二甲双胍", channel="cli")

    assert response.interrupted is True
    assert response.interrupt_reason == "delete_medication"
    assert "确认" in response.reply
    assert response.tool_calls[0].result == {"pending": True}

    medications = tools.list_medications(user_id=1, active_only=False)
    assert medications[0]["is_active"] is True


def test_confirm_executes_pending_dose_update(monkeypatch, test_session_factory) -> None:
    monkeypatch.setattr(tools, "SessionLocal", test_session_factory)
    with test_session_factory() as db:
        created = add_medication(
            db=db,
            user_id=1,
            name="二甲双胍",
            dose="1 片",
            frequency="daily",
            times=["08:00"],
        )
    medication_id = created["medication"]["id"]

    fake_model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_update",
                        "name": "update_medication",
                        "args": {
                            "user_id": 1,
                            "medication_id": medication_id,
                            "dose": "2 片",
                        },
                    }
                ],
            ),
        ]
    )
    compiled = build_graph(model=fake_model, checkpointer=InMemorySaver())
    monkeypatch.setattr(graph_module, "get_graph", lambda: compiled)

    pending = run_agent_turn(user_id=1, user_message="把二甲双胍改成2片", channel="cli")
    assert pending.interrupted is True

    response = run_agent_turn(user_id=1, user_message="确认", channel="cli")

    assert response.interrupted is False
    assert response.interrupt_reason is None
    assert response.tool_calls[0].name == "update_medication"
    assert response.tool_calls[0].result is not None
    assert response.tool_calls[0].result["medication"]["dose"] == "2 片"

    medications = tools.list_medications(user_id=1)
    assert medications[0]["dose"] == "2 片"


def test_cancel_keeps_pending_delete_from_executing(monkeypatch, test_session_factory) -> None:
    monkeypatch.setattr(tools, "SessionLocal", test_session_factory)
    with test_session_factory() as db:
        created = add_medication(
            db=db,
            user_id=1,
            name="二甲双胍",
            dose="2 片",
            frequency="daily",
            times=["08:00"],
        )
    medication_id = created["medication"]["id"]

    fake_model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_delete",
                        "name": "delete_medication",
                        "args": {
                            "user_id": 1,
                            "medication_id": medication_id,
                        },
                    }
                ],
            ),
        ]
    )
    compiled = build_graph(model=fake_model, checkpointer=InMemorySaver())
    monkeypatch.setattr(graph_module, "get_graph", lambda: compiled)

    pending = run_agent_turn(user_id=1, user_message="删掉二甲双胍", channel="cli")
    assert pending.interrupted is True

    response = run_agent_turn(user_id=1, user_message="取消", channel="cli")

    assert response.interrupted is False
    assert "取消" in response.reply
    assert response.tool_calls == []

    medications = tools.list_medications(user_id=1, active_only=False)
    assert medications[0]["is_active"] is True


def test_confirm_without_pending_action_is_isolated(monkeypatch) -> None:
    compiled = build_graph(model=FakeModel([]), checkpointer=InMemorySaver())
    monkeypatch.setattr(graph_module, "get_graph", lambda: compiled)

    response = run_agent_turn(user_id=2, user_message="确认", channel="cli")

    assert response.interrupted is False
    assert response.reply == "没有待确认的操作。"


def test_pending_action_is_isolated_by_user(monkeypatch, test_session_factory) -> None:
    monkeypatch.setattr(tools, "SessionLocal", test_session_factory)
    with test_session_factory() as db:
        created = add_medication(
            db=db,
            user_id=1,
            name="二甲双胍",
            dose="2 片",
            frequency="daily",
            times=["08:00"],
        )
    medication_id = created["medication"]["id"]

    fake_model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_delete",
                        "name": "delete_medication",
                        "args": {
                            "user_id": 1,
                            "medication_id": medication_id,
                        },
                    }
                ],
            ),
        ]
    )
    compiled = build_graph(model=fake_model, checkpointer=InMemorySaver())
    monkeypatch.setattr(graph_module, "get_graph", lambda: compiled)

    pending = run_agent_turn(user_id=1, user_message="删掉二甲双胍", channel="cli")
    assert pending.interrupted is True

    response = run_agent_turn(user_id=2, user_message="确认", channel="cli")

    assert response.reply == "没有待确认的操作。"
    medications = tools.list_medications(user_id=1, active_only=False)
    assert medications[0]["is_active"] is True


def test_multiturn_completion_uses_checkpoint_history(monkeypatch, test_session_factory) -> None:
    monkeypatch.setattr(tools, "SessionLocal", test_session_factory)
    fake_model = FakeModel(
        [
            AIMessage(content="请告诉我剂量、服用频率和提醒时间。"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_add",
                        "name": "add_medication",
                        "args": {
                            "user_id": 1,
                            "name": "二甲双胍",
                            "dose": "2 片",
                            "frequency": "daily",
                            "times": ["08:00"],
                            "instructions": "饭后",
                        },
                    }
                ],
            ),
            AIMessage(content="已添加二甲双胍。"),
        ]
    )
    compiled = build_graph(model=fake_model, checkpointer=InMemorySaver())
    monkeypatch.setattr(graph_module, "get_graph", lambda: compiled)

    first = run_agent_turn(user_id=1, user_message="帮我记录二甲双胍", channel="cli")
    second = run_agent_turn(user_id=1, user_message="每天早上8点，2片，饭后", channel="cli")

    assert first.tool_calls == []
    assert second.tool_calls[0].name == "add_medication"
    assert tools.list_medications(user_id=1)[0]["name"] == "二甲双胍"
    second_model_messages = fake_model.messages[1]
    assert any(isinstance(message, HumanMessage) and message.content == "帮我记录二甲双胍" for message in second_model_messages)


def test_stream_agent_turn_yields_graph_chunks(monkeypatch) -> None:
    monkeypatch.setattr(graph_module, "get_graph", lambda: StreamingGraph())

    chunks = list(stream_agent_turn(user_id=7, user_message="列一下我的药", channel="cli"))

    assert chunks == ["第一段", "第二段"]
