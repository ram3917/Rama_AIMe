"""log_weight uses langgraph's interrupt() for write confirmation, so
its confirm/decline flow needs a real (tiny) graph rather than calling
the tool function directly.
"""
import datetime
import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from typing_extensions import TypedDict

from trainer import fitness_data
from trainer.fitness_data import get_daily_log, log_weight


def _fresh_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE daily_log (
            date TEXT PRIMARY KEY,
            steps INTEGER,
            sleep_hours REAL,
            weight_kg REAL,
            activity_type TEXT,
            duration_min REAL,
            calories INTEGER,
            distance_km REAL,
            avg_hr INTEGER,
            max_hr INTEGER
        )"""
    )
    conn.commit()
    return conn


def test_get_daily_log_defaults_to_today(monkeypatch):
    conn = _fresh_conn()
    monkeypatch.setattr(fitness_data, "_conn", conn)
    today = datetime.date.today().isoformat()
    conn.execute("INSERT INTO daily_log (date, steps) VALUES (?, ?)", (today, 5000))
    conn.commit()

    result = get_daily_log.invoke({})
    assert result["steps"] == 5000
    assert result["date"] == today


def test_get_daily_log_missing_date_returns_note(monkeypatch):
    monkeypatch.setattr(fitness_data, "_conn", _fresh_conn())

    result = get_daily_log.invoke({"date": "2099-01-01"})
    assert result == {"date": "2099-01-01", "note": "no data logged for this date"}


def test_get_daily_log_includes_workout_fields_and_omits_unset_ones(monkeypatch):
    conn = _fresh_conn()
    monkeypatch.setattr(fitness_data, "_conn", conn)
    conn.execute(
        "INSERT INTO daily_log (date, activity_type, duration_min, calories, distance_km, avg_hr, max_hr) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-03-01", "running", 32.5, 350, 5.2, 142, 168),
    )
    conn.commit()

    result = get_daily_log.invoke({"date": "2026-03-01"})

    assert result == {
        "date": "2026-03-01",
        "activity_type": "running",
        "duration_min": 32.5,
        "calories": 350,
        "distance_km": 5.2,
        "avg_hr": 142,
        "max_hr": 168,
    }
    assert "steps" not in result


class _State(TypedDict):
    weight_kg: float
    date: str
    result: dict


def _build_log_weight_graph():
    def node(state):
        return {"result": log_weight.invoke({"weight_kg": state["weight_kg"], "date": state["date"]})}

    builder = StateGraph(_State)
    builder.add_node("log_weight", node)
    builder.add_edge(START, "log_weight")
    builder.add_edge("log_weight", END)
    return builder.compile(checkpointer=InMemorySaver())


def test_log_weight_confirmed_writes_to_garmin_and_fitness_db(monkeypatch):
    conn = _fresh_conn()
    monkeypatch.setattr(fitness_data, "_conn", conn)
    monkeypatch.setattr(fitness_data.settings, "garmin_email", "user@example.com")
    monkeypatch.setattr(fitness_data.settings, "garmin_password", "secret")

    graph = _build_log_weight_graph()
    config = {"configurable": {"thread_id": "t1"}}

    mock_client = MagicMock()
    with patch("garminconnect.Garmin", return_value=mock_client) as mock_cls:
        paused = graph.invoke({"weight_kg": 82.4, "date": "2026-03-01"}, config)
        assert "__interrupt__" in paused
        final = graph.invoke(Command(resume="yes"), config)

    mock_cls.assert_called_once_with("user@example.com", "secret")
    mock_client.login.assert_called_once()
    mock_client.add_weigh_in.assert_called_once()
    row = conn.execute("SELECT weight_kg FROM daily_log WHERE date = ?", ("2026-03-01",)).fetchone()
    assert row[0] == 82.4
    assert final["result"] == {"date": "2026-03-01", "weight_kg": 82.4}


def test_log_weight_declined_does_not_write(monkeypatch):
    conn = _fresh_conn()
    monkeypatch.setattr(fitness_data, "_conn", conn)

    graph = _build_log_weight_graph()
    config = {"configurable": {"thread_id": "t2"}}
    graph.invoke({"weight_kg": 82.4, "date": "2026-03-01"}, config)
    final = graph.invoke(Command(resume="no"), config)

    assert final["result"] == {"cancelled": True}
    assert conn.execute("SELECT COUNT(*) FROM daily_log").fetchone()[0] == 0


def test_log_weight_raises_clearly_without_garmin_creds(monkeypatch):
    monkeypatch.setattr(fitness_data, "_conn", _fresh_conn())
    monkeypatch.setattr(fitness_data.settings, "garmin_email", None)
    monkeypatch.setattr(fitness_data.settings, "garmin_password", None)

    graph = _build_log_weight_graph()
    config = {"configurable": {"thread_id": "t3"}}
    graph.invoke({"weight_kg": 82.4, "date": "2026-03-01"}, config)

    with pytest.raises(RuntimeError, match="GARMIN_EMAIL"):
        graph.invoke(Command(resume="yes"), config)
