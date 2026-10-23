"""Contactos personales del bot.

/enlace Juan  → enlace al bot (t.me/<bot>?start=<código>) para mandárselo a Juan.
Cuando Juan lo abre y toca Iniciar, el bot lo saluda, le entrega su invitación VIP de un uso
y te avisa. Desde ahí le puedes escribir con /mensaje Juan ... (Telegram no deja que un bot
escriba primero a nadie: la persona siempre tiene que tocar Iniciar).
"""
from __future__ import annotations

import secrets
from datetime import timedelta

from . import config, formatting, store, telegram

FREE_LINK = "https://t.me/stakevision"


def _now_iso() -> str:
    return store.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def bot_username(state: dict) -> str:
    if not state.get("bot_username"):
        state["bot_username"] = (telegram._call("getMe") or {}).get("username") or ""
    return state["bot_username"]


def _vip_invite(state: dict, name: str, days: int = 7) -> str | None:
    if not state.get("vip_chat"):
        return None
    expire = int((store.now_utc() + timedelta(days=days)).timestamp())
    try:
        link = telegram._call("createChatInviteLink", chat_id=state["vip_chat"], name=name[:32],
                              member_limit=1, expire_date=expire)
    except telegram.TelegramError as e:
        print(f"No se pudo crear la invitación VIP: {e}")
        return None
    state.setdefault("invites", []).append({"name": name[:32], "link": link["invite_link"],
                                            "created": _now_iso(), "days": days})
    return link["invite_link"]


def link_command(state: dict, text: str) -> None:
    """/enlace Nombre [gratis] — enlace personal al bot (con VIP por defecto; «gratis» solo canal gratis)."""
    owner = state["owner_chat"]
    parts = text.split(maxsplit=1)
    body = parts[1].strip() if len(parts) > 1 else ""
    free_only = body.lower().endswith(" gratis") or body.lower() == "gratis"
    name = body[:-7].strip() if body.lower().endswith(" gratis") else ("" if body.lower() == "gratis" else body)
    if not name:
        telegram.send(owner, "Usa /enlace y el nombre, por ejemplo /enlace Juan\n"
                             "(agrega «gratis» al final si solo quieres invitarlo al canal gratis).")
        return
    code = secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")
    state.setdefault("guest_codes", {})[code] = {"name": name[:40], "created": _now_iso(), "vip": not free_only}
    user = bot_username(state)
    telegram.send(owner, f"🔗 Enlace personal para <b>{formatting.escape(name)}</b>"
                         f"{' (canal gratis)' if free_only else ' (con acceso VIP)'}:\n"
                         f"https://t.me/{user}?start={code}\n\n"
                         "Mándaselo. Cuando lo abra y toque <b>Iniciar</b>, te aviso y ya le podré escribir "
                         f"con /mensaje {formatting.escape(name)} …")


def handle_start(state: dict, msg: dict) -> None:
    """/start de alguien que no es el dueño (con o sin código personal)."""
    chat = msg["chat"]["id"]
    who = msg.get("from") or {}
    text = (msg.get("text") or "").strip()
    code = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
    contacts = state.setdefault("contacts", {})
    info = (state.get("guest_codes") or {}).get(code)
    owner = state.get("owner_chat")
    if info and info.get("used_by") not in (None, chat):
        info = None   # cada enlace personal sirve para una sola persona
    c = contacts.setdefault(str(chat), {"joined": _now_iso()})
    c.update(tg_name=(who.get("first_name") or "")[:40], username=who.get("username") or "")
    if info:
        info["used_by"] = chat
        c["name"] = info["name"]
    name = c.get("name") or c.get("tg_name") or "crack"
    lines = [f"👋 ¡Hola {formatting.escape(name)}! Bienvenido a <b>Stakevision</b> 👁",
             "Pronósticos de fútbol con valor, analizados con datos y publicados antes de cada partido."]
    if info and info.get("vip"):
        invite = c.get("vip_link") or _vip_invite(state, name)
        if invite:
            c["vip_link"] = invite
            lines += ["", "🎟 Te invitaron al <b>canal VIP</b>. Este es tu acceso personal "
                          "(sirve solo para ti y vence en 7 días):", invite]
    lines += ["", f"🎁 Canal gratis con 1 pick al día: {FREE_LINK}",
              "", "🔞 Contenido solo para mayores de 18 años. Apuesta con responsabilidad: "
                  "solo dinero que puedas perder."]
    telegram.send(chat, "\n".join(lines))
    if owner and chat != owner:
        uname = f" (@{c['username']})" if c.get("username") else ""
        what = "y recibió su acceso VIP" if info and info.get("vip") and c.get("vip_link") else \
            "con su enlace personal" if info else "por su cuenta"
        telegram.send(owner, f"👤 <b>{formatting.escape(c.get('name') or c.get('tg_name') or '?')}</b>{formatting.escape(uname)} "
                             f"entró al bot {what}.")


def _find(state: dict, name: str) -> list[tuple[str, dict]]:
    n = name.lower().lstrip("@")
    out = []
    for cid, c in (state.get("contacts") or {}).items():
        names = {(c.get("name") or "").lower(), (c.get("tg_name") or "").lower(), (c.get("username") or "").lower()}
        if n in names:
            out.append((cid, c))
    return out


def message_command(state: dict, text: str) -> None:
    """/mensaje Nombre texto — le escribe a un contacto que ya inició el bot."""
    owner = state["owner_chat"]
    parts = text.split(maxsplit=1)
    body = parts[1] if len(parts) > 1 else ""
    contacts = state.get("contacts") or {}
    # el nombre puede tener espacios: se prueba el más largo que calce
    words = body.split()
    for k in range(min(4, len(words) - 1), 0, -1):
        hits = _find(state, " ".join(words[:k]))
        if hits:
            msg = " ".join(words[k:])
            if len(hits) > 1:
                telegram.send(owner, "Hay más de un contacto con ese nombre; usa su @usuario.")
                return
            cid, c = hits[0]
            try:
                telegram.send(int(cid), formatting.escape(msg))
                telegram.send(owner, f"✉️ Enviado a {formatting.escape(c.get('name') or c.get('tg_name'))}.")
            except telegram.TelegramError as e:
                telegram.send(owner, f"⚠️ No pude escribirle (quizás bloqueó el bot): {formatting.escape(str(e))}")
            return
    lista = ", ".join(c.get("name") or c.get("tg_name") or "?" for c in contacts.values()) or "nadie todavía"
    telegram.send(owner, "Usa /mensaje Nombre texto. Contactos que ya iniciaron el bot: " + formatting.escape(lista))


def contacts_command(state: dict) -> None:
    owner = state["owner_chat"]
    cs = state.get("contacts") or {}
    if not cs:
        telegram.send(owner, "Todavía nadie inició el bot. Crea un enlace con /enlace Nombre.")
        return
    rows = []
    for c in cs.values():
        u = f" @{c['username']}" if c.get("username") else ""
        vip = " · 🎟 VIP" if c.get("vip_link") else ""
        rows.append(f"• {formatting.escape(c.get('name') or c.get('tg_name') or '?')}{formatting.escape(u)}{vip}")
    telegram.send(owner, "👥 <b>Contactos del bot</b>\n" + "\n".join(rows))
