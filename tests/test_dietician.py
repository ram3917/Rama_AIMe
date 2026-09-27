"""log_meal uses langgraph's interrupt() for calorie confirmation, so its
confirm/decline flow needs a real (tiny) graph rather than calling the
tool function directly.
"""
import sqlite3

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from typing_extensions import TypedDict

from trainer import dietician
from trainer.dietician import get_meals, log_meal


def _fresh_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE meal_entries (
            date TEXT NOT NULL, meal TEXT NOT NULL, food TEXT NOT NULL,
            calories REAL, protein REAL, carbohydrates REAL, fat REAL
        )"""
    )
    return conn


class _State(TypedDict):
    food: str
    calories: float
    date: str
    result: dict


def _build_log_meal_graph():
    def node(state):
        return {"result": log_meal.invoke({"food": state["food"], "calories": state["calories"], "date": state["date"]})}

    builder = StateGraph(_State)
    builder.add_node("log_meal", node)
    builder.add_edge(START, "log_meal")
    builder.add_edge("log_meal", END)
    return builder.compile(checkpointer=InMemorySaver())


def test_log_meal_confirmed_writes_to_meals_db(monkeypatch):
    conn = _fresh_conn()
    monkeypatch.setattr(dietician, "_conn", conn)

    graph = _build_log_meal_graph()
    config = {"configurable": {"thread_id": "t1"}}

    paused = graph.invoke({"food": "chicken salad", "calories": 450, "date": "2026-03-01"}, config)
    assert "__interrupt__" in paused
    final = graph.invoke(Command(resume="yes"), config)

    row = conn.execute(
        "SELECT meal, food, calories FROM meal_entries WHERE date = ?", ("2026-03-01",)
    ).fetchone()
    assert row == ("meal", "chicken salad", 450)
    assert final["result"] == {"date": "2026-03-01", "meal": "meal", "food": "chicken salad", "calories": 450}


def test_log_meal_declined_does_not_write(monkeypatch):
    conn = _fresh_conn()
    monkeypatch.setattr(dietician, "_conn", conn)

    graph = _build_log_meal_graph()
    config = {"configurable": {"thread_id": "t2"}}
    graph.invoke({"food": "chicken salad", "calories": 450, "date": "2026-03-01"}, config)
    final = graph.invoke(Command(resume="no"), config)

    assert final["result"] == {"cancelled": True}
    assert conn.execute("SELECT COUNT(*) FROM meal_entries").fetchone()[0] == 0


def test_get_meals_defaults_to_today(monkeypatch):
    conn = _fresh_conn()
    monkeypatch.setattr(dietician, "_conn", conn)
    import datetime

    today = datetime.date.today().isoformat()
    conn.execute(
        "INSERT INTO meal_entries (date, meal, food, calories) VALUES (?, 'breakfast', 'Oatmeal', 300)",
        (today,),
    )
    conn.commit()

    result = get_meals.invoke({})

    assert result["date"] == today
    assert result["meals"]["breakfast"][0] == {"food": "Oatmeal", "calories": 300}
    assert result["totals"] == {"calories": 300}


def test_get_meals_missing_date_returns_note(monkeypatch):
    monkeypatch.setattr(dietician, "_conn", _fresh_conn())

    result = get_meals.invoke({"date": "2099-01-01"})

    assert result == {"date": "2099-01-01", "note": "no meals logged for this date"}


def test_get_meals_sums_totals_across_entries_and_meals(monkeypatch):
    conn = _fresh_conn()
    monkeypatch.setattr(dietician, "_conn", conn)
    conn.execute(
        "INSERT INTO meal_entries (date, meal, food, calories, protein) VALUES "
        "('2026-03-01', 'breakfast', 'Oatmeal', 300, 10), "
        "('2026-03-01', 'lunch', 'Chicken salad', 450, 35)"
    )
    conn.commit()

    result = get_meals.invoke({"date": "2026-03-01"})

    assert result["totals"] == {"calories": 750, "protein": 45}
    assert set(result["meals"]) == {"breakfast", "lunch"}
