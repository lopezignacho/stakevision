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


def send_photo(chat_id, photo: bytes, caption: str | None = None, reply_to: int | None = None) -> dict:
    import json
    if not config.TELEGRAM_TOKEN:
        raise TelegramError("Falta TELEGRAM_TOKEN")
    data = {"chat_id": chat_id}
    if caption:
        data.update(caption=caption, parse_mode="HTML")
    if reply_to:
        data["reply_parameters"] = json.dumps({"message_id": reply_to, "allow_sending_without_reply": True})
    r = requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendPhoto",
                      data=data, files={"photo": ("pick.jpg", photo, "image/jpeg")}, timeout=60)
    res = r.json()
    if not res.get("ok"):
        raise TelegramError(f"sendPhoto: {res.get('description')}")
    return res["result"]


def set_buttons(chat_id, message_id: int, buttons: list[list[tuple[str, str]]]) -> None:
    try:
        _call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
              reply_markup={"inline_keyboard": [
                  [{"text": t, "callback_data": d} for t, d in row] for row in buttons]})
    except TelegramError:
        pass


def answer(callback_id: str, text: str = "") -> None:
    try:
        _call("answerCallbackQuery", callback_query_id=callback_id, text=text)
    except TelegramError:
        pass


def updates(offset: int, wait: int = 0) -> list[dict]:
    """wait > 0: espera hasta esos segundos a que llegue algo (respuesta inmediata a los botones)."""
    return _call("getUpdates", offset=offset, timeout=wait,
                 allowed_updates=["message", "callback_query", "channel_post"])


def edit_text(chat_id, message_id: int, text: str) -> None:
    _call("editMessageText", chat_id=chat_id, message_id=message_id, text=text,
          parse_mode="HTML", disable_web_page_preview=True)


def edit_caption(chat_id, message_id: int, caption: str) -> None:
    _call("editMessageCaption", chat_id=chat_id, message_id=message_id, caption=caption, parse_mode="HTML")


def download(file_id: str) -> bytes:
    """Descarga un archivo que te mandaron al bot (foto o documento)."""
    info = _call("getFile", file_id=file_id)
    r = requests.get(f"https://api.telegram.org/file/bot{config.TELEGRAM_TOKEN}/{info['file_path']}", timeout=60)
    if not r.ok:
        raise TelegramError("No se pudo descargar el archivo")   # sin URL: lleva el token
    return r.content
