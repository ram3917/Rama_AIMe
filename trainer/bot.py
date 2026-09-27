"""Telegram bot - long polling, no exposed ports. Every message is
routed through trainer.graph's two-node LangGraph app (Assistant vs
Personal Trainer), keyed by chat_id as the graph's thread id, which is
also how conversation history persists across restarts (the graph's
own SQLite checkpointer). Write tools (like logging weight) pause the
graph via interrupt() and this loop resumes it on the next message.

Run: python -m trainer.bot
"""
import logging
import time

import requests
from langgraph.types import Command

from trainer.config import settings
from trainer.graph import graph

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def _call(method: str, **params):
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    url = TELEGRAM_API.format(token=settings.telegram_bot_token, method=method)
    payload = {k: v for k, v in params.items() if v is not None}
    r = requests.post(url, json=payload, timeout=35)
    r.raise_for_status()
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram API error calling {method}: {body}")
    return body["result"]


def send_message(chat_id, text: str) -> None:
    _call("sendMessage", chat_id=chat_id, text=text)


def _reply_from(result: dict) -> str:
    if result.get("__interrupt__"):
        return result["__interrupt__"][0].value
    return result["messages"][-1].content


def handle_message(text: str, chat_id) -> None:
    logger.info("message received chat_id=%s len=%d", chat_id, len(text))
    config = {"configurable": {"thread_id": str(chat_id)}}
    if graph.get_state(config).next:
        result = graph.invoke(Command(resume=text), config)
    else:
        result = graph.invoke({"messages": [("user", text)]}, config)
    send_message(chat_id, _reply_from(result))


def _polling_loop() -> None:
    offset = None
    while True:
        try:
            updates = _call("getUpdates", offset=offset, timeout=30)
        except requests.RequestException:
            time.sleep(5)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message") or {}
            text = message.get("text")
            chat_id = (message.get("chat") or {}).get("id")
            if text and chat_id:
                handle_message(text, chat_id)


if __name__ == "__main__":
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _polling_loop()
