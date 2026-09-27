"""Dietician node: the user describes what they ate in plain language,
the model estimates calories and macros itself (no external food
database), and logs it to its own meals database - but only after the
user confirms the calorie estimate, via LangGraph's interrupt().
"""
import datetime
import sqlite3

from langchain_core.tools import tool
from langgraph.types import interrupt

from trainer.config import settings

_NUTRIENTS = ["calories", "protein", "carbohydrates", "fat"]
_CONFIRM_YES = {"yes", "y", "yep", "yeah", "confirm", "do it", "sure"}

settings.meals_db_path.parent.mkdir(parents=True, exist_ok=True)
_conn = sqlite3.connect(str(settings.meals_db_path), check_same_thread=False)
_conn.execute(
    f"""CREATE TABLE IF NOT EXISTS meal_entries (
        date TEXT NOT NULL,
        meal TEXT NOT NULL,
        food TEXT NOT NULL,
        {', '.join(f'{n} REAL' for n in _NUTRIENTS)}
    )"""
)
_conn.commit()


@tool
def log_meal(
    food: str,
    calories: float,
    protein: float | None = None,
    carbohydrates: float | None = None,
    fat: float | None = None,
    meal: str | None = None,
    date: str | None = None,
) -> dict:
    """Log a food/meal the user described, with your best-estimate calories and macros in grams (protein, carbohydrates, fat). `meal` is e.g. 'breakfast'/'lunch'/'dinner'/'snack', defaults to 'meal'. Asks the user to confirm the calorie estimate first."""
    date_str = date or datetime.date.today().isoformat()
    meal_name = meal or "meal"
    answer = interrupt(f"Log '{food}' ({meal_name}) at ~{calories} kcal? Reply yes to confirm.")
    if str(answer).strip().lower() not in _CONFIRM_YES:
        return {"cancelled": True}

    _conn.execute(
        f"INSERT INTO meal_entries (date, meal, food, {', '.join(_NUTRIENTS)}) "
        f"VALUES (?, ?, ?, {', '.join('?' for _ in _NUTRIENTS)})",
        (date_str, meal_name, food, calories, protein, carbohydrates, fat),
    )
    _conn.commit()
    return {"date": date_str, "meal": meal_name, "food": food, "calories": calories}


@tool
def get_meals(date: str | None = None) -> dict:
    """Get logged meals, foods, and nutrition totals for a date (YYYY-MM-DD, defaults to today)."""
    date_str = date or datetime.date.today().isoformat()

    rows = _conn.execute(
        f"SELECT meal, food, {', '.join(_NUTRIENTS)} FROM meal_entries WHERE date = ?", (date_str,)
    ).fetchall()
    if not rows:
        return {"date": date_str, "note": "no meals logged for this date"}

    meals: dict[str, list[dict]] = {}
    totals = dict.fromkeys(_NUTRIENTS, 0.0)
    for meal, food, *values in rows:
        entry = {"food": food}
        for nutrient, value in zip(_NUTRIENTS, values):
            if value is not None:
                entry[nutrient] = value
                totals[nutrient] += value
        meals.setdefault(meal, []).append(entry)

    return {
        "date": date_str,
        "meals": meals,
        "totals": {n: round(v, 1) for n, v in totals.items() if v},
    }


TOOLS = [log_meal, get_meals]

SYSTEM_PROMPT = (
    "You are the user's dietician. When they describe something they ate, "
    "estimate its calories and macros (protein/carbohydrates/fat in grams) "
    "yourself from general nutrition knowledge, then call log_meal with your "
    "best estimate - it will ask the user to confirm before anything is "
    "saved, so just make your best call. Use get_meals to check what's "
    "already logged before answering questions about their food, calories, "
    "or macros - don't invent numbers for what's already logged. Keep "
    "replies short and direct, no AI hedging."
)
