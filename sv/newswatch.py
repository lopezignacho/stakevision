"""Noticias de los partidos que pronosticamos, como contenido extra para Instagram.

Flujo:
1) Vigía (cada 2 h): titulares de ESPN de los equipos de nuestros picks (de ayer, hoy y mañana).
   Cada titular nuevo te llega por Telegram con «✅ Sí, prepárala» / «✖️ No».
2) Al tocar «Sí», queda en data/news_requests.json. Claude la redacta en español con datos verificados
   (tarea programada) y la deja en data/news_ready.json.
3) El bot arma la imagen (foto libre de Commons si hay; si no, colores del equipo) y te la manda con
   «📸 Publicar en Instagram». Solo sale a Instagram (no a los canales de Telegram).
Una entrada de news_ready con "approved": true (porque ya la aprobaste en el chat) se publica sin volver a preguntar.
"""
from __future__ import annotations

import html
import json
import os
import traceback
from datetime import datetime, timedelta, timezone

import requests

from . import config, formatting, store, telegram

REQ = os.path.join(config.ROOT, "data", "news_requests.json")
READY = os.path.join(config.ROOT, "data", "news_ready.json")
CHECK_EVERY_H = 2
MAX_PER_CHECK = 3
SOCCER_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary"


def BUTTONS(nid: str) -> list:
    return [[("✅ Sí, prepárala", f"nq:{nid}"), ("✖️ No", f"nx:{nid}")]]


def PUBLISH_BUTTONS(nid: str) -> list:
    return [[("📸 Publicar en Instagram", f"np:{nid}"), ("✖️ No publicar", f"nn:{nid}")]]


def _load(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return []


def _save(path: str, rows: list) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- 1) vigía
def _our_games(state: dict) -> list[dict]:
    """Partidos de nuestros picks (candidatos, aprobados, publicados o recién cerrados): ayer, hoy y mañana."""
    now = store.now_utc()
    out, seen = [], set()
    for p in state["picks"].values():
        if p.get("status") not in ("candidate", "selected", "published", "settled") or p.get("news"):
            continue
        for l in p.get("legs") or []:
            ko = store.parse_ts(l.get("kickoff") or p["kickoff"])
            if not (now - timedelta(hours=30) <= ko <= now + timedelta(hours=30)):
                continue
            key = (l["home"], l["away"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"pid": p["id"], "home": l["home"], "away": l["away"], "kickoff": l.get("kickoff") or p["kickoff"],
                        "sport": l.get("sport") or "soccer", "status": p["status"]})
    return out


def _articles(g: dict) -> list[dict]:
    """Artículos de ESPN del partido y de sus equipos."""
    arts = []
    if g["sport"] == "basketball":
        from . import nba
        found = nba.find_event(g["home"], g["away"], g["kickoff"])
        if not found:
            return []
        e = found[0]
        arts += ((nba._get("/summary", event=e.get("id")) or {}).get("news") or {}).get("articles") or []
        for c in e["competitions"][0]["competitors"]:
            tid = (c.get("team") or {}).get("id")
            if tid:
                arts += nba._get("/news", team=tid, limit=8).get("articles") or []
    else:
        from . import espn
        found = espn._find(g["home"], g["away"], g["kickoff"])
        if not found:
            return []
        try:
            sm = requests.get(SOCCER_SUMMARY, params={"event": found[0]["id"]}, timeout=25).json()
        except Exception:  # noqa: BLE001
            sm = {}
        arts += ((sm.get("news") or {}).get("articles")) or []
    return arts


def _plain(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


def check(state: dict, force: bool = False) -> int:
    """Busca titulares nuevos de nuestros partidos y te los manda para decidir. Devuelve cuántos mandó."""
    owner = state.get("owner_chat")
    if not owner:
        return 0
    now = store.now_utc()
    nx = state.get("news_next")
    if not force and nx and now < store.parse_ts(nx):
        return 0
    state["news_next"] = (now + timedelta(hours=CHECK_EVERY_H)).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen = state.setdefault("news_seen", [])
    sent = 0
    since = now - timedelta(hours=18)
    for g in _our_games(state):
        try:
            arts = _articles(g)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            continue
        names = [_plain(n).split()[-1] for n in (g["home"], g["away"])]
        for a in arts:
            aid = str(a.get("id") or a.get("headline") or "")
            head = html.unescape((a.get("headline") or "").strip())
            if not aid or aid in seen or not head:
                continue
            try:
                when = datetime.fromisoformat((a.get("published") or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            if when < since:
                continue
            text = _plain(head + " " + (a.get("description") or ""))
            if not any(n in text for n in names):
                continue
            seen.append(aid)
            link = (((a.get("links") or {}).get("web") or {}).get("href")) or ""
            nid = f"n{len(seen)}{now.strftime('%d%H%M')}"
            pend = state.setdefault("news_pending", {})
            pend[nid] = {"id": nid, "headline": head, "description": html.unescape(a.get("description") or ""),
                         "link": link, "published": a.get("published"), "pick": g["pid"],
                         "home": g["home"], "away": g["away"], "sport": g["sport"]}
            esc = formatting.escape
            telegram.send(owner,
                          f"📰 <b>Noticia de un partido nuestro</b> · pick #{g['pid']} "
                          f"({esc(formatting.team(g['home']))} vs {esc(formatting.team(g['away']))})\n\n"
                          f"<b>{esc(head)}</b>\n" + (f"<i>{esc(pend[nid]['description'])}</i>\n" if pend[nid]["description"] else "")
                          + (f"🔗 {esc(link)}\n" if link else "") + "\n¿La preparamos para Instagram?",
                          BUTTONS(nid))
            sent += 1
            if sent >= MAX_PER_CHECK:
                break
        if sent >= MAX_PER_CHECK:
            break
    del seen[:-400]
    return sent


def request(state: dict, nid: str) -> bool:
    """«Sí, prepárala»: queda pedida para que Claude la redacte en español con datos verificados."""
    item = (state.get("news_pending") or {}).pop(nid, None)
    if not item:
        return False
    rows = _load(REQ)
    item.update(status="pending", requested_at=store.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"))
    rows.append(item)
    _save(REQ, rows[-50:])
    return True


# ---------------------------------------------------------------- 3) listas para publicar
def _render(item: dict) -> tuple[bytes, str | None]:
    from . import commons, newsimage
    photo, credit = None, None
    try:
        got = None
        if item.get("photo_file"):
            got = commons.file_photo(item["photo_file"])
        elif item.get("player"):
            got = commons.player_photo(item["player"], item.get("teams") or [], need_team=True)
        if got:
            photo = got[0]
            cr = got[1] or {}
            credit = f"Foto de referencia: {cr.get('author')} / Wikimedia Commons ({cr.get('license')}), modificada"
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    n = {k: item[k] for k in ("tag", "kicker", "headline", "sub", "facts", "status") if k in item}
    n["colors"] = [tuple(c) for c in item.get("colors") or [(30, 40, 60), (80, 90, 110)]]
    n["source"] = "Fuentes: " + item.get("sources", "ESPN")
    if photo:
        n["photo"], n["credit"] = photo, credit
    return newsimage.render_news(n), credit


def ready(state: dict) -> None:
    """Noticias ya redactadas (data/news_ready.json): imagen + texto. Te llegan para aprobar o, si ya la
    aprobaste en el chat (approved), se publican directo en Instagram."""
    owner = state.get("owner_chat")
    if not owner:
        return
    from . import instagram
    done = state.setdefault("news_done", [])
    for item in _load(READY):
        nid = item.get("id")
        if not nid or nid in done:
            continue
        done.append(nid)
        try:
            img, _credit = _render(item)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            telegram.send(owner, f"⚠️ No pude armar la noticia {formatting.escape(nid)}: {formatting.escape(str(e))}")
            continue
        key = f"news-{nid}"
        instagram.save_image(key, img)
        job = {"key": key, "caption": item["caption"], "status": "draft", "title": item.get("headline", "")}
        state.setdefault("ig_jobs", {})[nid] = job
        if item.get("approved"):
            job["status"] = "queued"
            msg = telegram.send_photo(owner, img, caption="📰 <b>Noticia para Instagram</b> (aprobada en el chat): "
                                      "se publica en unos minutos.")
        else:
            msg = telegram.send_photo(owner, img, caption="📰 <b>Noticia lista para Instagram</b>\n"
                                      "Abajo va el texto. ¿La publicamos? (solo Instagram)")
            telegram.send(owner, "<pre>" + formatting.escape(item["caption"]) + "</pre>")
            telegram.set_buttons(owner, msg["message_id"], PUBLISH_BUTTONS(nid))
    del done[:-200]


def callback(state: dict, cb: dict, action: str, nid: str) -> None:
    owner = state["owner_chat"]
    mid = cb["message"]["message_id"]
    if action == "nq":
        ok = request(state, nid)
        telegram.edit_buttons_off(owner, mid, "✅ Pedida: te llega lista para aprobar" if ok else "Ya estaba procesada")
        telegram.answer(cb["id"], "La preparo" if ok else "Ya procesada")
    elif action == "nx":
        (state.get("news_pending") or {}).pop(nid, None)
        telegram.edit_buttons_off(owner, mid, "✖️ Descartada")
        telegram.answer(cb["id"], "Descartada")
    elif action in ("np", "nn"):
        job = (state.get("ig_jobs") or {}).get(nid)
        if not job or job["status"] != "draft":
            telegram.answer(cb["id"], "Ya estaba procesada")
            return
        job["status"] = "queued" if action == "np" else "skipped"
        telegram.edit_buttons_off(owner, mid, "⏳ Se publica en Instagram en unos minutos" if action == "np"
                                  else "✖️ No se publica")
        telegram.answer(cb["id"], "Listo")


def publish_jobs(state: dict) -> None:
    """Publica en Instagram las noticias aprobadas (cuando la imagen ya está en la web)."""
    from . import instagram
    owner = state.get("owner_chat")
    for nid, job in (state.get("ig_jobs") or {}).items():
        if job.get("status") != "queued" or not instagram.image_live(job["key"]):
            continue
        try:
            link = instagram.publish(state, job["key"], job["caption"])
            job["status"] = "posted"
            if owner:
                telegram.send(owner, "✅ Noticia publicada en Instagram" + (f"\n{link}" if link else ""))
        except instagram.InstagramError as e:
            job["tries"] = job.get("tries", 0) + 1
            if job["tries"] >= 3:
                job["status"] = "failed"
                if owner:
                    telegram.send(owner, f"⚠️ No pude publicar la noticia en Instagram: {formatting.escape(str(e))}")
