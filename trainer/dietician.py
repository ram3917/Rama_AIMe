"""Dietician node: the user describes what they ate in plain language -
one meal, or every meal of the day in one message - the model estimates
calories and macros itself (no external food database) for each distinct
item, and logs each to the Notion Meals database, but only after the
user confirms that item's estimate via LangGraph's interrupt(). A
message describing several meals means several log_meal calls, each
confirmed on its own, not one batch confirmation - simpler and more
reliable for a local model to drive than a single call carrying a list.
"""
import datetime

from langchain_core.tools import tool
from langgraph.types import interrupt

from trainer import notion
from trainer.config import settings

_CONFIRM_YES = {"yes", "y", "yep", "yeah", "confirm", "do it", "sure"}
_MACRO_PROPS = {
    "calories": "Calories",
    "protein": "Protein (g)",
    "carbohydrates": "Carbs (g)",
    "fat": "Fat (g)",
}


def _query_meals(date_str: str) -> list[dict]:
    return notion.query_database(
        settings.notion_meals_db_id, filter={"property": "Date", "date": {"equals": date_str}}
    )


def _meals_and_totals(pages: list[dict]) -> tuple[dict, dict]:
    meals: dict[str, list[dict]] = {}
    totals = dict.fromkeys(_MACRO_PROPS, 0.0)
    for page in pages:
        meal_name = notion.page_property(page, "Meal") or "meal"
        entry = {"food": notion.page_property(page, "Food")}
        for key, prop_name in _MACRO_PROPS.items():
            value = notion.page_property(page, prop_name)
            if value is not None:
                entry[key] = value
                totals[key] += value
        meals.setdefault(meal_name, []).append(entry)
    return meals, {n: round(v, 1) for n, v in totals.items() if v}


def _describe_macros(calories: float, protein: float | None, carbohydrates: float | None, fat: float | None) -> str:
    parts = [f"{calories} kcal"]
    if protein is not None:
        parts.append(f"{protein}g protein")
    if carbohydrates is not None:
        parts.append(f"{carbohydrates}g carbs")
    if fat is not None:
        parts.append(f"{fat}g fat")
    return ", ".join(parts)


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
    """Log a single food/meal the user described, with your best-estimate calories and macros in grams (protein, carbohydrates, fat). If they described several foods/meals in one message, call this once per item. `meal` is e.g. 'breakfast'/'lunch'/'dinner'/'snack', defaults to 'meal'. Asks the user to confirm the estimate first."""
    date_str = date or datetime.date.today().isoformat()
    meal_name = meal or "meal"
    macros = _describe_macros(calories, protein, carbohydrates, fat)
    answer = interrupt(f"Log '{food}' ({meal_name}) - {macros}? Reply yes to confirm.")
    if str(answer).strip().lower() not in _CONFIRM_YES:
        return {"cancelled": True}

    properties = {
        "Food": notion.title(food),
        "Date": notion.date(date_str),
        "Meal": notion.select(meal_name),
        "Calories": notion.number(calories),
    }
    if protein is not None:
        properties["Protein (g)"] = notion.number(protein)
    if carbohydrates is not None:
        properties["Carbs (g)"] = notion.number(carbohydrates)
    if fat is not None:
        properties["Fat (g)"] = notion.number(fat)
    notion.create_page(settings.notion_meals_db_id, properties)

    _, today_totals = _meals_and_totals(_query_meals(date_str))
    return {"date": date_str, "meal": meal_name, "food": food, "calories": calories, "today_totals": today_totals}


@tool
def get_meals(date: str | None = None) -> dict:
    """Get logged meals, foods, and nutrition totals for a date (YYYY-MM-DD, defaults to today)."""
    date_str = date or datetime.date.today().isoformat()
    pages = _query_meals(date_str)
    if not pages:
        return {"date": date_str, "note": "no meals logged for this date"}

    meals, totals = _meals_and_totals(pages)
    return {"date": date_str, "meals": meals, "totals": totals}


TOOLS = [log_meal, get_meals]

SYSTEM_PROMPT = (
    "You are the user's dietician. When they describe something they ate - "
    "whether it's one meal or everything they ate that day in one message - "
    "estimate the calories and macros (protein/carbohydrates/fat in grams) "
    "yourself from general nutrition knowledge for EACH distinct food/meal, "
    "and call log_meal once per item with your best estimate; it will ask "
    "the user to confirm each one before saving, so just make your best "
    "call. After logging (log_meal's result includes today's running "
    "totals), always follow up with a short, specific response about the "
    "meal itself - not just a bare confirmation - using the health goals "
    "below (calorie/macro targets) to say how it fits: whether it's a good "
    "choice, how much room is left in today's targets, or what to adjust "
    "for the rest of the day. Use get_meals to check what's already logged "
    "before answering questions about their food, calories, or macros - "
    "don't invent numbers for what's already logged. Keep replies short and "
    "direct, no AI hedging."
)
