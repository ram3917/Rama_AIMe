"""Assistant node: tools for remembering and recalling personal facts and
notes, and tracking todos - all backed by its own personal-sqlite
database.
"""
import datetime
import sqlite3

from langchain_core.tools import tool

from trainer.config import settings

settings.personal_db_path.parent.mkdir(parents=True, exist_ok=True)
_conn = sqlite3.connect(str(settings.personal_db_path), check_same_thread=False)
_conn.execute("CREATE TABLE IF NOT EXISTS notes (key TEXT PRIMARY KEY, value TEXT)")
_conn.execute(
    """CREATE TABLE IF NOT EXISTS todos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        deadline TEXT,
        state TEXT NOT NULL DEFAULT 'open',
        created_at TEXT NOT NULL,
        done_at TEXT
    )"""
)
_conn.commit()


@tool
def remember(key: str, value: str) -> str:
    """Save a personal fact or note under a short key, e.g. 'dentist_appointment'."""
    _conn.execute(
        "INSERT INTO notes (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    _conn.commit()
    return f"Saved '{key}'."


@tool
def recall(key: str) -> str:
    """Look up a previously saved personal fact or note by its key."""
    row = _conn.execute("SELECT value FROM notes WHERE key = ?", (key,)).fetchone()
    return row[0] if row else f"Nothing saved under '{key}'."


@tool
def list_notes() -> dict:
    """List every personal fact/note that's been saved, as key/value pairs."""
    return dict(_conn.execute("SELECT key, value FROM notes").fetchall())


def _purge_old_done_todos() -> None:
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat()
    _conn.execute("DELETE FROM todos WHERE state = 'done' AND done_at < ?", (cutoff,))
    _conn.commit()


@tool
def add_todo(text: str, deadline: str | None = None) -> str:
    """Add a todo for the user, with an optional deadline (e.g. 'tomorrow', '2026-10-01')."""
    _conn.execute(
        "INSERT INTO todos (text, deadline, state, created_at) VALUES (?, ?, 'open', ?)",
        (text, deadline, datetime.datetime.now().isoformat()),
    )
    _conn.commit()
    if deadline:
        return f"Added todo '{text}' - due {deadline}, I'll remind you."
    return f"Added todo '{text}'."


@tool
def complete_todo(todo_id: int) -> str:
    """Mark a todo as done, by its id (look it up with list_todos first)."""
    _conn.execute(
        "UPDATE todos SET state = 'done', done_at = ? WHERE id = ?",
        (datetime.datetime.now().isoformat(), todo_id),
    )
    _conn.commit()
    return f"Marked todo {todo_id} as done."


@tool
def list_todos() -> list[dict]:
    """List all todos (open and recently-closed) with their id, text, deadline, and state."""
    _purge_old_done_todos()
    rows = _conn.execute("SELECT id, text, deadline, state FROM todos").fetchall()
    return [{"id": r[0], "text": r[1], "deadline": r[2], "state": r[3]} for r in rows]


TOOLS = [remember, recall, list_notes, add_todo, complete_todo, list_todos]

SYSTEM_PROMPT = (
    "You are the user's personal assistant. Handle general requests directly, "
    "and use your tools to remember or recall personal facts and notes, and "
    "to track todos - when adding a todo with a deadline, remind the user of "
    "that deadline in your reply. Workouts, steps, sleep, weight, and Garmin "
    "data are the personal trainer's job, not yours. Keep replies short and "
    "direct, no AI hedging."
)
