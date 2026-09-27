import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import garmin as garmin_script  # noqa: E402


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
    return conn


def _mock_client(**overrides):
    client = MagicMock()
    client.get_stats.return_value = overrides.get("stats", {"totalSteps": 5000})
    client.get_sleep_data.return_value = overrides.get(
        "sleep", {"dailySleepDTO": {"sleepTimeSeconds": 27000}}
    )
    client.get_daily_weigh_ins.return_value = overrides.get(
        "weigh_ins", {"dateWeightList": [{"weight": 82400}]}
    )
    client.get_activities_by_date.return_value = overrides.get("activities", [])
    return client


def test_fetch_day_combines_steps_sleep_and_weight():
    row = garmin_script._fetch_day(_mock_client(), "2026-03-01")

    assert row == {"date": "2026-03-01", "steps": 5000, "sleep_hours": 7.5, "weight_kg": 82.4}


def test_fetch_day_skips_missing_weigh_ins():
    row = garmin_script._fetch_day(_mock_client(weigh_ins={"dateWeightList": []}), "2026-03-01")

    assert "weight_kg" not in row


def test_fetch_day_tolerates_a_failing_call():
    client = _mock_client()
    client.get_stats.side_effect = RuntimeError("boom")

    row = garmin_script._fetch_day(client, "2026-03-01")

    assert "steps" not in row
    assert row["sleep_hours"] == 7.5


def test_fetch_day_includes_workout_summary():
    activities = [
        {"activityType": {"typeKey": "running"}, "duration": 1800, "calories": 350, "distance": 5200, "averageHR": 142, "maxHR": 168},
    ]
    row = garmin_script._fetch_day(_mock_client(activities=activities), "2026-03-01")

    assert row["activity_type"] == "running"
    assert row["duration_min"] == 30.0
    assert row["calories"] == 350
    assert row["distance_km"] == 5.2
    assert row["avg_hr"] == 142
    assert row["max_hr"] == 168


def test_summarize_activities_combines_multiple_workouts():
    activities = [
        {"activityType": {"typeKey": "running"}, "duration": 1800, "calories": 350, "distance": 5000, "averageHR": 140, "maxHR": 160},
        {"activityType": {"typeKey": "strength_training"}, "duration": 1200, "calories": 200, "distance": 0, "averageHR": 110, "maxHR": 130},
    ]
    summary = garmin_script._summarize_activities(activities)

    assert summary["activity_type"] == "running+strength_training"
    assert summary["duration_min"] == 50.0
    assert summary["calories"] == 550
    assert summary["distance_km"] == 5.0
    assert summary["avg_hr"] == 125
    assert summary["max_hr"] == 160


def test_summarize_activities_empty_list_returns_empty_summary():
    assert garmin_script._summarize_activities([]) == {}


def test_upsert_inserts_then_updates():
    conn = _fresh_conn()

    garmin_script._upsert(conn, {"date": "2026-03-01", "steps": 5000})
    garmin_script._upsert(conn, {"date": "2026-03-01", "weight_kg": 82.4, "activity_type": "running"})
    conn.commit()

    row = conn.execute(
        "SELECT steps, weight_kg, activity_type FROM daily_log WHERE date = ?", ("2026-03-01",)
    ).fetchone()
    assert row == (5000, 82.4, "running")
