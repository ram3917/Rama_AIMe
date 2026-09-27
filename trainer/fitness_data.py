"""Personal Trainer node: fitness tools backed by the Notion Fitness Log
database, plus Garmin for weight writes. Logging weight pauses the graph
for a yes/no confirmation via LangGraph's interrupt() - the model never
gets to touch Garmin (or Notion) on its own say-so.
"""
import datetime

from langchain_core.tools import tool
from langgraph.types import interrupt

from trainer import notion
from trainer.config import settings

_CONFIRM_YES = {"yes", "y", "yep", "yeah", "confirm", "do it", "sure"}
LOG_PROPS = {
    "steps": "Steps",
    "sleep_hours": "Sleep (hrs)",
    "weight_kg": "Weight (kg)",
    "activity_type": "Activity Type",
    "duration_min": "Duration (min)",
    "calories": "Calories",
    "distance_km": "Distance (km)",
    "avg_hr": "Avg HR",
    "max_hr": "Max HR",
}


def find_day(date_str: str) -> dict | None:
    pages = notion.query_database(
        settings.notion_fitness_db_id, filter={"property": "Date", "date": {"equals": date_str}}
    )
    return pages[0] if pages else None


@tool
def get_daily_log(date: str | None = None) -> dict:
    """Get logged fitness data (steps, sleep, weight, workouts) for a date (YYYY-MM-DD, defaults to today)."""
    date_str = date or datetime.date.today().isoformat()
    page = find_day(date_str)
    if not page:
        return {"date": date_str, "note": "no data logged for this date"}
    result = {"date": date_str}
    for key, prop_name in LOG_PROPS.items():
        value = notion.page_property(page, prop_name)
        if value is not None:
            result[key] = value
    return result


@tool
def log_weight(weight_kg: float, date: str | None = None) -> dict:
    """Log the user's body weight in kilograms for a date (defaults to today). Writes to Garmin and the Notion fitness log."""
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

    page = find_day(date_str)
    if page:
        notion.update_page(page["id"], {"Weight (kg)": notion.number(weight_kg)})
    else:
        notion.create_page(
            settings.notion_fitness_db_id,
            {"Name": notion.title(date_str), "Date": notion.date(date_str), "Weight (kg)": notion.number(weight_kg)},
        )
    return {"date": date_str, "weight_kg": weight_kg}


TOOLS = [get_daily_log, log_weight]

SYSTEM_PROMPT = (
    "You are the user's personal trainer. Talk like a real trainer texting a "
    "client: short, direct, no AI hedging. Use get_daily_log to check steps, "
    "sleep, weight, or workout data (type, duration, calories, distance, "
    "heart rate) before answering questions about them - don't invent "
    "numbers that aren't there. Use the health goals below to judge whether "
    "the user is on track and to tailor any advice."
)
