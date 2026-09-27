import datetime
import sqlite3

from trainer import personal


def _fresh_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE notes (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        """CREATE TABLE todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            deadline TEXT,
            state TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            done_at TEXT
        )"""
    )
    conn.commit()
    return conn


def test_remember_and_recall_roundtrip(monkeypatch):
    monkeypatch.setattr(personal, "_conn", _fresh_conn())

    result = personal.remember.invoke({"key": "dentist", "value": "March 5th"})

    assert "Saved" in result
    assert personal.recall.invoke({"key": "dentist"}) == "March 5th"


def test_recall_missing_key_says_nothing_saved(monkeypatch):
    monkeypatch.setattr(personal, "_conn", _fresh_conn())

    assert "Nothing saved" in personal.recall.invoke({"key": "missing"})


def test_list_notes_returns_all_saved_notes(monkeypatch):
    monkeypatch.setattr(personal, "_conn", _fresh_conn())
    personal.remember.invoke({"key": "a", "value": "1"})
    personal.remember.invoke({"key": "b", "value": "2"})

    assert personal.list_notes.invoke({}) == {"a": "1", "b": "2"}


def test_add_todo_without_deadline_does_not_mention_one(monkeypatch):
    monkeypatch.setattr(personal, "_conn", _fresh_conn())

    result = personal.add_todo.invoke({"text": "buy milk"})

    assert result == "Added todo 'buy milk'."


def test_add_todo_with_deadline_reminds_of_it(monkeypatch):
    monkeypatch.setattr(personal, "_conn", _fresh_conn())

    result = personal.add_todo.invoke({"text": "pay rent", "deadline": "2026-10-01"})

    assert "pay rent" in result
    assert "2026-10-01" in result


def test_new_todo_starts_open_and_appears_in_list(monkeypatch):
    monkeypatch.setattr(personal, "_conn", _fresh_conn())
    personal.add_todo.invoke({"text": "buy milk"})

    todos = personal.list_todos.invoke({})

    assert len(todos) == 1
    assert todos[0]["text"] == "buy milk"
    assert todos[0]["state"] == "open"


def test_complete_todo_marks_it_done(monkeypatch):
    monkeypatch.setattr(personal, "_conn", _fresh_conn())
    personal.add_todo.invoke({"text": "buy milk"})
    todo_id = personal.list_todos.invoke({})[0]["id"]

    personal.complete_todo.invoke({"todo_id": todo_id})

    todos = personal.list_todos.invoke({})
    assert todos[0]["state"] == "done"


def test_recently_closed_todo_stays_in_list(monkeypatch):
    conn = _fresh_conn()
    monkeypatch.setattr(personal, "_conn", conn)
    now = datetime.datetime.now().isoformat()
    conn.execute(
        "INSERT INTO todos (text, state, created_at, done_at) VALUES ('buy milk', 'done', ?, ?)",
        (now, now),
    )
    conn.commit()

    todos = personal.list_todos.invoke({})

    assert len(todos) == 1


def test_closed_todo_older_than_a_day_is_purged(monkeypatch):
    conn = _fresh_conn()
    monkeypatch.setattr(personal, "_conn", conn)
    old = (datetime.datetime.now() - datetime.timedelta(days=2)).isoformat()
    conn.execute(
        "INSERT INTO todos (text, state, created_at, done_at) VALUES ('buy milk', 'done', ?, ?)",
        (old, old),
    )
    conn.commit()

    todos = personal.list_todos.invoke({})

    assert todos == []
    assert conn.execute("SELECT COUNT(*) FROM todos").fetchone()[0] == 0


def test_old_open_todo_is_not_purged(monkeypatch):
    conn = _fresh_conn()
    monkeypatch.setattr(personal, "_conn", conn)
    old = (datetime.datetime.now() - datetime.timedelta(days=2)).isoformat()
    conn.execute(
        "INSERT INTO todos (text, state, created_at) VALUES ('buy milk', 'open', ?)",
        (old,),
    )
    conn.commit()

    todos = personal.list_todos.invoke({})

    assert len(todos) == 1
