"""Personal Trainer node: fitness tools backed by their own fitness
database, plus Garmin for weight writes. Logging weight pauses the
graph for a yes/no confirmation via LangGraph's interrupt() - the model
never gets to touch Garmin on its own say-so.
"""
import datetime
import sqlite3

from langchain_core.tools import tool
from langgraph.types import interrupt

from trainer.config import settings

settings.fitness_db_path.parent.mkdir(parents=True, exist_ok=True)
_conn = sqlite3.connect(str(settings.fitness_db_path), check_same_thread=False)
_conn.execute(
    """CREATE TABLE IF NOT EXISTS daily_log (
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
_conn.commit()

_CONFIRM_YES = {"yes", "y", "yep", "yeah", "confirm", "do it", "sure"}
_LOG_COLUMNS = [
    "steps", "sleep_hours", "weight_kg",
    "activity_type", "duration_min", "calories", "distance_km", "avg_hr", "max_hr",
]


@tool
def get_daily_log(date: str | None = None) -> dict:
    """Get logged fitness data (steps, sleep, weight, workouts) for a date (YYYY-MM-DD, defaults to today)."""
    date_str = date or datetime.date.today().isoformat()
    row = _conn.execute(
        f"SELECT {', '.join(_LOG_COLUMNS)} FROM daily_log WHERE date = ?", (date_str,)
    ).fetchone()
    if not row:
        return {"date": date_str, "note": "no data logged for this date"}
    result = {"date": date_str}
    result.update({col: val for col, val in zip(_LOG_COLUMNS, row) if val is not None})
    return result


@tool
def log_weight(weight_kg: float, date: str | None = None) -> dict:
    """Log the user's body weight in kilograms for a date (defaults to today). Writes to Garmin and the fitness database."""
    date_str = date or datetime.date.today().isoformat()
    answer = interrupt(f"Log {weight_kg} kg for {date_str}? Reply yes to confirm.")
    if str(answer).strip().lower() not in _CONFIRM_YES:
        return {"cancelled": True}

    if not settings.garmin_email or not settings.garmin_password:
        raise RuntimeError("GARMIN_EMAIL and GARMIN_PASSWORD must be set to log weight to Garmin")

    from garminconnect import Garmin

    today_str = datetime.date.today().isoformat()
    timestamp = datetime.datetime.now().isoformat() if date_str == today_str else f"{date_str}T07:00:00"

    client = Garmin(settings.garmin_email, settings.garmin_password)
    client.login()
    client.add_weigh_in(weight=weight_kg, unitKey="kg", timestamp=timestamp)

    _conn.execute(
        "INSERT INTO daily_log (date, weight_kg) VALUES (?, ?) ON CONFLICT(date) DO UPDATE SET weight_kg = excluded.weight_kg",
        (date_str, weight_kg),
    )
    _conn.commit()
    return {"date": date_str, "weight_kg": weight_kg}


TOOLS = [get_daily_log, log_weight]

SYSTEM_PROMPT = (
    "You are the user's personal trainer. Talk like a real trainer texting a "
    "client: short, direct, no AI hedging. Use get_daily_log to check steps, "
    "sleep, weight, or workout data (type, duration, calories, distance, "
    "heart rate) before answering questions about them - don't invent "
    "numbers that aren't there."
)
