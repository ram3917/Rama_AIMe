"""Assistant node: tools for remembering and recalling personal facts and
notes, and tracking todos - Notion is the source of truth for both (see
trainer/notion.py). Notes live in their own dedicated database; todos
reuse the user's existing Notion Todos database, so the bot sees and
manages the same list the user already has, not a separate shadow list.
"""
import datetime

from langchain_core.tools import tool

from trainer import notion
from trainer.config import settings

_DONE_STATES = {"Done", "Archived"}


@tool
def remember(key: str, value: str) -> str:
    """Save a personal fact or note under a short key, e.g. 'dentist_appointment'."""
    existing = notion.query_database(
        settings.notion_notes_db_id, filter={"property": "Key", "title": {"equals": key}}
    )
    properties = {"Key": notion.title(key), "Value": notion.rich_text(value)}
    if existing:
        notion.update_page(existing[0]["id"], {"Value": notion.rich_text(value)})
    else:
        notion.create_page(settings.notion_notes_db_id, properties)
    return f"Saved '{key}'."


@tool
def recall(key: str) -> str:
    """Look up a previously saved personal fact or note by its key."""
    pages = notion.query_database(
        settings.notion_notes_db_id, filter={"property": "Key", "title": {"equals": key}}
    )
    if not pages:
        return f"Nothing saved under '{key}'."
    return notion.page_property(pages[0], "Value") or f"Nothing saved under '{key}'."


@tool
def list_notes() -> dict:
    """List every personal fact/note that's been saved, as key/value pairs."""
    pages = notion.query_database(settings.notion_notes_db_id)
    return {notion.page_property(p, "Key"): notion.page_property(p, "Value") for p in pages}


def _purge_old_done_todos() -> None:
    cutoff = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)).isoformat()
    stale = notion.query_database(
        settings.notion_todos_db_id,
        filter={
            "and": [
                {"property": "Status", "status": {"equals": "Done"}},
                {"timestamp": "last_edited_time", "last_edited_time": {"before": cutoff}},
            ]
        },
    )
    for page in stale:
        notion.archive_page(page["id"])


@tool
def add_todo(text: str, deadline: str | None = None) -> str:
    """Add a todo for the user, with an optional deadline (YYYY-MM-DD)."""
    properties = {"Task name": notion.title(text), "Status": notion.status("Not started")}
    if deadline:
        properties["Due"] = notion.date(deadline)
    notion.create_page(settings.notion_todos_db_id, properties)
    if deadline:
        return f"Added todo '{text}' - due {deadline}, I'll remind you."
    return f"Added todo '{text}'."


@tool
def complete_todo(todo_id: str) -> str:
    """Mark a todo as done, by its id (look it up with list_todos first)."""
    notion.update_page(todo_id, {"Status": notion.status("Done")})
    return f"Marked todo {todo_id} as done."


@tool
def list_todos() -> list[dict]:
    """List all todos (open and recently-closed) with their id, text, deadline, and state."""
    _purge_old_done_todos()
    pages = notion.query_database(settings.notion_todos_db_id)
    return [
        {
            "id": p["id"],
            "text": notion.page_property(p, "Task name"),
            "deadline": notion.page_property(p, "Due"),
            "state": "done" if notion.page_property(p, "Status") in _DONE_STATES else "open",
        }
        for p in pages
    ]


TOOLS = [remember, recall, list_notes, add_todo, complete_todo, list_todos]

SYSTEM_PROMPT = (
    "You are the user's personal assistant. Handle general requests directly, "
    "and use your tools to remember or recall personal facts and notes, and "
    "to track todos - when adding a todo with a deadline, remind the user of "
    "that deadline in your reply. Workouts, steps, sleep, weight, and diet "
    "are the personal trainer's/dietician's job, not yours. Keep replies "
    "short and direct, no AI hedging."
)
