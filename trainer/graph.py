"""LangGraph wiring: three nodes sharing one local Ollama model - an
Assistant node (trainer/personal.py), a Personal Trainer node
(trainer/fitness_data.py), and a Dietician node (trainer/dietician.py) -
routed by a small classification call. This is the one place that
decides which specialist handles a message; everything else (the
tool-calling loop, write confirmations, chat history across restarts)
is langgraph/langchain machinery, not ours.

The trainer and dietician also get the user's Notion "Health Goals" page
(a plain page of prose/targets, not a database) fetched fresh into their
system prompt on every message, so goals stay current without a restart.
"""
import sqlite3
from typing import Literal

from langchain_core.messages import SystemMessage
from langchain_ollama import ChatOllama
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel

from trainer import dietician, fitness_data, notion, personal
from trainer.config import settings

model = ChatOllama(base_url=settings.ollama_host, model=settings.ollama_model)


def _with_health_goals(system_prompt: str):
    def prompt_fn(state: MessagesState) -> list:
        goals = notion.get_page_text(settings.notion_health_goals_page_id) if settings.notion_health_goals_page_id else ""
        combined = f"{system_prompt}\n\nHealth goals (from Notion):\n{goals}" if goals else system_prompt
        return [SystemMessage(combined)] + state["messages"]

    return prompt_fn


assistant_agent = create_react_agent(model, tools=personal.TOOLS, prompt=personal.SYSTEM_PROMPT)
trainer_agent = create_react_agent(model, tools=fitness_data.TOOLS, prompt=_with_health_goals(fitness_data.SYSTEM_PROMPT))
dietician_agent = create_react_agent(model, tools=dietician.TOOLS, prompt=_with_health_goals(dietician.SYSTEM_PROMPT))


class _Route(BaseModel):
    target: Literal["assistant", "trainer", "dietician"]


_router_model = model.with_structured_output(_Route)

_ROUTER_PROMPT = (
    "Route this message to 'trainer' if it's about workouts, steps, sleep, "
    "weight, or Garmin data; to 'dietician' if it's about food, meals, "
    "calories, or macros; otherwise route it to 'assistant'."
)


def route(state: MessagesState) -> Literal["assistant", "trainer", "dietician"]:
    decision = _router_model.invoke([SystemMessage(_ROUTER_PROMPT), state["messages"][-1]])
    return decision.target


builder = StateGraph(MessagesState)
builder.add_node("assistant", assistant_agent)
builder.add_node("trainer", trainer_agent)
builder.add_node("dietician", dietician_agent)
builder.add_conditional_edges(
    START, route, {"assistant": "assistant", "trainer": "trainer", "dietician": "dietician"}
)
builder.add_edge("assistant", END)
builder.add_edge("trainer", END)
builder.add_edge("dietician", END)

settings.checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
_conn = sqlite3.connect(str(settings.checkpoint_db_path), check_same_thread=False)
checkpointer = SqliteSaver(_conn)

graph = builder.compile(checkpointer=checkpointer)
