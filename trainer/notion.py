"""Thin REST client for the Notion API - the only place trainer/personal.py,
trainer/fitness_data.py, trainer/dietician.py, and scripts/garmin.py should
reach Notion from. No official SDK - Notion's HTTP API is simple enough
that a dependency isn't worth it (same call as using `requests` directly
for Telegram in trainer/bot.py).
"""
import requests

from trainer.config import settings

_BASE_URL = "https://api.notion.com/v1"
_VERSION = "2022-06-28"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.notion_token}",
        "Notion-Version": _VERSION,
        "Content-Type": "application/json",
    }


def query_database(database_id: str, filter: dict | None = None) -> list[dict]:
    """Return every (non-archived) page in a database, paginating as needed."""
    pages = []
    cursor = None
    while True:
        body: dict = {}
        if filter:
            body["filter"] = filter
        if cursor:
            body["start_cursor"] = cursor
        resp = requests.post(f"{_BASE_URL}/databases/{database_id}/query", headers=_headers(), json=body, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        pages.extend(data["results"])
        if not data.get("has_more"):
            return pages
        cursor = data["next_cursor"]


def create_page(database_id: str, properties: dict) -> dict:
    resp = requests.post(
        f"{_BASE_URL}/pages",
        headers=_headers(),
        json={"parent": {"database_id": database_id}, "properties": properties},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def update_page(page_id: str, properties: dict) -> dict:
    resp = requests.patch(f"{_BASE_URL}/pages/{page_id}", headers=_headers(), json={"properties": properties}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def archive_page(page_id: str) -> dict:
    resp = requests.patch(f"{_BASE_URL}/pages/{page_id}", headers=_headers(), json={"archived": True}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_page_text(page_id: str) -> str:
    """Flatten a page's child blocks into readable plain text (headings and
    list items get simple prefixes; nested/child blocks are not recursed)."""
    blocks = []
    cursor = None
    while True:
        params = {"start_cursor": cursor} if cursor else {}
        resp = requests.get(f"{_BASE_URL}/blocks/{page_id}/children", headers=_headers(), params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        blocks.extend(data["results"])
        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]

    lines = []
    for block in blocks:
        btype = block["type"]
        content = block.get(btype, {})
        text = "".join(t.get("plain_text", "") for t in content.get("rich_text", []))
        if not text:
            continue
        if btype.startswith("heading"):
            lines.append(f"\n{text}")
        elif btype in ("bulleted_list_item", "numbered_list_item"):
            lines.append(f"- {text}")
        else:
            lines.append(text)
    return "\n".join(lines)


# --- property builders (for create_page/update_page) ---

def title(text: str) -> dict:
    return {"title": [{"text": {"content": text}}]}


def rich_text(text: str) -> dict:
    return {"rich_text": [{"text": {"content": text}}]}


def number(value: float | None) -> dict:
    return {"number": value}


def select(name: str | None) -> dict:
    return {"select": {"name": name} if name else None}


def status(name: str) -> dict:
    return {"status": {"name": name}}


def date(iso_date: str | None) -> dict:
    return {"date": {"start": iso_date} if iso_date else None}


# --- property readers (for query_database results) ---

def prop_value(prop: dict):
    """Extract the plain Python value out of one Notion property object."""
    ptype = prop["type"]
    if ptype == "title":
        return "".join(t["plain_text"] for t in prop["title"]) or None
    if ptype == "rich_text":
        return "".join(t["plain_text"] for t in prop["rich_text"]) or None
    if ptype == "number":
        return prop["number"]
    if ptype == "select":
        return prop["select"]["name"] if prop["select"] else None
    if ptype == "status":
        return prop["status"]["name"] if prop["status"] else None
    if ptype == "date":
        return prop["date"]["start"] if prop["date"] else None
    return None


def page_property(page: dict, name: str):
    return prop_value(page["properties"][name])
