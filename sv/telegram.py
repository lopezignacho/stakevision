"""Bot de Telegram (API HTTP directa, sin librerías extra)."""
from __future__ import annotations

import requests

from . import config


class TelegramError(RuntimeError):
    pass


def _call(method: str, **payload):
    if not config.TELEGRAM_TOKEN:
        raise TelegramError("Falta TELEGRAM_TOKEN")
    r = requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/{method}",
                      json=payload, timeout=40)
    data = r.json()
    if not data.get("ok"):
        # Nunca incluir el token en el error.
        raise TelegramError(f"{method}: {data.get('description')}")
    return data["result"]


def send(chat_id, text: str, buttons: list[list[tuple[str, str]]] | None = None,
         reply_to: int | None = None) -> dict:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": [
            [{"text": t, "callback_data": d} for t, d in row] for row in buttons]}
    if reply_to:
        payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    return _call("sendMessage", **payload)


def edit_buttons_off(chat_id, message_id: int, note: str) -> None:
    try:
        _call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
              reply_markup={"inline_keyboard": [[{"text": note, "callback_data": "noop"}]]})
    except TelegramError:
        pass


def answer(callback_id: str, text: str = "") -> None:
    try:
        _call("answerCallbackQuery", callback_query_id=callback_id, text=text)
    except TelegramError:
        pass


def updates(offset: int) -> list[dict]:
    return _call("getUpdates", offset=offset, timeout=0,
                 allowed_updates=["message", "callback_query", "channel_post"])
