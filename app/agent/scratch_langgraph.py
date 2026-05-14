from typing import Literal, Optional, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class ScratchState(TypedDict):
    user_id: int
    message: str
    reply: str
    pending_action: Optional[str]
    confirmed: Optional[bool]


def reply_node(state: ScratchState) -> ScratchState:
    message = state["message"]
    if "删除" in message or "删掉" in message:
        return {
            **state,
            "reply": "",
            "pending_action": "delete_medication",
            "confirmed": None,
        }

    return {
        **state,
        "reply": f"收到：{message}",
        "pending_action": None,
        "confirmed": None,
    }


def review_node(state: ScratchState) -> ScratchState:
    decision = interrupt(
        {
            "action": state["pending_action"],
            "reason": "删除用药计划前需要用户确认。",
            "expected_replies": ["确认", "取消"],
        }
    )

    confirmed = str(decision).strip() == "确认"
    return {
        **state,
        "confirmed": confirmed,
        "reply": "已确认，后续会执行删除。" if confirmed else "已取消删除。",
    }


def route_after_reply(state: ScratchState) -> Literal["review", "__end__"]:
    if state["pending_action"]:
        return "review"
    return "__end__"


def build_graph():
    graph = StateGraph(ScratchState)
    graph.add_node("reply", reply_node)
    graph.add_node("review", review_node)
    graph.add_edge(START, "reply")
    graph.add_conditional_edges(
        "reply",
        route_after_reply,
        {
            "review": "review",
            "__end__": END,
        },
    )
    graph.add_edge("review", END)
    return graph.compile(checkpointer=InMemorySaver())


def main() -> None:
    graph = build_graph()

    normal_config = {"configurable": {"thread_id": "user:1"}}
    normal = graph.invoke(
        {
            "user_id": 1,
            "message": "hello",
            "reply": "",
            "pending_action": None,
            "confirmed": None,
        },
        config=normal_config,
    )
    print("normal:", normal)

    review_config = {"configurable": {"thread_id": "user:2"}}
    interrupted = graph.invoke(
        {
            "user_id": 2,
            "message": "删除二甲双胍",
            "reply": "",
            "pending_action": None,
            "confirmed": None,
        },
        config=review_config,
    )
    print("interrupted:", interrupted)

    resumed = graph.invoke(Command(resume="确认"), config=review_config)
    print("resumed:", resumed)


if __name__ == "__main__":
    main()
