"""Punto de entrada.

    python -m sv.main scan    # busca valor y te manda candidatos (1 vez al día)
    python -m sv.main poll    # procesa tus botones, publica y pide resultados (cada ~10 min)
    python -m sv.main setup   # descarga la lista de mercados (1 vez)
"""
from __future__ import annotations

import os
import re
import sys
import traceback
from datetime import timedelta

from . import apifootball, config, formatting, oddspapi, store, telegram
from .value import build_picks, selections_for_fixture

CANDIDATE_BUTTONS = lambda pid: [  # noqa: E731
    [("🖼 Elegir y generar imagen", f"s:{pid}")],
    [("❌ Descartar", f"r:{pid}")],
]


def _image_row(p: dict) -> list:
    """Antes del partido el pick sale como cupón (solo la apuesta). Tu imagen es opcional y se puede deshacer."""
    if p.get("pick_style") == "photo":
        return [("🧾 Volver al cupón", f"st:{p['id']}"), ("🖼 Adjuntar otra imagen", f"yp:{p['id']}")]
    return [("🖼 Adjuntar mi imagen", f"yp:{p['id']}")]


def SHARE_BUTTONS(p: dict) -> list:
    """Destinos para un pick elegido. Cada uno se puede usar; lo ya hecho queda marcado."""
    pid, msgs = p["id"], p.get("channel_msgs") or {}
    rows = []
    vip_done, free_done = "vip" in msgs, "free" in msgs
    if _vip_only(p):   # NBA y Bet Builder: exclusivos del canal VIP (sin Gratis ni Instagram antes del partido)
        rows.append([("✅ En VIP" if vip_done else "👑 Enviar a VIP", "noop" if vip_done else f"pv:{pid}")])
        if p.get("kind") == "builder":
            if not msgs:
                rows.append([("❌ Descartar", f"r:{pid}")])
            return rows
        rows.append(_image_row(p))
        if not msgs:
            rows.append([("❌ Descartar", f"r:{pid}")])
        return rows
    if not vip_done and not free_done:
        rows.append([("👑 Enviar a VIP", f"pv:{pid}"), ("🎁 Enviar a Gratis", f"pg:{pid}")])
        rows.append([("👑🎁 Enviar a VIP + Gratis", f"pf:{pid}")])
    elif not free_done:
        rows.append([("✅ En VIP", "noop"), ("🎁 Agregar a Gratis", f"pg:{pid}")])
    elif not vip_done:
        rows.append([("👑 Agregar a VIP", f"pv:{pid}"), ("✅ En Gratis", "noop")])
    else:
        rows.append([("✅ En VIP + Gratis", "noop")])
    st = p.get("ig_pre_status")
    rows.append([("✅ Instagram" if st == "posted" else "⏳ Instagram en cola" if st == "queued"
                  else "📸 Compartir en Instagram", "noop" if st in ("queued", "posted") else f"pi:{pid}")])
    rows.append(_image_row(p))
    rows.append([("📲 Adelanto (historia)", f"ad:{pid}")])
    if not msgs and not st:
        rows.append([("❌ Descartar", f"r:{pid}")])
    return rows


def _vip_only(p: dict) -> bool:
    """Regla: la NBA es exclusiva del VIP; el gratis del día siempre es fútbol."""
    return (any((l.get("sport") or "soccer") == "basketball" for l in p.get("legs") or [])
            or p.get("sport") == "basketball" or p.get("kind") == "builder")


def _share_panel(state: dict, p: dict) -> None:
    """Te manda la imagen del pick con los botones de destino (VIP, VIP + Gratis, Instagram)."""
    owner = state.get("owner_chat")
    if not owner:
        return
    tier = "free" if (p.get("auto_free") or p.get("free")) and not _vip_only(p) else "vip"
    image = _pick_image(p, tier)
    look = ("" if _vip_only(p) else
            "\n🎨 En VIP sale en dorado con «PICK VIP»; en Gratis e Instagram, en verde con «PICK GRATIS».")
    head = (f"🖼 <b>Pick #{p['id']} listo para compartir</b>{look}\n"
            "Elige dónde publicarlo (puedes usar varios botones). Este es el texto que sale con la imagen:")
    text = formatting.channel_post(p, tier)
    full = f"{head}\n\n{text}"
    together = bool(image) and formatting.caption_fits(full)
    caption = full if together else head
    msg = telegram.send_photo(owner, image, caption=caption) if image else telegram.send(owner, caption)
    p["share_msg"] = msg["message_id"]
    telegram.set_buttons(owner, p["share_msg"], SHARE_BUTTONS(p))
    if not together:
        telegram.send(owner, text)


def _share_command(state: dict, text: str) -> None:
    owner = state["owner_chat"]
    parts = text.split()
    pid = parts[1].lstrip("#") if len(parts) > 1 else ""
    p = state["picks"].get(pid)
    if not p:
        recent = [x for x in state["picks"].values() if x["status"] in ("selected", "published", "settled")]
        recent.sort(key=lambda x: int(x["id"]), reverse=True)
        lista = "\n".join(f"#{x['id']} · {formatting.escape(x['legs'][0]['home'])} vs "
                           f"{formatting.escape(x['legs'][0]['away'])}" for x in recent[:6])
        telegram.send(owner, "Usa /compartir y el número del pick, por ejemplo /compartir 8"
                      + (f"\n\nÚltimos picks:\n{lista}" if lista else ""))
        return
    if p["status"] == "rejected" and _expires(p) > store.now_utc():   # recuperar un descarte
        p["status"] = "selected"
        p.pop("prev_status", None)
        telegram.send(owner, f"↩️ Recuperé el pick #{p['id']}.")
    if p["status"] in ("selected", "published"):
        _share_panel(state, p)
    elif p["status"] in ("settled", "news") and p.get("recap") and os.path.exists(_recap_file(p)):
        _recap_panel(state, p)
    elif p["status"] == "settled" and p.get("result") == "W":
        p["ig_kit_sent"] = False
        if p.get("ig_status") not in ("queued", "posted"):
            p.pop("ig_status", None)
        _instagram_kit(state, p)
    else:
        telegram.send(owner, f"El pick #{pid} no se puede compartir ({p['status']}"
                      + (f", resultado {p.get('result')}" if p.get("result") else "") + ").")


def _expires(p: dict):
    """Un candidato en vivo vence a los 20 minutos (las cuotas cambian); uno normal, al empezar el partido."""
    if p.get("live"):
        return store.parse_ts(p["created_at"]) + timedelta(minutes=config.LIVE_CANDIDATE_MIN)
    return store.parse_ts(p["kickoff"])
RESULT_BUTTONS = lambda pid: [  # noqa: E731
    [("✅ Verde", f"W:{pid}"), ("❌ Roja", f"L:{pid}"), ("↩️ Nula", f"V:{pid}")],
]


def _local_today() -> str:
    from zoneinfo import ZoneInfo
    return store.now_utc().astimezone(ZoneInfo(config.TIMEZONE)).date().isoformat()


def _end_of_today():
    """23:59:59 de hoy en hora de Chile, en UTC."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(config.TIMEZONE)
    local = store.now_utc().astimezone(tz)
    return local.replace(hour=23, minute=59, second=59, microsecond=0).astimezone(store.now_utc().tzinfo)


def _is_today(iso: str) -> bool:
    from zoneinfo import ZoneInfo
    return store.parse_ts(iso).astimezone(ZoneInfo(config.TIMEZONE)).date().isoformat() == _local_today()


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- escaneo diario
def scan(hours: int | None = None, top: int | None = None, manual: bool = False, live: bool = False) -> None:
    """Escaneo de fútbol y, en el diario, también de la NBA."""
    state = store.load()
    if not state["owner_chat"]:
        print("Aún no está vinculado tu chat. Escribe al bot: /vincular <tu código>")
        return
    if not manual and not live:   # el escaneo diario sale una sola vez (lo pueden lanzar dos caminos)
        today = _local_today()
        if state.get("auto_scan_date") == today:
            print("El escaneo de hoy ya salió.")
            return
        state["auto_scan_date"] = today
        store.save(state)
    try:
        _scan_soccer(hours, top, manual, live)
    finally:
        if not manual and not live and config.NBA_ENABLED and config.NBA_DAILY_SCAN:
            try:
                scan_nba()
            except Exception:
                traceback.print_exc()
        if not manual and not live and config.AUTO_FREE:
            try:
                state = store.load()
                _auto_free_choose(state)
                store.save(state)
            except Exception:
                traceback.print_exc()
        if not manual and not live and config.DAILY_BUILDERS:
            try:
                state = store.load()
                _daily_builders(state)
                store.save(state)
            except Exception:
                traceback.print_exc()


# ---------------------------------------------------------------- pick gratis automático
AUTO_KEYS = ("legs", "price", "prob", "edge", "stake", "tier", "kind", "analysis")


def AUTO_FREE_BUTTONS(pid: str) -> list:
    return [[("🚀 Publicar ya", f"fa:{pid}"), ("🔁 Elegir otro", f"fo:{pid}")],
            [("✋ No publicar hoy", f"fc:{pid}")]]


def _auto_reject(p: dict, d: dict | None, lead) -> str | None:
    """Por qué una opción NO sirve para el gratis (None si sirve)."""
    if not d or len(d.get("legs") or []) != 1:
        return "no es una apuesta simple"
    if not _is_today(p["kickoff"]):
        return "el partido no es de hoy"
    if store.parse_ts(p["kickoff"]) < lead:
        return "empieza muy pronto para publicarlo con tiempo"
    if not (_min_odds(d) <= d["price"] <= config.ODDS_MAX):
        return f"la cuota {formatting.odds(d['price'])} está fuera del rango"
    if d["edge"] < config.AUTO_FREE_MIN_EDGE:
        return "la cuota está muy por debajo de la justa"
    ev = _leg_evidence(d["legs"][0])
    if ev and ev["verdict"] == "contra":
        return "los datos (forma y cara a cara) lo contradicen"
    from . import evidence
    pp = evidence.blend(d["prob"], ev)
    if pp < 1 / d["price"]:
        return (f"sin margen: le damos {round(pp * 100)}% y la cuota {formatting.odds(d['price'])} "
                f"pide {round(100 / d['price'])}%")
    return None


def _auto_pool(state: dict, publish_at, scored: bool = False) -> list:
    """Opciones del escaneo de hoy que sirven para el gratis, de la más probable a la menos.
    Si el escaneo de las 00:05 dejó su top 3, se elige solo entre esos."""
    lead = publish_at + timedelta(minutes=config.AUTO_FREE_MIN_LEAD_MIN)
    today = _local_today()
    from zoneinfo import ZoneInfo
    from . import evidence
    cands = []
    for p in state["picks"].values():
        if p["status"] != "candidate" or p.get("live") or p.get("kind") != "simple" or _vip_only(p):
            continue   # el gratis siempre es fútbol
        made = store.parse_ts(p["created_at"]).astimezone(ZoneInfo(config.TIMEZONE)).date().isoformat()
        if made == today:
            cands.append(p)
    if any(p.get("daily_top") == today for p in cands):
        cands = [p for p in cands if p.get("daily_top") == today]
    pool = []
    for p in cands:
        for opt, d in (("A", p), ("B", p.get("alt"))):
            if not d or _auto_reject(p, d, lead):
                continue
            ev = _leg_evidence(d["legs"][0])
            rank = 2 if ev and ev["verdict"] == "ok" else 1 if not ev else 0
            pool.append((rank, evidence.blend(d["prob"], ev), d["edge"], p["id"], opt))
    # primero los que los datos respaldan; luego la probabilidad final (mercado + datos); luego el valor
    pool.sort(key=lambda x: (x[0], round(x[1], 3), x[2]), reverse=True)
    if scored:
        return pool
    return [[pid, opt] for _rk, _pr, _ed, pid, opt in pool]


def _auto_free_reason(state: dict, p: dict, opt: str, publish_at) -> str:
    """«Por qué lo elegí»: comparación con los otros picks del top del día."""
    from . import evidence
    today = _local_today()
    lead = publish_at + timedelta(minutes=config.AUTO_FREE_MIN_LEAD_MIN)
    me = p
    l = me["legs"][0]
    ev = _leg_evidence(l)
    my_prob = evidence.blend(me["prob"], ev)
    rivals = [x for x in state["picks"].values() if x.get("daily_top") == today and x["id"] != p["id"]
              and x["status"] in ("candidate", "selected", "published", "expired")]
    rivals.sort(key=lambda x: int(x["id"]))
    out = ["🧠 <b>Por qué lo elegí</b>"]
    if ev and ev["verdict"] == "ok":
        out.append("• Los datos lo respaldan: " + evidence.line(ev).split(": ", 1)[-1].split(" → ")[0] + ".")
    elif ev:
        out.append("• Los datos acompañan a medias (" + evidence.line(ev).split(": ", 1)[-1].split(" → ")[0]
                   + "), pero es lo más sólido de hoy.")
    else:
        out.append("• Sin historial suficiente para contrastar: manda la probabilidad del mercado.")
    probs = []
    for x in rivals:
        why = _auto_reject(x, x, lead)
        if why:
            out.append(f"• #{x['id']} ({formatting.escape(x['legs'][0]['home'])} vs "
                       f"{formatting.escape(x['legs'][0]['away'])}) quedó fuera: {why}.")
        else:
            probs.append(evidence.blend(x["prob"], _leg_evidence(x["legs"][0])))
    if probs:
        out.insert(1, f"• Es el más probable del top: {formatting.pct(my_prob)} frente a "
                   + " y ".join(formatting.pct(q) for q in sorted(probs, reverse=True)) + ".")
    else:
        out.insert(1, f"• Probabilidad estimada (mercado + datos): {formatting.pct(my_prob)}.")
    fair = 1 / me["prob"] if me.get("prob") else None
    if fair:
        rel = "por encima de" if me["price"] > fair + 0.005 else "en línea con" if abs(me["price"] - fair) <= 0.005 else "apenas bajo"
        out.append(f"• Cuota {formatting.odds(me['price'])}, {rel} la justa ({formatting.odds(fair)}).")
    if opt == "B":
        out.append("• Uso la opción B del partido: es la más probable de las dos.")
    return "\n".join(out)


EVIDENCE_V = 4   # versión del contraste: si cambia la forma de calcularlo, se recalcula


def _evidence_note(l: dict) -> str:
    from . import evidence
    return evidence.line(_leg_evidence(l)) + "\n\n"


def _leg_evidence(l: dict) -> dict | None:
    """Contraste con datos (forma reciente + cara a cara), calculado una vez y guardado en la selección."""
    if "evidence" not in l or l.get("evidence_v") != EVIDENCE_V:
        l["evidence_v"] = EVIDENCE_V
        try:
            from . import evidence
            l["evidence"] = evidence.check(l)
        except Exception:
            traceback.print_exc()
            l["evidence"] = None
    return l["evidence"]


def _free_given_today(state: dict) -> bool:
    from zoneinfo import ZoneInfo
    today = _local_today()
    for p in state["picks"].values():
        if p.get("status") == "cancelled":
            continue
        if "free" in (p.get("channel_msgs") or {}) and p.get("published_at"):
            if store.parse_ts(p["published_at"]).astimezone(ZoneInfo(config.TIMEZONE)).date().isoformat() == today:
                return True
    return False


def _use_option(p: dict, opt: str) -> None:
    if opt == "B" and p.get("alt"):
        alt = p.pop("alt")
        p["alt_original"] = {k: p[k] for k in AUTO_KEYS}
        p.update({k: alt[k] for k in AUTO_KEYS})
        p["chosen_option"] = "B"


def _undo_option(p: dict) -> None:
    if p.get("chosen_option") == "B" and p.get("alt_original"):
        p["alt"] = {k: p[k] for k in AUTO_KEYS}
        p.update(p.pop("alt_original"))
        p.pop("chosen_option", None)


def _restore_candidate(state: dict, p: dict) -> None:
    """Devuelve el pick a candidato (con sus botones de siempre) si se cambia o cancela el automático."""
    _undo_option(p)
    p["status"] = "candidate"
    p.pop("auto_free", None)
    p.pop("pick_style", None)
    owner = state.get("owner_chat")
    if owner and p.get("owner_msg"):
        btns = NBA_BUTTONS(p["id"], bool(p.get("alt"))) if p.get("sport") == "basketball" else CANDIDATE_BUTTONS(p["id"])
        try:
            telegram.set_buttons(owner, p["owner_msg"], btns)
        except Exception:  # noqa: BLE001
            pass


def _auto_free_choose(state: dict, skip: list | None = None) -> bool:
    """Elige el pick gratis del día (el de mayor probabilidad justa dentro de 1.65-2.00) y te avisa
    con unos minutos para cancelarlo o cambiarlo antes de publicarlo."""
    owner = state.get("owner_chat")
    if not owner or state.get("auto_free_off"):
        return False
    today = _local_today()
    af = state.get("auto_free") or {}
    if af.get("date") == today and af.get("status") in ("pending", "published", "cancelled") and skip is None:
        return False
    if _free_given_today(state):
        return False
    now = store.now_utc()
    at = now + timedelta(minutes=config.AUTO_FREE_DELAY_MIN)
    pool = af.get("pool") if skip is not None and af.get("date") == today else _auto_pool(state, at)
    gone = {x[0] for x in skip or []}
    pool = [x for x in pool or [] if x[0] not in gone
            and (state["picks"].get(x[0]) or {}).get("status") == "candidate"]
    if not pool:
        state["auto_free"] = {"date": today, "status": "none", "pool": []}
        lead = at + timedelta(minutes=config.AUTO_FREE_MIN_LEAD_MIN)
        why = "\n".join(f"• #{x['id']} ({formatting.escape(x['legs'][0]['home'])} vs {formatting.escape(x['legs'][0]['away'])}): "
                        f"{_auto_reject(x, x, lead) or 'ya no está disponible'}"
                        for x in state["picks"].values() if x.get("daily_top") == today)
        telegram.send(owner, "🤖 Pick gratis automático: hoy ninguna opción de fútbol cumple (cuota en rango, cerca de la "
                             "cuota justa, partido de hoy y con tiempo antes de empezar)."
                      + (f"\n\n{why}" if why else "") + "\n\nSi quieres, elige uno a mano con /gratis N.")
        return False
    pid, opt = pool[0]
    p = state["picks"][pid]
    _use_option(p, opt)
    p["status"] = "selected"
    p["auto_free"] = True
    p["pick_style"] = "coupon"   # antes del partido: solo la apuesta (las fotos quedan para el final)
    if p.get("owner_msg"):
        telegram.edit_buttons_off(owner, p["owner_msg"], "🤖 Elegido como pick gratis automático (abajo)")
    state["auto_free"] = {"date": today, "status": "pending", "pid": pid, "opt": opt, "at": _iso(at),
                          "pool": pool, "tried": (af.get("tried") or []) + [[pid, opt]] if skip else [[pid, opt]]}
    l = p["legs"][0]
    from zoneinfo import ZoneInfo
    hhmm = at.astimezone(ZoneInfo(config.TIMEZONE)).strftime("%H:%M")
    where = "VIP + Gratis" if (config.AUTO_FREE_VIP_TOO and state.get("vip_chat")) else "Gratis"
    from . import instagram
    if config.AUTO_FREE_INSTAGRAM and instagram.enabled(state):
        where += " + Instagram"
    esc = formatting.escape
    others = len(pool) - 1
    cap = (f"🤖 <b>Pick gratis automático de hoy</b> · #{pid}" + (" (opción B)" if opt == "B" else "") + "\n"
           f"{'🏀' if l.get('sport') == 'basketball' else '⚽'} {esc(l['home'])} vs {esc(l['away'])}\n"
           f"🎯 <b>{esc(formatting.outcome_label(l))}</b> @ {formatting.odds(p['price'])}\n"
           f"📈 Probabilidad justa {formatting.pct(p['prob'])} · valor {'+' if p['edge'] >= 0 else ''}"
           f"{formatting.pct(p['edge'])}\n\n"
           + _auto_free_reason(state, p, opt, at) + "\n\n" +
           f"Se publica sola a las <b>{hhmm}</b> en {where}.\n"
           "Revisa la cuota en tu app. Puedes publicarlo ya, cambiarlo por la siguiente opción"
           + (f" (quedan {others})" if others else "") + " o no publicar gratis hoy.")
    image = _pick_image(p, "free")
    msg = telegram.send_photo(owner, image, caption=cap) if image else telegram.send(owner, cap)
    state["auto_free"]["msg"] = msg["message_id"]
    telegram.set_buttons(owner, msg["message_id"], AUTO_FREE_BUTTONS(pid))
    return True


def _auto_free_publish(state: dict, p: dict) -> None:
    owner = state.get("owner_chat")
    af = state["auto_free"]
    vip_too = config.AUTO_FREE_VIP_TOO and bool(state.get("vip_chat"))
    _publish(state, p, free=True, vip_too=vip_too)
    p["auto_free"] = True
    note = "✅ Publicado en " + ("VIP + Gratis" if vip_too else "Gratis")
    from . import instagram
    if config.AUTO_FREE_INSTAGRAM and instagram.enabled(state) and not p.get("ig_pre_status"):
        image = _pick_image(p, "free")
        if image:
            from . import postimage
            instagram.save_image(f"pre-{p['id']}", postimage.fit_instagram(image))
            p["ig_pre_status"] = "queued"
            p["ig_pre_caption"] = formatting.instagram_pick_caption(p)
            note += " · Instagram en cola"
    af["status"] = "published"
    if owner and af.get("msg"):
        telegram.edit_buttons_off(owner, af["msg"], note)
    if owner:
        _share_panel(state, p)   # por si quieres el adelanto para historias u otro diseño


def _auto_free_tick(state: dict, now) -> None:
    af = state.get("auto_free") or {}
    if af.get("status") != "pending" or now < store.parse_ts(af["at"]):
        return
    p = state["picks"].get(af.get("pid") or "")
    owner = state.get("owner_chat")
    if not p or p["status"] not in ("selected", "published") or "free" in (p.get("channel_msgs") or {}):
        af["status"] = "published" if p and "free" in (p.get("channel_msgs") or {}) else "cancelled"
        return
    if _free_given_today(state):
        af["status"] = "cancelled"
        if owner and af.get("msg"):
            telegram.edit_buttons_off(owner, af["msg"], "Ya publicaste un gratis hoy: no salió el automático")
        _restore_candidate(state, p)
        return
    if store.parse_ts(p["kickoff"]) - now < timedelta(minutes=15):
        af["status"] = "cancelled"
        if owner and af.get("msg"):
            telegram.edit_buttons_off(owner, af["msg"], "⌛ El partido está por empezar: no se publicó")
        return
    _auto_free_publish(state, p)


def _auto_recap_tick(state: dict, p: dict, now) -> None:
    """Post partido del pick gratis automático: se comparte solo en sus canales (e Instagram si fue verde)."""
    r = p.get("recap") or {}
    if (not r.get("auto_at") or r.get("auto_done") or r.get("auto_off") or now < store.parse_ts(r["auto_at"])
            or not os.path.exists(_recap_file(p))):
        return
    r["auto_done"] = True
    done = []
    for where in (p.get("channel_msgs") or {}):
        if where in r["msgs"] or (where == "vip" and not state.get("vip_chat")):
            continue
        try:
            _recap_share(state, p, where)
            done.append("VIP" if where == "vip" else "Gratis")
        except Exception:
            traceback.print_exc()
    from . import instagram
    if (p.get("result") == "W" and config.AUTO_FREE_INSTAGRAM and instagram.enabled(state)
            and p.get("ig_res_status") not in ("queued", "posted")):
        p["ig_res_status"] = "queued"
        p["ig_res_caption"] = r["ig"]
        done.append("Instagram (en cola)")
    owner = state.get("owner_chat")
    if owner:
        if r.get("panel"):
            telegram.set_buttons(owner, r["panel"], RECAP_BUTTONS(p))
        if done:
            telegram.send(owner, f"🤖 Compartí el post partido del pick #{p['id']} en " + ", ".join(done) + ".")


def _auto_free_callback(state: dict, cb: dict, action: str, p: dict) -> None:
    owner = state["owner_chat"]
    af = state.get("auto_free") or {}
    mid = cb["message"]["message_id"]
    if af.get("pid") != p["id"] or af.get("status") != "pending":
        telegram.answer(cb["id"], "Ya no está pendiente")
        telegram.edit_buttons_off(owner, mid, "Ya procesado")
        return
    if action == "fa":
        telegram.answer(cb["id"], "Publicando…")
        _auto_free_publish(state, p)
        return
    _restore_candidate(state, p)
    if action == "fc":
        af["status"] = "cancelled"
        telegram.edit_buttons_off(owner, mid, "✋ Hoy no sale el gratis automático (el pick volvió a candidatos)")
        telegram.answer(cb["id"], "Cancelado por hoy")
        return
    telegram.edit_buttons_off(owner, mid, "🔁 Cambiado por la siguiente opción (abajo)")
    telegram.answer(cb["id"], "Buscando la siguiente…")
    if not _auto_free_choose(state, skip=(af.get("tried") or []) + [[p["id"], af.get("opt")]]):
        state["auto_free"]["status"] = "none"


def _free_preview(state: dict) -> None:
    """/gratis prueba · muestra SOLO a ti qué pick elegiría ahora. No publica ni cambia nada del día."""
    import copy
    owner = state["owner_chat"]
    at = store.now_utc() + timedelta(minutes=config.AUTO_FREE_DELAY_MIN)
    pool = _auto_pool(state, at)
    if not pool:
        telegram.send(owner, "🧪 Prueba del pick gratis: no hay candidatos de hoy que cumplan (cuota 1.65–2.00, "
                             "cerca de la cuota justa y con 2 h antes del partido).\n"
                             "Lanza primero /buscar (o /buscar nba), espera los candidatos y repite /gratis prueba.")
        return
    pid, opt = pool[0]
    p = copy.deepcopy(state["picks"][pid])
    _use_option(p, opt)
    p["id"] = f"{pid}-prueba"
    p["pick_style"] = "coupon"
    l = p["legs"][0]
    esc = formatting.escape
    ranking = []
    for i, (xid, xo) in enumerate(pool[:5], 1):
        x = copy.deepcopy(state["picks"][xid])
        _use_option(x, xo)
        xl = x["legs"][0]
        ranking.append(f"{i}. {esc(xl['home'])} vs {esc(xl['away'])} · {esc(formatting.outcome_label(xl))} @ "
                       f"{formatting.odds(x['price'])} · {formatting.pct(x['prob'])}")
    cap = (f"🧪 <b>Prueba · pick gratis automático</b> (solo tú lo ves, no se publica)\n"
           f"{'🏀' if l.get('sport') == 'basketball' else '⚽'} {esc(l['home'])} vs {esc(l['away'])}\n"
           f"🎯 <b>{esc(formatting.outcome_label(l))}</b> @ {formatting.odds(p['price'])}\n"
           f"📈 Probabilidad justa {formatting.pct(p['prob'])} · valor {'+' if p['edge'] >= 0 else ''}"
           f"{formatting.pct(p['edge'])}")
    image = _pick_image(p, "free")
    if image and formatting.caption_fits(cap):
        telegram.send_photo(owner, image, caption=cap)
    else:
        if image:
            telegram.send_photo(owner, image)
        telegram.send(owner, cap)
    telegram.send(owner, "🏆 <b>Ranking de opciones de hoy</b> (más probable primero):\n" + "\n".join(ranking)
                  + "\n\nCon el automático encendido, a las 00:05 elegiría el n.º 1 entre los candidatos de ese "
                    "escaneo y te daría 30 min para cambiarlo o cancelarlo.")
    try:
        os.remove(_pick_photo_file(p))
        os.remove(_upload_file(p, "pickphoto"))
    except OSError:
        pass


def _force_free(state: dict, pid: str, opt: str = "A") -> str:
    """Usa un pick elegido por ti como el gratis de hoy y lo publica ya (VIP + Gratis + Instagram)."""
    p = state["picks"].get(pid)
    now = store.now_utc()
    if not p:
        return f"No encuentro el pick #{pid}."
    if _vip_only(p):
        return f"El pick #{pid} es de NBA: la NBA es exclusiva del VIP. El gratis del día tiene que ser fútbol."
    if not _is_today(p["kickoff"]):
        return f"El pick #{pid} no se juega hoy: el gratis tiene que ser de un partido del día."
    if "free" in (p.get("channel_msgs") or {}):
        return f"El pick #{pid} ya estaba en el canal Gratis."
    if p["status"] not in ("candidate", "selected", "published"):
        return f"El pick #{pid} ya no está disponible ({p['status']})."
    if store.parse_ts(p["kickoff"]) - now < timedelta(minutes=15) and not p.get("live"):
        return f"El partido del pick #{pid} ya empezó o está por empezar: no se publica."
    if p.get("live") and _expires(p) <= now:
        return f"El pick en vivo #{pid} venció (las cuotas en vivo duran 20 min)."
    if _free_given_today(state):
        return "Hoy ya salió un pick en el canal Gratis."
    af = state.get("auto_free") or {}
    other = state["picks"].get(af.get("pid") or "")
    if af.get("status") == "pending" and other and other["id"] != pid:   # reemplaza al automático pendiente
        _restore_candidate(state, other)
        if af.get("msg") and state.get("owner_chat"):
            telegram.edit_buttons_off(state["owner_chat"], af["msg"], f"🔁 Reemplazado por el pick #{pid}")
    if p["status"] == "candidate":
        _use_option(p, "B" if opt.upper() == "B" else "A")
        p["status"] = "selected"
        if p.get("owner_msg") and state.get("owner_chat"):
            telegram.edit_buttons_off(state["owner_chat"], p["owner_msg"], "🤖 Elegido como pick gratis de hoy")
    p["auto_free"] = True
    if p.get("pick_style") == "photo" and not p.get("pick_raw"):
        p["pick_style"] = "coupon"
    state["auto_free"] = {"date": _local_today(), "status": "pending", "pid": pid, "opt": opt.upper(),
                          "at": _iso(now), "pool": [], "manual": True}
    _auto_free_publish(state, p)
    return ""


def _force_free_file(state: dict) -> None:
    """data/force_free.json ({"id": "...", "pid": "37", "opt": "A"}): elegir el gratis de hoy desde el repo, una vez."""
    import json
    path = os.path.join(config.ROOT, "data", "force_free.json")
    if not os.path.exists(path) or not state.get("owner_chat"):
        return
    try:
        with open(path, encoding="utf-8") as f:
            req = json.load(f)
    except Exception:  # noqa: BLE001
        return
    if not req.get("id") or req["id"] in (state.get("force_free_done") or []):
        return
    state.setdefault("force_free_done", []).append(req["id"])
    err = _force_free(state, str(req.get("pid", "")).lstrip("#"), req.get("opt") or "A")
    if err:
        telegram.send(state["owner_chat"], "⚠️ Pick gratis elegido: " + formatting.escape(err))


def _repair_pick(state: dict, pid: str) -> str:
    """Arregla un pick ya publicado con las reglas nuevas: imagen nueva (referente del equipo) y,
    si es NBA, lo saca del canal Gratis y de la cola de Instagram (la NBA es exclusiva del VIP)."""
    p = state["picks"].get(pid)
    if not p:
        return f"No encuentro el pick #{pid}."
    notes = []
    for f in (_upload_file(p, "pickphoto"), _pick_photo_file(p)):
        if os.path.exists(f):
            os.remove(f)
    p["pick_style"] = "coupon"
    image = _pick_image(p, "vip")
    msgs = p.setdefault("channel_msgs", {})
    if _vip_only(p) and "free" in msgs:
        ok = telegram.delete_message(config.FREE_CHANNEL, msgs["free"])
        if ok:
            msgs.pop("free")
            p["free"] = False
            notes.append("lo borré del canal Gratis")
        else:
            notes.append("⚠️ no pude borrarlo del canal Gratis (Telegram no lo permitió): bórralo a mano")
    if "vip" in msgs and state.get("vip_chat") and image:
        text = formatting.channel_post(p, "vip")
        if telegram.edit_photo(state["vip_chat"], msgs["vip"], image, text if formatting.caption_fits(text) else None):
            notes.append("cambié la imagen en el VIP (mismo mensaje)")
        else:
            telegram.send_photo(state["vip_chat"], image, caption="🖼 Imagen actualizada del pick 👆", reply_to=msgs["vip"])
            notes.append("mandé la imagen nueva en el VIP como respuesta al pick")
    if _vip_only(p):
        if p.get("ig_pre_status") == "queued":
            p["ig_pre_status"] = "skipped"
            try:
                from . import instagram
                os.remove(instagram.image_path(f"pre-{p['id']}"))
            except OSError:
                pass
            notes.append("lo saqué de la cola de Instagram")
        elif p.get("ig_pre_status") == "posted":
            notes.append("⚠️ ya estaba en Instagram: bórralo a mano desde la app (Instagram no deja borrarlo al bot)")
        p.pop("auto_free", None)
        af = state.get("auto_free") or {}
        if af.get("pid") == pid:
            state["auto_free"] = {}   # el gratis de hoy vuelve a elegirse (fútbol) tras el escaneo de las 00:05
            notes.append("el gratis de hoy se elegirá de nuevo, de fútbol, tras el escaneo de las 00:05")
    owner = state.get("owner_chat")
    if owner and image:
        cr = p.get("pick_photo_credit") or {}
        who = f" · {cr['player']}" if cr.get("player") else ""
        telegram.send_photo(owner, image, caption=f"🔧 <b>Pick #{pid} corregido</b>{formatting.escape(who)}\n"
                                                  + "\n".join(f"• {formatting.escape(n)}" for n in notes))
    return ""


def _fresh_evidence(p: dict) -> None:
    """Datos del partido al día (forma, localía, cara a cara, tabla) para el «por qué» del texto público."""
    for l in p.get("legs") or []:
        if (l.get("sport") or "soccer") == "soccer" and p.get("kind") != "builder":
            _leg_evidence(l)


def _refresh_post(state: dict, p: dict) -> list[str]:
    """Reescribe un pick ya publicado con el formato simple: mismo mensaje en Gratis y VIP (imagen + texto)
    y, para Instagram, la versión nueva lista para publicar (Instagram no deja al bot editar ni borrar)."""
    notes = []
    _fresh_evidence(p)
    p["pick_style"] = "coupon"
    for where, mid in (p.get("channel_msgs") or {}).items():
        chat = state.get("vip_chat") if where == "vip" else config.FREE_CHANNEL
        if not chat:
            continue
        tier = "vip" if where == "vip" else "free"
        text = formatting.channel_post(p, tier)
        image = _pick_image(p, tier)
        name = "VIP" if where == "vip" else "Gratis"
        fits = formatting.caption_fits(text)
        if image and fits and telegram.edit_photo(chat, mid, image, text):
            notes.append(f"{name}: imagen y texto nuevos (mismo mensaje)")
            continue
        try:   # el texto iba aparte (no cabía como pie de foto): texto en mid, foto justo antes
            telegram.edit_text(chat, mid, text)
            if image:
                telegram.edit_photo(chat, mid - 1, image)
            notes.append(f"{name}: texto nuevo" + (" e imagen nueva" if image else ""))
        except telegram.TelegramError as e:
            notes.append(f"⚠️ {name}: no pude editarlo ({e})")
    from . import instagram, postimage
    owner = state.get("owner_chat")
    if p.get("ig_pre_status") in ("queued", "posted") and not _vip_only(p):
        image = _pick_image(p, "free")
        cap = formatting.instagram_pick_caption(p)
        key = f"pre-{p['id']}-v{int(store.now_utc().timestamp())}"
        if image:
            instagram.save_image(key, postimage.fit_instagram(image))
        p["ig_pre_key"], p["ig_pre_caption"] = key, cap
        if p["ig_pre_status"] == "queued":
            notes.append("Instagram: aún no salía; saldrá con la versión nueva")
        elif owner and image:
            msg = telegram.send_photo(owner, image, caption="📸 <b>Instagram · versión nueva del pick #" + p["id"] + "</b>\n"
                                      "Instagram no deja al bot editar ni borrar publicaciones. Borra la publicación "
                                      "antigua desde la app y toca «Publicar versión nueva».")
            telegram.send(owner, "<pre>" + formatting.escape(cap) + "</pre>")
            telegram.set_buttons(owner, msg["message_id"], [[("📸 Publicar versión nueva", f"ip:{p['id']}")],
                                                            [("Dejar Instagram como está", f"ipn:{p['id']}")]])
            notes.append("Instagram: te mandé la versión nueva con el botón para publicarla")
    return notes


def _refresh_file(state: dict) -> None:
    """data/refresh.json ({"id": "...", "pid": "auto" | "80"}): reescribe un pick publicado con el formato simple."""
    import json
    path = os.path.join(config.ROOT, "data", "refresh.json")
    owner = state.get("owner_chat")
    if not os.path.exists(path) or not owner:
        return
    try:
        with open(path, encoding="utf-8") as f:
            req = json.load(f)
    except Exception:  # noqa: BLE001
        return
    if not req.get("id") or req["id"] in (state.get("refresh_done") or []):
        return
    state.setdefault("refresh_done", []).append(req["id"])
    pid = str(req.get("pid") or "").lstrip("#")
    if pid == "auto":   # el gratis de hoy (automático o elegido a mano)
        af = state.get("auto_free") or {}
        pid = af.get("pid") if af.get("date") == _local_today() and af.get("status") == "published" else ""
        if not pid:
            todays = [x for x in state["picks"].values() if "free" in (x.get("channel_msgs") or {})
                      and x.get("published_at") and _is_today(x["published_at"]) and x.get("status") != "cancelled"]
            pid = max(todays, key=lambda x: x["published_at"])["id"] if todays else ""
    p = state["picks"].get(pid)
    if not p:
        telegram.send(owner, "⚠️ No encontré el pick gratis de hoy para corregirlo.")
        return
    try:
        notes = _refresh_post(state, p)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        notes = [f"⚠️ falló la corrección: {e}"]
    from . import argument
    pp = argument.shown_prob(p)
    if p.get("kind") != "builder" and pp < 1 / p["price"]:
        notes.append(f"Ojo: con la regla nueva este pick quedaría «sin margen» ({argument.prob_text(pp)} contra "
                     f"{argument.prob_text(1 / p['price'])} que pide la cuota); no lo cambié, solo su texto.")
    telegram.send(owner, f"🔧 <b>Pick #{p['id']} reescrito en formato simple</b>\n"
                  + "\n".join(f"• {formatting.escape(n)}" for n in notes))


def _delete_pick_posts(state: dict, p: dict) -> list[str]:
    """Borra de los canales los mensajes del pick (el pick, su imagen si fue aparte y el adelanto)."""
    done = []
    for where, mid in list((p.get("channel_msgs") or {}).items()):
        chat = state.get("vip_chat") if where == "vip" else config.FREE_CHANNEL
        if not chat:
            continue
        ok = telegram.delete_message(chat, mid)
        # Si el texto no cupo como pie de foto, la imagen salió justo antes como mensaje aparte.
        if ok and p.get("has_photo") and not formatting.caption_fits(formatting.channel_post(p, where)):
            telegram.delete_message(chat, mid - 1)
        if ok:
            done.append("VIP" if where == "vip" else "Gratis")
            p["channel_msgs"].pop(where, None)
    t = p.get("teaser") or {}
    if t.get("free_msg") and telegram.delete_message(config.FREE_CHANNEL, t["free_msg"]):
        t.pop("free_msg", None)
    return done


def _cancel_pick(state: dict, pid: str, refree: bool = False, delete_posts: bool = False) -> str:
    """Cancela un pick publicado: sale de la web y no tendrá aviso, entretiempo ni resultado.
    Con refree, busca un gratis nuevo para hoy."""
    p = state["picks"].get(pid)
    if not p:
        return f"No encontré el pick #{pid}."
    was_free = "free" in (p.get("channel_msgs") or {})
    if p.get("status") == "cancelled" and delete_posts:   # ya cancelado: solo borrar los mensajes
        done = _delete_pick_posts(state, p)
        left = [("VIP" if w == "vip" else "Gratis") for w in (p.get("channel_msgs") or {})]
        if state.get("owner_chat"):
            telegram.send(state["owner_chat"], f"🗑 Pick #{pid}: "
                          + (f"borrado de {' y '.join(done)}." if done else "no se borró ningún mensaje.")
                          + (f" ⚠️ No pude borrarlo de {' y '.join(left)}: bórralo a mano." if left else ""))
        return ""
    p.update(status="cancelled", free=False, cancelled_at=_iso(store.now_utc()))
    if delete_posts:
        _delete_pick_posts(state, p)
    for k in ("ig_pre_status", "ig_story_status"):
        if p.get(k) == "queued":
            p[k] = "skipped"
    try:
        from . import instagram
        for key in (f"pre-{pid}", f"story-{pid}"):
            if os.path.exists(instagram.image_path(key)):
                os.remove(instagram.image_path(key))
    except Exception:  # noqa: BLE001
        pass
    owner = state.get("owner_chat")
    if owner:
        telegram.send(owner, f"🗑 Pick #{pid} cancelado: salió de la web y no tendrá aviso, entretiempo ni resultado."
                             + (" Los mensajes en Telegram siguen ahí." if p.get("channel_msgs") else ""))
    af = state.get("auto_free") or {}
    if refree and (was_free or af.get("pid") == pid):
        state["auto_free"] = {}
        if not _auto_free_choose(state):
            if owner:
                telegram.send(owner, "🔎 Buscando partidos de hoy para el gratis nuevo…")
            store.save(state)
            try:
                _scan_soccer(hours=max(2, int((_end_of_today() - store.now_utc()).total_seconds() // 3600) + 1),
                             top=config.MANUAL_TOP, manual=True)
            except Exception:
                traceback.print_exc()
            fresh = store.load()
            state.clear()
            state.update(fresh)
            state["auto_free"] = {}
            _auto_free_choose(state)
    return ""


def _manual_free_file(state: dict) -> None:
    """data/manual_free.json: pick gratis elegido por el dueño (mercado y cuota de su app), una sola vez.
    {"id", "team", "mtype": "teamtotals", "outcome": "Más", "handicap": 1.5, "price": 1.82}"""
    import json
    path = os.path.join(config.ROOT, "data", "manual_free.json")
    owner = state.get("owner_chat")
    if not os.path.exists(path) or not owner:
        return
    try:
        with open(path, encoding="utf-8") as f:
            req = json.load(f)
    except Exception:  # noqa: BLE001
        return
    if not req.get("id") or req["id"] in (state.get("manual_free_done") or []):
        return
    state.setdefault("manual_free_done", []).append(req["id"])
    try:
        _manual_free(state, req)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        telegram.send(owner, f"⚠️ No pude publicar el gratis manual: {formatting.escape(str(e))[:300]}")


def _manual_free(state: dict, req: dict) -> None:
    from .value import Pick
    owner = state["owner_chat"]
    now = store.now_utc()
    fx = None
    try:
        fxs = oddspapi.upcoming_fixtures(_iso(now - timedelta(hours=2)), _iso(now + timedelta(hours=12)))
        fx = next((f for f in fxs if _name_hit(req["team"], f.get("participant1Name") or "")
                   or _name_hit(req["team"], f.get("participant2Name") or "")), None)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    if not fx:   # respaldo: el partido desde el calendario de ESPN (sin cuota de referencia)
        from . import espn
        from zoneinfo import ZoneInfo
        day = now.astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d")
        for e in espn._scoreboard(day, "soccer"):
            c = (e.get("competitions") or [{}])[0]
            comp = c.get("competitors") or []
            h = next((x for x in comp if x.get("homeAway") == "home"), None)
            a_ = next((x for x in comp if x.get("homeAway") == "away"), None)
            if h and a_ and (_name_hit(req["team"], h["team"].get("displayName", "")) or _name_hit(req["team"], a_["team"].get("displayName", ""))):
                ko = e["date"].replace("Z", ":00Z") if len(e["date"]) == 17 else e["date"]
                fx = {"fixtureId": f"espn-{e.get('id')}", "participant1Name": h["team"]["displayName"],
                      "participant2Name": a_["team"]["displayName"], "startTime": ko, "tournamentId": None,
                      "league": req.get("league") or ""}
                break
    if not fx:
        telegram.send(owner, f"⚠️ No encontré el partido de {formatting.escape(req['team'])} de hoy.")
        return
    side = "1" if _name_hit(req["team"], fx.get("participant1Name") or "") else "2"
    mtype = f"teamtotals-team{side}" if req["mtype"] == "teamtotals" else req["mtype"]
    sel = None
    try:
        rows = oddspapi.odds_by_tournaments([fx["tournamentId"]]) if fx.get("tournamentId") else []
        row = next((r for r in rows if r.get("fixtureId") == fx["fixtureId"]), None)
        if row:
            for x in selections_for_fixture(fx, row, oddspapi.markets()):
                if (x.mtype == mtype and x.handicap is not None and abs(float(x.handicap) - float(req["handicap"])) < 1e-9
                        and str(x.outcome).lower()[:3] == req["outcome"].lower()[:3]):
                    sel = x
                    break
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    price = float(req["price"])
    if sel:
        sel.price = price
        d = Pick("simple", [sel], tier="valor" if sel.fair_prob * price - 1 >= config.MIN_EDGE else "justa").to_dict()
    else:   # sin cuota de referencia: la probabilidad parte de la cuota de tu app
        leg = {"fixture_id": fx["fixtureId"], "home": fx.get("participant1Name"), "away": fx.get("participant2Name"),
               "league": fx.get("league") or config.TOURNAMENTS.get(fx.get("tournamentId"), "") or req.get("league", ""),
               "kickoff": fx["startTime"], "market": "Goles del equipo",
               "mtype": mtype, "outcome": req["outcome"], "handicap": float(req["handicap"]), "price": price,
               "fair_odds": price, "edge": 0.0, "sport": "soccer"}
        d = {"kind": "simple", "tier": "justa", "price": price, "prob": round(1 / price, 4), "edge": 0.0, "stake": 3,
             "kickoff": fx["startTime"], "legs": [leg]}
    for l in d["legs"]:
        l["label"] = formatting.outcome_label(l)
        l["sport"] = "soccer"
    d["analysis"] = formatting.analysis(d)
    state["seq"] += 1
    pid = str(state["seq"])
    d.update(id=pid, status="selected", created_at=_iso(now), stake_v=2, pick_style="coupon", manual_free=True)
    state["picks"][pid] = d
    _fresh_evidence(d)
    _publish(state, d, free=True, vip_too=bool(state.get("vip_chat")))
    d["auto_free"] = True   # mismo trato que el gratis automático (postpartido)
    state["auto_free"] = {"date": _local_today(), "status": "published", "pid": pid, "opt": "A"}
    from . import evidence, instagram
    note = ""
    if config.AUTO_FREE_INSTAGRAM and instagram.enabled(state):
        image = _pick_image(d, "free")
        if image:
            from . import postimage
            instagram.save_image(f"pre-{pid}", postimage.fit_instagram(image))
            d["ig_pre_status"] = "queued"
            d["ig_pre_caption"] = formatting.instagram_pick_caption(d)
            note = " · Instagram en cola"
    from . import argument
    pp = argument.shown_prob(d)
    telegram.send(owner, f"✅ <b>Pick gratis #{pid} publicado</b> (Gratis + VIP{note})\n"
                  f"⚽ {formatting.escape(d['legs'][0]['home'])} vs {formatting.escape(d['legs'][0]['away'])}\n"
                  f"🎯 {formatting.escape(formatting.public_label(d['legs'][0]))} @ {formatting.odds(price)}\n"
                  + evidence.line(d["legs"][0].get("evidence")) + "\n"
                  + f"📈 Le damos {argument.prob_text(pp)}; la cuota pide {argument.prob_text(1 / price)}."
                  + ("" if sel else "\n(No encontré la cuota de referencia: la probabilidad parte de tu cuota.)"))


def _cancel_file(state: dict) -> None:
    """data/cancel.json ({"id": "...", "pid": "39", "refree": true}): cancelar un pick publicado, una sola vez."""
    import json
    path = os.path.join(config.ROOT, "data", "cancel.json")
    if not os.path.exists(path) or not state.get("owner_chat"):
        return
    try:
        with open(path, encoding="utf-8") as f:
            req = json.load(f)
    except Exception:  # noqa: BLE001
        return
    if not req.get("id") or req["id"] in (state.get("cancel_done") or []):
        return
    state.setdefault("cancel_done", []).append(req["id"])
    pid = str(req.get("pid", "")).lstrip("#")
    if req.get("only_if_data_against"):   # revisar con H2H y forma reciente; solo se cambia si no lo respaldan
        p = state["picks"].get(pid)
        if not p:
            telegram.send(state["owner_chat"], f"⚠️ No encontré el pick #{pid}.")
            return
        from . import evidence
        for l in p["legs"]:
            l.pop("evidence", None)   # siempre con datos frescos
        evs = [_leg_evidence(l) for l in p["legs"]]
        txt = "\n".join(evidence.line(e) for e in evs)
        if all(e and e["verdict"] == "ok" for e in evs):
            telegram.send(state["owner_chat"], f"🔍 Revisé el pick #{pid} con los datos y se mantiene:\n{txt}")
            return
        telegram.send(state["owner_chat"], f"🔍 Revisé el pick #{pid}: los datos no lo respaldan, lo reemplazo.\n{txt}")
    err = _cancel_pick(state, pid, bool(req.get("refree")), bool(req.get("delete_posts")))
    if err:
        telegram.send(state["owner_chat"], "⚠️ " + formatting.escape(err))


def _repair_file(state: dict) -> None:
    """data/repair.json ({"id": "...", "pid": "37"}): corrección de un pick publicado, una sola vez."""
    import json
    path = os.path.join(config.ROOT, "data", "repair.json")
    if not os.path.exists(path) or not state.get("owner_chat"):
        return
    try:
        with open(path, encoding="utf-8") as f:
            req = json.load(f)
    except Exception:  # noqa: BLE001
        return
    if not req.get("id") or req["id"] in (state.get("repair_done") or []):
        return
    state.setdefault("repair_done", []).append(req["id"])
    try:
        rp = state["picks"].get(str(req.get("pid", "")).lstrip("#"))
        if rp and req.get("layout"):
            rp["pick_layout"] = req["layout"]
        err = _repair_pick(state, str(req.get("pid", "")).lstrip("#"))
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        err = f"falló la corrección: {e}"
    if err:
        telegram.send(state["owner_chat"], "⚠️ " + formatting.escape(err))


def _free_command(state: dict, text: str) -> None:
    """/gratis · estado del pick gratis automático · /gratis apagar · /gratis encender · /gratis ahora"""
    owner = state["owner_chat"]
    arg = (text.split(maxsplit=1)[1] if len(text.split()) > 1 else "").strip().lower()
    if arg in ("apagar", "off", "no"):
        state["auto_free_off"] = True
        telegram.send(owner, "⏸️ Pick gratis automático apagado. Vuelve con /gratis encender.")
        return
    if arg in ("encender", "on", "si", "sí"):
        state.pop("auto_free_off", None)
        telegram.send(owner, "▶️ Pick gratis automático encendido: sale cada día tras el escaneo de las 00:05.")
        return
    bits = arg.replace("#", " ").split()
    if bits and bits[0].lstrip("#").isdigit():   # /gratis 37 [b] · ese pick es el gratis de hoy y sale ya
        err = _force_free(state, bits[0].lstrip("#"), bits[1] if len(bits) > 1 else "A")
        if err:
            telegram.send(owner, "⚠️ " + formatting.escape(err))
        return
    if arg in ("prueba", "test", "probar"):
        _free_preview(state)
        return
    af = state.get("auto_free") or {}
    on = "apagado ⏸️" if state.get("auto_free_off") else "encendido ▶️"
    st = {"pending": "pendiente de publicar", "published": "publicado", "cancelled": "cancelado",
          "none": "sin opción que cumpla"}.get(af.get("status"), "aún no se elige")
    telegram.send(owner, f"🤖 Pick gratis automático: {on}\nHoy: {st}"
                  + (f" (pick #{af['pid']})" if af.get("pid") and af.get("date") == _local_today() else "")
                  + "\n\n/gratis 37 · usar ese pick como gratis de hoy (sale ya)\n/gratis prueba · ver qué elegiría (solo tú, no publica)\n/gratis apagar · /gratis encender")


def _protect(pk, selections):
    """Totales X.5 → línea entera vecina («más de 2.5» → «más de 2»; «menos de 2.5» → «menos de 3»):
    si cae justo en la línea se devuelve en vez de perder. Solo si existe a buena cuota y precio justo."""
    from .value import Pick
    if pk.kind != "simple":
        return pk
    l = pk.legs[0]
    if not l.mtype.startswith(("totals", "teamtotals")) or l.handicap is None or float(l.handicap) % 1 != 0.5:
        return pk
    over = str(l.outcome).lower().startswith(("más", "mas", "over"))
    target = float(l.handicap) - 0.5 if over else float(l.handicap) + 0.5
    sibs = [s for s in selections if s.fixture_id == l.fixture_id and s.mtype == l.mtype and s.handicap is not None
            and abs(float(s.handicap) - target) < 1e-9 and str(s.outcome).lower()[:3] == str(l.outcome).lower()[:3]
            and config.PROTECTED_MIN_ODDS <= s.price <= config.ODDS_MAX and s.edge >= config.AUTO_FREE_MIN_EDGE]
    if not sibs:
        return pk
    s = max(sibs, key=lambda x: x.edge)
    return Pick("simple", [s], tier="valor" if s.edge >= config.MIN_EDGE else "justa")


def _min_odds(d: dict) -> float:
    """Piso de cuota: 1.65, o 1.60 para totales de línea entera (protegidos)."""
    l = (d.get("legs") or [{}])[0]
    h = l.get("handicap")
    if (l.get("mtype") or "").startswith(("totals", "teamtotals")) and h is not None and float(h) % 1 == 0:
        return min(config.ODDS_MIN, config.PROTECTED_MIN_ODDS)
    return config.ODDS_MIN


def _scan_soccer(hours: int | None = None, top: int | None = None, manual: bool = False, live: bool = False) -> None:
    state = store.load()
    now = store.now_utc()
    hours = min(hours or config.WINDOW_END_H, 47)
    if live:
        title = "🔴 Búsqueda en vivo"
        frm, to = now - timedelta(minutes=config.LIVE_MAX_MINUTE + 20), now
    else:
        title = f"🔎 Búsqueda manual ({hours} h)" if manual else "🔎 Escaneo de hoy"
        frm, to = now + timedelta(hours=config.WINDOW_START_H), now + timedelta(hours=hours)
        if not manual:   # escaneo diario: solo los partidos de HOY (hora Chile)
            to = min(to, _end_of_today())

    markets = oddspapi.markets()
    fixtures = (oddspapi.live_fixtures if live else oddspapi.upcoming_fixtures)(_iso(frm), _iso(to))
    fixtures = [f for f in fixtures if frm <= store.parse_ts(f["startTime"]) <= to]
    by_id = {f["fixtureId"]: f for f in fixtures}
    print(f"Partidos con cuotas de Betano en la ventana: {len(by_id)}")

    counts: dict[int, int] = {}
    for f in fixtures:
        t = f["tournamentId"]
        if t in config.TOURNAMENTS:
            counts[t] = counts.get(t, 0) + 1
    order = list(config.TOURNAMENTS)
    tournaments = sorted(counts, key=order.index)[:config.MAX_TOURNAMENTS_PER_CALL * config.ODDS_BATCHES]
    names = {t: config.TOURNAMENTS[t] for t in tournaments}
    print("Ligas analizadas hoy: " + "; ".join(f"{names[t]} ({counts[t]})" for t in tournaments))
    if not tournaments:
        telegram.send(state["owner_chat"], f"{title}: ninguna de tus ligas tiene partidos "
                      + ("jugándose ahora." if live else f"en las próximas {hours} horas."))
        return

    odds_rows = oddspapi.odds_by_tournaments(tournaments)
    selections, analyzed = [], 0
    for row in odds_rows:
        fx = by_id.get(row.get("fixtureId"))
        if fx and len(row.get("bookmakerOdds") or {}) == 2:
            analyzed += 1
            selections += selections_for_fixture(fx, row, markets)

    # No repetir partidos que ya tienen un candidato pendiente o un pick publicado.
    busy = {l["fixture_id"] for p in state["picks"].values()
            if p["status"] in ("candidate", "published") for l in p["legs"]}
    selections = [x for x in selections if x.fixture_id not in busy]
    daily = not manual and not live
    want = top or (config.DAILY_TOP if daily else config.MAX_CANDIDATES)
    picks = build_picks(selections, max_n=want * 2,
                        min_n=(top or (config.DAILY_TOP if daily else config.MIN_DAILY_CANDIDATES)) * 2)
    if config.PROTECTED_LINES:
        picks = [_protect(pk, selections) for pk in picks]
    # Segunda opinión con datos: los que el H2H y la forma reciente contradicen van al final (o fuera)
    scored = []
    for pk in picks:
        evs = []
        for leg in pk.legs:
            dd = {**leg.__dict__, "context": None}
            try:
                dd["context"] = apifootball.context(leg.home, leg.away, leg.kickoff)
            except Exception:
                traceback.print_exc()
            evs.append(_leg_evidence(dd))
        bad = any(e and e["verdict"] == "contra" for e in evs)
        good = all(e and e["verdict"] == "ok" for e in evs)
        scored.append((bad, not good, pk, evs))
    scored.sort(key=lambda x: (x[0], x[1]))
    keep = [x for x in scored if not x[0]][:want] or [x for x in scored][:max(1, min(want, len(scored)))]
    picks = [x[2] for x in keep]
    ev_by_pick = {id(x[2]): x[3] for x in keep}

    in_range = sorted((x for x in selections if config.ODDS_MIN <= x.price <= config.ODDS_MAX),
                      key=lambda x: x.edge, reverse=True)[:3]
    best = "\n".join(f"• {formatting.outcome_label({**x.__dict__})} ({x.home} vs {x.away}) @ {x.price:.2f}: "
                     f"{'+' if x.edge >= 0 else ''}{formatting.pct(x.edge)}" for x in in_range)
    if not picks:
        if best:
            best = "\n\nLo más cercano dentro del rango (valor frente a la cuota justa):\n" + best
        telegram.send(state["owner_chat"],
                      f"{title}: {len(tournaments)} ligas, {analyzed} partidos con cuotas de ambas casas, "
                      f"{len(selections)} cuotas comparadas. "
                      f"Ninguna cumple valor ≥ {formatting.pct(config.MIN_EDGE)} dentro de "
                      f"{config.ODDS_MIN:.2f}–{config.ODDS_MAX:.2f}. No hay picks para proponer." + best)
        store.save(state)
        return

    n_val = sum(1 for p in picks if p.tier == "valor")
    if daily:
        free_on = config.AUTO_FREE and not state.get("auto_free_off")
        telegram.send(state["owner_chat"],
                      f"{title}: {len(tournaments)} ligas, {analyzed} partidos, {len(selections)} cuotas comparadas.\n"
                      f"⚽ Te envío los <b>{len(picks)} mejores picks de fútbol de hoy</b> "
                      f"({n_val} 🟢 con valor y {len(picks) - n_val} ⚖️ de cuota justa).\n"
                      + ("De estos elijo el pick gratis del día: te llega al final con el motivo. Los otros quedan "
                         "para el VIP si los apruebas. " if free_on else "Elige 1 para el gratis y los que quieras para el VIP. ")
                      + "La NBA llega aparte, unos 30 min antes de cada partido. Revisa cada cuota en tu app.")
    else:
        telegram.send(state["owner_chat"],
                  f"{title}: {len(tournaments)} ligas, {analyzed} partidos, {len(selections)} cuotas comparadas.\n"
                  f"{'Tu top ' + str(len(picks)) if manual else 'Te envío ' + str(len(picks)) + ' candidatos'}: "
                  f"{n_val} 🟢 con valor y {len(picks) - n_val} ⚖️ de cuota justa.\n"
                  + ("En unos segundos te llega el pick gratis que elegí (el más probable); tú elige de 2 a 4 "
                     "para el VIP. " if config.AUTO_FREE and not manual and not live and not state.get("auto_free_off")
                     else "Sugerencia: 1 para el canal gratis (✅ VIP + Gratis) y de 2 a 4 para el VIP. ") +
                  f"Revisa cada cuota en tu app antes de aprobar.")
    try:
        from . import history
        history.update(max_fetch=5)   # completar el historial antes de calcular la forma de los equipos
    except Exception:
        traceback.print_exc()
    for p in picks:
        d = p.to_dict()
        for leg, ev in zip(d["legs"], ev_by_pick.get(id(p), [None] * len(d["legs"]))):
            leg["label"] = formatting.outcome_label(leg)
            leg["context"] = apifootball.context(leg["home"], leg["away"], leg["kickoff"])
            leg["evidence"] = ev
        state["seq"] += 1
        pid = str(state["seq"])
        d.update(id=pid, status="candidate", created_at=_iso(now), stake_v=2)
        if daily:
            d["daily_top"] = _local_today()
        if live:
            d["live"] = True
            try:
                from . import espn
                info = espn.live_info(d["legs"][0]["home"], d["legs"][0]["away"], d["legs"][0]["kickoff"])
            except Exception:
                info = None
            if info:
                d["live_info"] = f"{info['score']} · {info['clock']}"
        d["analysis"] = formatting.analysis(d)
        msg = telegram.send(state["owner_chat"], formatting.owner_candidate(d), CANDIDATE_BUTTONS(pid))
        d["owner_msg"] = msg["message_id"]
        state["picks"][pid] = d
        store.save(state)  # guardar tras cada envío por si algo falla a mitad


# ---------------------------------------------------------------- NBA
def NBA_BUTTONS(pid: str, has_b: bool) -> list:
    row = [("🅰️ Elegir opción A", f"s:{pid}")]
    if has_b:
        row.append(("🅱️ Elegir opción B", f"sb:{pid}"))
    return [row, [("❌ Descartar", f"r:{pid}")]]


def _nba_option_block(d: dict, role: str) -> str:
    from . import argument
    l = d["legs"][0]
    sign = "+" if d["edge"] >= 0 else ""
    ev = l.get("nba_ev")
    pp = argument.shown_prob(d)
    data = ""
    if ev:
        tag = {"ok": "✅ los datos acompañan", "debil": "🟡 los datos acompañan a medias",
               "contra": "⚠️ los datos lo contradicen"}[ev["verdict"]]
        who = (("del local", "del visitante") if l.get("mtype") == "totals" else ("del equipo elegido", "del rival"))
        data = (f"📚 Datos: se habría cumplido en {ev['me'][0]}/{ev['me'][1]} partidos {who[0]} y "
                f"{ev['op'][0]}/{ev['op'][1]} {who[1]} → {tag}\n")
    margin = ("⚖️ <b>Sin margen:</b> le damos " + argument.prob_text(pp) + " y la cuota pide "
              + argument.prob_text(1 / d["price"]) + ". Decide tú.\n") if pp < 1 / d["price"] else ""
    return (f"<b>Opción {role}</b> · 🎯 <b>{formatting.escape(l['label'])}</b> @ {formatting.odds(d['price'])} "
            f"· valor {sign}{formatting.pct(d['edge'])} · stake {d['stake']}/10\n" + margin + data +
            f"🗣 En el canal: <b>{formatting.escape(formatting.public_label(l))}</b>\n"
            f"<i>{formatting.escape(d.get('why', ''))}</i>\n{_args_html(l)}")


def _args_html(l: dict) -> str:
    """Argumentos a favor / en contra según el deporte."""
    if l.get("sport") == "basketball":
        from . import nba
        return nba.arguments_text(l, l.get("nba_ctx"))
    pros, cons = formatting.soccer_arguments(l)
    out = []
    if pros:
        out.append("✅ <b>A favor:</b>\n" + "\n".join(f"• {p}" for p in pros))
    if cons:
        out.append("⚠️ <b>En contra:</b>\n" + "\n".join(f"• {c}" for c in cons))
    return "\n".join(out)


def nba_candidate_text(d: dict) -> str:
    l = d["legs"][0]
    live = ""
    if d.get("live"):
        live = (f"🔴 <b>EN VIVO</b>" + (f" · {formatting.escape(d['live_info'])}" if d.get("live_info") else "")
                + f"\n⏱ Vence en {config.LIVE_CANDIDATE_MIN} min: las cuotas en vivo cambian rápido.\n")
    tag = "🟢 <b>Con valor</b>" if d.get("tier") == "valor" else "⚖️ <b>Cuota justa</b>"
    head = "🏀 <b>NBA" if l.get("sport") == "basketball" else "⚽ <b>Partido"
    parts = [f"{head} · Candidato #{d['id']}</b>\n{live}{tag}",
             f"<b>{formatting.escape(l['home'])} vs {formatting.escape(l['away'])}</b> · 🕒 {formatting.local_time(l['kickoff'])}",
             "", _nba_option_block(d, "A")]
    if d.get("alt"):
        parts += ["", _nba_option_block(d["alt"], "B")]
    parts += ["", "Verifica las cuotas en tu app. Elige la opción que te convenza y te llega la imagen para publicar."]
    return "\n".join(parts)


def scan_nba(top: int | None = None, manual: bool = False, live: bool = False) -> None:
    """NBA: por cada partido, opción A (1.65-2.00, la de más valor) y opción B (alternativa), con argumentos."""
    from . import nba
    from .value import Pick
    state = store.load()
    owner = state.get("owner_chat")
    if not owner:
        return
    now = store.now_utc()
    title = "🏀🔴 NBA en vivo" if live else ("🏀 Búsqueda NBA" if manual else "🏀 NBA de hoy")
    if live:
        frm, to = now - timedelta(hours=3), now
    else:
        frm, to = now + timedelta(minutes=30), now + timedelta(hours=30)
        if not manual:
            to = min(to, _end_of_today())
    markets = oddspapi.markets(sport_id=config.NBA_SPORT_ID)
    fixtures = (oddspapi.live_fixtures if live else oddspapi.upcoming_fixtures)(_iso(frm), _iso(to),
                                                                             sport_id=config.NBA_SPORT_ID)
    fixtures = [f for f in fixtures if f.get("tournamentId") == config.NBA_TOURNAMENT
                and frm <= store.parse_ts(f["startTime"]) <= to]
    if not fixtures:
        if manual or live:
            telegram.send(owner, f"{title}: no hay partidos " + ("jugándose ahora." if live else "en las próximas 30 horas."))
        return
    by_id = {f["fixtureId"]: f for f in fixtures}
    busy = {l.get("fixture_id") for p in state["picks"].values()
            if p["status"] in ("candidate", "selected", "published") for l in p["legs"]}
    games = []
    for row in oddspapi.odds_by_tournaments([config.NBA_TOURNAMENT]):
        fx = by_id.get(row.get("fixtureId"))
        if not fx or fx["fixtureId"] in busy or len(row.get("bookmakerOdds") or {}) < 2:
            continue
        opt = nba.options_for_game(selections_for_fixture(fx, row, markets, "basketball"))
        if opt:
            games.append((fx, opt))
    games.sort(key=lambda g: g[1][0].edge, reverse=True)
    games = games[:top or config.NBA_DAILY_GAMES]
    if not games:
        telegram.send(owner, f"{title}: {len(fixtures)} partidos revisados, ninguno con una apuesta en "
                             f"{config.ODDS_MIN:.2f}–{config.ODDS_MAX:.2f} cerca de la cuota justa.")
        return
    telegram.send(owner, f"{title}: {len(fixtures)} partidos revisados. Te mando {len(games)}, cada uno con "
                         "opción A (nuestro rango) y opción B (alternativa), con sus argumentos.")
    for fx, (a, b, tier) in games:
        ctx = None
        try:
            ctx = nba.context(a.home, a.away, a.kickoff)
        except Exception:
            traceback.print_exc()

        def build(sel, t, role):
            d = Pick("simple", [sel], tier=t).to_dict()
            leg = d["legs"][0]
            leg["label"] = formatting.outcome_label(leg)
            leg["nba_ctx"] = ctx
            d["why"] = nba.why_line(sel, role)
            d["analysis"] = formatting.analysis(d)
            return d

        d = build(a, tier, "A")
        if b:
            d["alt"] = build(b, "valor" if b.edge >= config.MIN_EDGE else "justa", "B")
        state["seq"] += 1
        pid = str(state["seq"])
        d.update(id=pid, status="candidate", created_at=_iso(now), stake_v=2, sport="basketball")
        _nba_enrich(d, ctx)
        if live:
            d["live"] = True
            found = nba.find_event(a.home, a.away, a.kickoff)
            if found:
                st = found[0].get("status") or {}
                comp = found[0]["competitions"][0]["competitors"]
                hs = next(x for x in comp if x["homeAway"] == "home").get("score")
                as_ = next(x for x in comp if x["homeAway"] == "away").get("score")
                sc = f"{as_}-{hs}" if found[1] else f"{hs}-{as_}"
                d["live_info"] = f"{sc} · {st.get('period', '?')}º cuarto {st.get('displayClock', '')}"
        msg = telegram.send(owner, nba_candidate_text(d), NBA_BUTTONS(pid, bool(d.get("alt"))))
        d["owner_msg"] = msg["message_id"]
        state["picks"][pid] = d
        store.save(state)


def _name_hit(query: str, name: str) -> bool:
    from . import espn
    q, n = set(espn._toks(query)), set(espn._toks(name))
    return bool(q & n)


def scan_match(query: str, sport: str | None = None) -> None:
    """/partido Celtics vs Knicks — analiza un partido específico (en juego o de las próximas 47 h),
    de fútbol o NBA, y te manda la opción A y B con sus argumentos."""
    import re as _re
    from . import espn, nba
    from .value import Pick
    state = store.load()
    owner = state.get("owner_chat")
    now = store.now_utc()
    teams = [t.strip() for t in _re.split(r"\s+(?:vs\.?|v|-|contra)\s+", query, maxsplit=1, flags=_re.I) if t.strip()]
    if not teams:
        telegram.send(owner, "Usa: /partido Celtics vs Knicks (o solo un equipo: /partido Colo-Colo)")
        return

    def fits(fx):
        h, a = fx.get("participant1Name") or "", fx.get("participant2Name") or ""
        if len(teams) == 1:
            return _name_hit(teams[0], h) or _name_hit(teams[0], a)
        return ((_name_hit(teams[0], h) and _name_hit(teams[1], a)) or
                (_name_hit(teams[0], a) and _name_hit(teams[1], h)))

    sports = [sport] if sport else []
    if not sports:   # sin decir el deporte: si calza con un partido NBA de hoy/mañana en ESPN, es NBA
        is_nba = False
        for d in (0, 1):
            day = (now + timedelta(days=d)).astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).strftime("%Y%m%d")
            for e in nba._get("/scoreboard", dates=day).get("events") or []:
                names = [x["team"]["displayName"] for x in e["competitions"][0]["competitors"]]
                if all(any(_name_hit(t, n) for n in names) for t in teams):
                    is_nba = True
        sports = ["basketball"] if is_nba else ["soccer"]
    sp = sports[0]
    sid = config.NBA_SPORT_ID if sp == "basketball" else 10
    found, live = None, False
    for is_live in (True, False):
        frm, to = (now - timedelta(hours=3), now) if is_live else (now, now + timedelta(hours=47))
        fxs = (oddspapi.live_fixtures if is_live else oddspapi.upcoming_fixtures)(_iso(frm), _iso(to), sport_id=sid)
        found = next((f for f in fxs if fits(f)), None)
        if found:
            live = is_live
            break
    if not found:
        st_ = store.load()   # no encontró el partido: la búsqueda no cuenta
        m_ = st_.get("manual") or {}
        if m_.get("n", 0) > 0 and m_.get("date") == _local_today():
            m_["n"] -= 1
            store.save(st_)
        telegram.send(owner, f"🔎 No encontré «{formatting.escape(query)}» con cuotas, ni en juego ni en las próximas 47 horas. "
                             "Esta búsqueda no se descontó: revisa el nombre e intenta de nuevo.")
        return
    markets = oddspapi.markets(sport_id=sid)
    rows = oddspapi.odds_by_tournaments([found["tournamentId"]])
    row = next((r for r in rows if r.get("fixtureId") == found["fixtureId"]), None)
    sels = selections_for_fixture(found, row, markets, sp) if row and len(row.get("bookmakerOdds") or {}) == 2 else []
    opt = nba.options_for_game(sels) if sels else None
    title = f"{found.get('participant1Name')} vs {found.get('participant2Name')}"
    if not opt:
        near = sorted(sels, key=lambda s: s.edge, reverse=True)[:3]
        lines = "\n".join(f"• {formatting.escape(formatting.outcome_label({**x.__dict__}))} @ {x.price:.2f}: "
                          f"{'+' if x.edge >= 0 else ''}{formatting.pct(x.edge)}" for x in near)
        telegram.send(owner, f"🔎 <b>{formatting.escape(title)}</b>{' 🔴 en vivo' if live else ''}: no hay una apuesta en "
                             f"{config.ODDS_MIN:.2f}–{config.ODDS_MAX:.2f} cerca de la cuota justa."
                             + (f"\n\nLo mejor que hay ahora:\n{lines}" if lines else
                                "\nNo hay cuotas comparables de las dos casas para este partido."))
        return
    a, b, tier = opt
    ctx = None
    try:
        ctx = (nba.context(a.home, a.away, a.kickoff) if sp == "basketball"
               else apifootball.context(a.home, a.away, a.kickoff))
    except Exception:
        traceback.print_exc()

    def build(sel, t, role):
        d = Pick("simple", [sel], tier=t).to_dict()
        leg = d["legs"][0]
        leg["label"] = formatting.outcome_label(leg)
        leg["nba_ctx" if sp == "basketball" else "context"] = ctx
        d["why"] = nba.why_line(sel, role)
        d["analysis"] = formatting.analysis(d)
        return d

    d = build(a, tier, "A")
    if b:
        d["alt"] = build(b, "valor" if b.edge >= config.MIN_EDGE else "justa", "B")
    state["seq"] += 1
    pid = str(state["seq"])
    d.update(id=pid, status="candidate", created_at=_iso(now), stake_v=2, sport=sp)
    if sp == "basketball":
        _nba_enrich(d, ctx)
    if live:
        d["live"] = True
        if sp == "basketball":
            ev = nba.find_event(a.home, a.away, a.kickoff)
            if ev:
                st = ev[0].get("status") or {}
                comp = ev[0]["competitions"][0]["competitors"]
                hs = next(x for x in comp if x["homeAway"] == "home").get("score")
                as_ = next(x for x in comp if x["homeAway"] == "away").get("score")
                d["live_info"] = f"{as_ + '-' + hs if ev[1] else hs + '-' + as_} · {st.get('period', '?')}º cuarto {st.get('displayClock', '')}"
        else:
            info = espn.live_info(a.home, a.away, a.kickoff)
            if info:
                d["live_info"] = f"{info['score']} · {info['clock']}"
    msg = telegram.send(owner, nba_candidate_text(d), NBA_BUTTONS(pid, bool(d.get("alt"))))
    d["owner_msg"] = msg["message_id"]
    state["picks"][pid] = d
    store.save(state)


def _nba_daily(state: dict) -> None:
    """Resumen diario (por privado) y alertas en vivo de posibles remontadas."""
    if not config.NBA_ENABLED or not state.get("owner_chat"):
        return
    from zoneinfo import ZoneInfo
    from . import nba
    local = store.now_utc().astimezone(ZoneInfo(config.TIMEZONE))
    if state.get("nba_digest_date") != _local_today() and config.NBA_DIGEST_HOUR <= local.hour < 22:
        state["nba_digest_date"] = _local_today()
        try:
            telegram.send(state["owner_chat"], nba.digest())
        except Exception:
            traceback.print_exc()
    if config.NBA_LIVE_ALERTS and (local.hour >= 12 or local.hour < 4):
        try:
            for a in nba.live_alerts(state):
                telegram.send(state["owner_chat"], a)
        except Exception:
            traceback.print_exc()


# ---------------------------------------------------------------- resultados
def grade_leg(l: dict, h: int, a: int) -> str | None:
    """Compara la apuesta con el marcador de 90': 'W' verde, 'L' roja, 'V' nula, None si no sé leerla."""
    t, o, line = l.get("mtype", ""), str(l.get("outcome", "")).strip().lower(), l.get("handicap")
    if t == "1x2":
        won = {"1": h > a, "x": h == a, "2": h < a}.get(o)
    elif t == "moneyline" and o in ("1", "2"):   # básquetbol: ganador incluida la prórroga
        won = (h > a) if o == "1" else (a > h)
    elif t == "bothteamsscore":
        won = (h > 0 and a > 0) == o.startswith(("s", "y"))
    elif t in ("totals", "teamtotals-team1", "teamtotals-team2") and line is not None:
        goals = h + a if t == "totals" else (h if t.endswith("1") else a)
        diff = goals - float(line)
        if diff == 0:
            return "V"
        won = diff > 0 if o.startswith(("más", "mas", "over")) else diff < 0
    elif t in ("toscore-team1", "toscore-team2"):
        goals = h if t.endswith("1") else a
        won = (goals > 0) == o.startswith(("s", "y"))
    elif t == "drawnobet" and o in ("1", "2"):
        if h == a:
            return "V"
        won = (h > a) if o == "1" else (a > h)
    elif t == "spreads" and line is not None and o in ("1", "2"):
        # la línea viene expresada para el local; las de cuarto (x.25/x.75) no se usan
        diff = (h - a + float(line)) if o == "1" else (a - h - float(line))
        if diff == 0:
            return "V"
        won = diff > 0
    else:
        won = None
    if won is None:
        return None
    return "W" if won else "L"


def _grade(pick: dict) -> tuple[str | None, list, bool]:
    """Busca el marcador final de cada partido y califica el pick.
    Devuelve (resultado, marcadores, todos_terminados). Una doble es roja si falla
    una selección; nula si ambas se devuelven; verde en otro caso."""
    if pick.get("kind") == "builder":
        from . import builder
        box = builder.final_box(pick["bb"])
        if box is None:
            return None, [None] * len(pick["legs"]), False
        res = [builder.grade(x, box) for x in pick["bb"]["legs"]]
        for l, r in zip(pick["legs"], res):
            l["leg_result"] = r
        if "L" in res:
            return "L", [], True
        if None in res:   # un jugador no jugó: lo decides tú (las casas lo tratan distinto)
            return None, [], True
        return "W", [], True
    scores, results = [], []
    for l in pick["legs"]:
        if l.get("sport") == "basketball":
            from . import nba
            sc = nba.final_score(l["home"], l["away"], l["kickoff"])
        else:
            sc = apifootball.final_score(l["home"], l["away"], l["kickoff"])
        scores.append(sc)
        results.append(grade_leg(l, *sc) if sc else None)
    finished = all(scores)
    if not finished or None in results:
        return None, scores, finished
    if "L" in results:
        return "L", scores, True
    if all(r == "V" for r in results):
        return "V", scores, True
    return "W", scores, True


def _post(chat, text: str, image: bytes | None) -> int:
    """Publica el pick con su imagen. Si el texto cabe, va como pie de foto; si no,
    foto y luego el texto. Si la imagen falla, sale solo el texto."""
    if image:
        try:
            if formatting.caption_fits(text):
                return telegram.send_photo(chat, image, caption=text)["message_id"]
            telegram.send_photo(chat, image)
        except Exception as e:
            print(f"No se pudo enviar la imagen: {e}")
    return telegram.send(chat, text)["message_id"]


def _pick_photo_file(p: dict) -> str:
    return os.path.join(config.ROOT, "data", "pickimg", f"{p['id']}.jpg")


def _make_pick_photo(p: dict, user_photo: bytes | None = None, reuse: bool = False) -> bool:
    """Versión del pick con foto real del equipo (Commons, o la tuya) y colores de ESPN. Se guarda para reutilizarla."""
    from . import espn, teaser
    l = p["legs"][0]
    try:
        teams = espn.preview(l["home"], l["away"], l["kickoff"], l.get("sport") or "soccer")
    except Exception:
        traceback.print_exc()
        teams = None
    cache = _upload_file(p, "pickphoto")
    photo = (user_photo, None) if user_photo else None
    if not photo and reuse and os.path.exists(cache):
        with open(cache, "rb") as f:
            photo = (f.read(), p.get("pick_photo_credit"))
    if not photo and not reuse:
        from . import matchphoto
        photo = matchphoto.for_pick(l, teams)   # un referente del equipo, con su camiseta si se puede
    if photo:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "wb") as f:
            f.write(photo[0])
    p.pop("pick_raw", None)
    p["pick_teams"] = teams   # para dibujar luego la versión de cada canal sin volver a consultar
    from . import layouts, postimage
    tier = "vip" if _vip_only(p) else ("free" if p.get("free") else None)
    with postimage.accent(tier):
        image = layouts.render_pick(teaser.pick_photo_data(p, teams, photo, tier), p.get("pick_layout") or "revista",
                                    p.get("theme") or "dark")
    path = _pick_photo_file(p)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(image)
    p["pick_photo_credit"] = photo[1] if photo else None
    return True


def _pick_image(p: dict, tier: str | None = None) -> bytes | None:
    """Imagen del pick. tier «free» o «vip» la dibuja con la identidad de ese canal
    (verde «PICK GRATIS» / dorado «PICK VIP»). La NBA siempre es VIP."""
    if _vip_only(p):
        tier = "vip"
    if p.get("kind") == "builder":
        try:
            from . import postimage
            return postimage.render_builder(p, "vip")
        except Exception:
            traceback.print_exc()
            return None
    if p.get("pick_style") == "photo" and os.path.exists(_pick_photo_file(p)):
        cache = _upload_file(p, "pickphoto")
        if tier and os.path.exists(cache) and not p.get("pick_raw"):
            try:
                from . import layouts, postimage, teaser
                with open(cache, "rb") as f:
                    photo = (f.read(), p.get("pick_photo_credit"))
                with postimage.accent(tier):
                    return layouts.render_pick(teaser.pick_photo_data(p, p.get("pick_teams"), photo, tier),
                                               p.get("pick_layout") or "revista", p.get("theme") or "dark")
            except Exception:
                traceback.print_exc()
        with open(_pick_photo_file(p), "rb") as f:
            return f.read()
    try:
        from . import postimage
        return postimage.render(p, tier)
    except Exception:
        traceback.print_exc()
        return None


def _publish(state: dict, p: dict, free: bool, vip_too: bool = True) -> None:
    """Publica en VIP (si vip_too) y en Gratis (si free). Si ya estaba en un canal, no lo repite."""
    msgs = p.setdefault("channel_msgs", {})
    vip = state.get("vip_chat")
    image = None
    _fresh_evidence(p)
    if vip_too and vip and "vip" not in msgs:
        image = _pick_image(p, "vip")   # dorado «PICK VIP»
        msgs["vip"] = _post(vip, formatting.channel_post(p, "vip"), image)
    if free and "free" not in msgs and not _vip_only(p):
        image = _pick_image(p, "free")   # verde «PICK GRATIS»
        msgs["free"] = _post(config.FREE_CHANNEL, formatting.channel_post(p, "free"), image)
    if p["status"] != "published":
        p.update(status="published", published_at=_iso(store.now_utc()), has_photo=bool(image))
    p["free"] = "free" in msgs


def _result_image(state: dict, p: dict) -> bytes | None:
    """Imagen de resultado para los canales: verde (celebración) o nula. Las rojas van solo en texto."""
    if p.get("result") not in ("W", "V"):
        return None
    try:
        from . import postimage
        return postimage.render_win(p, _streak(state, p) if p["result"] == "W" else 1, p["result"])
    except Exception:
        traceback.print_exc()
        return None


def _post_result(state: dict, p: dict, text: str) -> None:
    image = _result_image(state, p)
    p["result_msgs"], p["result_is_photo"] = {}, {}
    for where, mid in (p.get("channel_msgs") or {}).items():
        chat = state["vip_chat"] if where == "vip" else config.FREE_CHANNEL
        try:
            if image:
                try:
                    p["result_msgs"][where] = telegram.send_photo(chat, image, caption=text, reply_to=mid)["message_id"]
                    p["result_is_photo"][where] = True
                    continue
                except Exception as e:  # noqa: BLE001
                    print(f"No se pudo enviar la imagen del resultado en {where}: {e}")
            p["result_msgs"][where] = telegram.send(chat, text, reply_to=mid)["message_id"]
        except telegram.TelegramError as e:
            print(f"No se pudo publicar resultado en {where}: {e}")


def _loss_text(p: dict) -> str:
    """Roja: mensaje corto con lo que pasó (marcador y, si ESPN los tiene, remates al arco)."""
    from . import loss
    rep = None
    l = p["legs"][0]
    if len(p["legs"]) == 1 and (l.get("sport") or "soccer") == "soccer" and p.get("kind") != "builder":
        try:
            from . import espn
            rep = espn.match_report(l["home"], l["away"], l["kickoff"])
        except Exception:
            traceback.print_exc()
    return loss.message(p, rep)


def _settle(state: dict, p: dict, result: str) -> None:
    p.update(result=result, status="settled", settled_at=_iso(store.now_utc()))
    _post_result(state, p, _loss_text(p) if result == "L" else formatting.result_post(p))
    _after_result(state, p)


def _nba_pregame(state: dict, p: dict, now) -> bool:
    """NBA: previa exclusiva en el VIP 20-30 min antes (bajas al minuto, forma, pronóstico y noticias).
    True si ya se encargó del aviso de este pick."""
    if not _vip_only(p) or len(p["legs"]) != 1:
        return False
    if p.get("pregame") or p["status"] != "published":
        return True
    kick = store.parse_ts(p["kickoff"])
    if not (kick - timedelta(minutes=config.NBA_PREGAME_MIN) <= now < kick - timedelta(minutes=8)):
        return True
    p["pregame"] = "sent"
    p["reminded"] = True
    from . import nba
    try:
        text = nba.pregame(p, int((kick - now).total_seconds() // 60))
    except Exception:
        traceback.print_exc()
        text = None
    text = text or formatting.pre_kickoff(p, int((kick - now).total_seconds() // 60))
    for where, mid in (p.get("channel_msgs") or {}).items():
        if where != "vip":
            continue
        try:
            telegram.send(state["vip_chat"], text, reply_to=mid)
        except telegram.TelegramError as e:
            print(f"No se pudo enviar la previa NBA: {e}")
    if state.get("owner_chat"):
        telegram.send(state["owner_chat"], f"🏀 Publiqué en el VIP la previa del pick #{p['id']}.")
    return True


def _remind(state: dict, p: dict, now) -> None:
    """Aviso en los canales cuando faltan ~30 minutos para el partido."""
    if p["status"] != "published" or p.get("reminded"):
        return
    if config.NBA_PREGAME and _nba_pregame(state, p, now):
        return
    kick = store.parse_ts(p["kickoff"])
    start = kick - timedelta(minutes=config.REMINDER_BEFORE_MIN)
    if not (start <= now < kick):
        return
    p["reminded"] = True
    pub = p.get("published_at")
    if pub and store.parse_ts(pub) > start - timedelta(minutes=5):
        return  # se publicó a última hora: el pick recién salió, no hace falta recordarlo
    text = formatting.pre_kickoff(p, int((kick - now).total_seconds() // 60))
    for where, mid in (p.get("channel_msgs") or {}).items():
        chat = state["vip_chat"] if where == "vip" else config.FREE_CHANNEL
        try:
            telegram.send(chat, text, reply_to=mid)
        except telegram.TelegramError as e:
            print(f"No se pudo enviar el aviso en {where}: {e}")


def _auto_result(state: dict, p: dict, owner, now, last_kick) -> None:
    """Califica solo el pick con el marcador final y lo publica. Si el marcador aún no
    está, reintenta cada RESULT_RETRY_MIN; si no se puede leer, te lo pregunta."""
    try:
        res, scores, finished = _grade(p)
    except Exception:
        traceback.print_exc()
        res, scores, finished = None, [], False
    for l, sc in zip(p["legs"], scores):
        if sc:
            l["score"] = list(sc)   # marcador final para la web
    if res:
        _settle(state, p, res)
        p["auto_result"] = True
        telegram.send(owner, formatting.owner_auto_result(p, scores), [[("✏️ Corregir", f"c:{p['id']}")]])
        return
    gave_up = now >= last_kick + timedelta(minutes=config.RESULT_GIVE_UP_MIN)
    if finished or gave_up:  # terminó pero el mercado no se sabe leer, o nunca apareció el marcador
        telegram.send(owner, formatting.owner_result_request(p, None, scores), RESULT_BUTTONS(p["id"]))
        p["result_asked"] = True
    else:
        p["next_check"] = _iso(now + timedelta(minutes=config.RESULT_RETRY_MIN))


def _streak(state: dict, p: dict) -> int:
    """Verdes seguidos REALES terminando en este pick, para no mostrar una racha falsa.
    Cuenta todos los picks publicados (Gratis y VIP, por orden de partido): una roja corta la racha,
    las nulas no suman ni cortan, y un pick anterior que aún no se resuelve también la corta
    (no se puede afirmar una racha que todavía no se sabe)."""
    def published(x):
        return (x.get("channel_msgs") or x.get("published_at")) and not x.get("news") and x.get("status") != "cancelled"

    def key(x):
        return (max(l["kickoff"] for l in x["legs"]), x.get("settled_at") or "", int(x["id"]) if str(x["id"]).isdigit() else 0)

    if p.get("result") != "W":
        return 0
    mine = key(p)
    earlier = sorted((x for x in state["picks"].values() if published(x) and x is not p and key(x) < mine),
                     key=key, reverse=True)
    n = 1
    for x in earlier:
        if x.get("status") in ("selected",):
            continue   # aprobado pero nunca publicado
        r = x.get("result") if x.get("status") == "settled" else None
        if r == "V":
            continue
        if r != "W":
            break   # roja, o un pick anterior que aún no termina
        n += 1
    return n


def _instagram_kit(state: dict, p: dict) -> None:
    """Pick verde: imagen de celebración + texto para Instagram.
    Con Instagram conectado, te llega la vista previa con un botón para publicar;
    sin conexión, te llega el material para subirlo a mano."""
    owner = state.get("owner_chat")
    if not owner or p.get("ig_kit_sent") or p.get("result") != "W":
        return
    p["ig_kit_sent"] = True
    try:
        from . import instagram, postimage
        streak = _streak(state, p)
        image = postimage.render_win(p, streak)
        caption = formatting.instagram_caption(p, streak)
        p["ig_caption"] = caption
        p["ig_kit_mode"] = "api" if instagram.enabled(state) else "manual"
        if instagram.enabled(state) and p.get("auto_free") and config.AUTO_FREE_INSTAGRAM:
            instagram.save_image(p["id"], image)
            p["ig_status"] = "queued"
            telegram.send_photo(owner, image, caption=(
                f"🤖 <b>Celebración en Instagram</b> · pick gratis automático #{p['id']} ✅\n"
                "Se publica sola en unos minutos."))
        elif instagram.enabled(state):
            instagram.save_image(p["id"], image)   # la web la sirve para que Instagram la descargue
            telegram.send_photo(owner, image, caption=(
                f"📸 <b>Celebración para Instagram</b> · pick #{p['id']} ✅\n"
                "Este es el texto que se publicará (abajo). ¿Lo subo a Instagram?"))
            telegram.send(owner, f"<pre>{formatting.escape(caption)}</pre>",
                          [[("📸 Publicar en Instagram", f"ig:{p['id']}"), ("No publicar", f"ign:{p['id']}")]])
        else:
            telegram.send_photo(owner, image, caption=(
                f"📸 <b>Para Instagram</b> · pick #{p['id']} ✅\n"
                "Guarda la imagen y copia el texto de abajo (tócalo para copiarlo)."))
            telegram.send(owner, f"<pre>{formatting.escape(caption)}</pre>")
    except Exception:
        traceback.print_exc()


def _instagram_queue(state: dict, now) -> None:
    """Publica en Instagram los verdes que aprobaste, cuando la imagen ya está en la web."""
    from . import instagram
    owner = state.get("owner_chat")
    jobs = []
    for p in state["picks"].values():
        if p.get("ig_status") == "queued":
            jobs.append((p, "ig_status", p["id"], p.get("ig_caption") or ""))
        if p.get("ig_pre_status") == "queued":
            jobs.append((p, "ig_pre_status", p.get("ig_pre_key") or f"pre-{p['id']}", p.get("ig_pre_caption") or ""))
        if p.get("ig_res_status") == "queued":
            jobs.append((p, "ig_res_status", f"res-{p['id']}", p.get("ig_res_caption") or ""))
        if p.get("ig_story_status") == "queued":
            jobs.append((p, "ig_story_status", f"story-{p['id']}", None))
    for p, field, key, caption in jobs:
        rk = (p.get("recap") or {}).get("reel") if field == "ig_res_status" else None
        if not (instagram.video_live(rk) if rk else instagram.image_live(key)):
            continue   # la web aún no la publica; se reintenta en la próxima revisión
        try:
            if rk:   # postpartido como Reel (en dos pasos: Instagram procesa el video)
                job = p.setdefault("ig_res_job", {"reel": rk})
                link = instagram.reel_step(state, job, caption)
                if link is None:
                    continue
            elif field == "ig_story_status":
                instagram.publish_story(state, instagram.image_url(key))
                link = ""
            else:
                link = instagram.publish(state, key, caption)
            p[field] = "posted"
            if field == "ig_story_status" and (p.get("teaser") or {}).get("msg") and owner:
                telegram.set_buttons(owner, p["teaser"]["msg"], TEASER_BUTTONS(p))
            if field == "ig_pre_status" and p.get("share_msg") and owner:
                telegram.set_buttons(owner, p["share_msg"], SHARE_BUTTONS(p))
            if field == "ig_res_status" and (p.get("recap") or {}).get("panel") and owner:
                telegram.set_buttons(owner, p["recap"]["panel"], RECAP_BUTTONS(p))
            if owner:
                what = "Historia publicada" if field == "ig_story_status" else "Publicado"
                telegram.send(owner, f"✅ {what} en Instagram (pick #{p['id']})" + (f"\n{link}" if link else ""))
        except instagram.InstagramError as e:
            tries = field.replace("status", "tries")
            p[tries] = p.get(tries, 0) + 1
            print(f"Instagram falló (pick {p['id']}): {e}")
            if p[tries] >= 3:
                p[field] = "failed"
                if owner:
                    telegram.send(owner, f"⚠️ No pude publicar en Instagram el pick #{p['id']}: "
                                         f"{formatting.escape(str(e))}\nPuedes subirlo a mano con la imagen que te mandé.")


def _correct(state: dict, p: dict, result: str) -> None:
    """Cambia el resultado de un pick ya cerrado: tacha el mensaje anterior y publica el correcto."""
    old_msgs, old_photo = p.get("result_msgs") or {}, p.get("result_is_photo") or {}
    note = "✏️ <i>Resultado corregido: ver el mensaje siguiente.</i>"
    for where, mid in old_msgs.items():
        chat = state["vip_chat"] if where == "vip" else config.FREE_CHANNEL
        try:
            (telegram.edit_caption if old_photo.get(where) else telegram.edit_text)(chat, mid, note)
        except telegram.TelegramError as e:
            print(f"No se pudo marcar la corrección en {where}: {e}")
    p.update(result=result, corrected_at=_iso(store.now_utc()))
    _post_result(state, p, (_loss_text(p) + "\n<i>(resultado corregido)</i>") if result == "L"
                 else formatting.result_correction(p))
    _after_result(state, p)


# ---------------------------------------------------------------- post partido (formato revista)
def RECAP_BUTTONS(p: dict) -> list:
    pid, msgs = p["id"], (p.get("recap") or {}).get("msgs") or {}
    st = p.get("ig_res_status")
    if _vip_only(p):   # NBA: el final va al VIP y a Instagram (nunca a Gratis)
        return [
            [("✅ En VIP", "noop") if "vip" in msgs else ("👑 Compartir en VIP", f"xv:{pid}"),
             ("✅ Instagram" if st == "posted" else "⏳ Instagram en cola" if st == "queued" else "📸 Instagram",
              "noop" if st in ("queued", "posted") else f"xi:{pid}")],
            [("🖼 Adjuntar mi imagen", f"xp:{pid}"), ("✏️ Cambiar titular", f"xt:{pid}")],
            [("🌙 Modo noche" if (p.get("recap") or {}).get("theme") == "light" else "☀️ Modo día", f"xh:{pid}")],
        ]
    return [
        [("✅ En VIP", "noop") if "vip" in msgs else ("👑 Compartir en VIP", f"xv:{pid}"),
         ("✅ En Gratis", "noop") if "free" in msgs else ("🎁 Compartir en Gratis", f"xf:{pid}")],
        [("✅ Instagram" if st == "posted" else "⏳ Instagram en cola" if st == "queued" else "📸 Compartir en Instagram",
          "noop" if st in ("queued", "posted") else f"xi:{pid}")],
        [("🖼 Adjuntar mi imagen", f"xp:{pid}"), ("✏️ Cambiar titular", f"xt:{pid}")],
        [("🌙 Modo noche" if (p.get("recap") or {}).get("theme") == "light" else "☀️ Modo día", f"xh:{pid}"),
         ("🔀 Otro diseño", f"xl:{pid}")],
    ] + ([[("✋ No compartir sola", f"xn:{pid}")]] if (p.get("recap") or {}).get("auto_at")
         and not p["recap"].get("auto_done") and not p["recap"].get("auto_off") else [])


def _recap_supported(p: dict) -> bool:
    return len(p["legs"]) == 1 and (p["legs"][0].get("sport") or "soccer") in ("soccer", "basketball")


def _recap_file(p: dict) -> str:
    from . import recap
    return recap.image_path(p["id"])


def _recap_panel(state: dict, p: dict) -> None:
    """Te manda la imagen post partido con los botones para compartirla."""
    owner = state["owner_chat"]
    r = p["recap"]
    if r.get("panel"):
        telegram.edit_buttons_off(owner, r["panel"], "↪️ Reemplazada por la versión de abajo")
    label = {"W": " (✅ verde)", "L": " (❌ roja)", "V": " (↩️ nula)"}.get(p.get("result"), "")
    who = "partido " + p["id"] if p.get("news") else "pick #" + p["id"]
    cap = (f"📰 <b>Post partido · {who}</b>{label}\n"
           f"Titular: <b>{formatting.escape(r['title'])}</b> · para cambiarlo: /titular {p['id']} TU TITULAR\n"
           "Elige dónde compartirlo (puedes usar varios botones).")
    if r.get("credit"):
        cap += f"\n📸 {formatting.escape(r['credit']['text'])}"
    if r.get("auto_at") and not r.get("auto_done") and not r.get("auto_off"):
        from zoneinfo import ZoneInfo
        hhmm = store.parse_ts(r["auto_at"]).astimezone(ZoneInfo(config.TIMEZONE)).strftime("%H:%M")
        cap += (f"\n🤖 Pick gratis automático: se comparte sola a las {hhmm} en los canales del pick"
                + (" y en Instagram" if p.get("result") == "W" else "") + ".")
    if r.get("reel"):
        cap += "\n🎬 En Instagram sale como Reel (el video de abajo)."
    with open(_recap_file(p), "rb") as f:
        msg = telegram.send_photo(owner, f.read(), caption=cap)
    r["panel"] = msg["message_id"]
    if r.pop("reel_new", None):
        try:
            from . import instagram
            with open(instagram.video_path(r["reel"]), "rb") as f:
                telegram.send_video(owner, f.read(), caption=f"🎬 Reel del postpartido · pick #{p['id']}")
        except Exception:
            traceback.print_exc()
    telegram.set_buttons(owner, r["panel"], RECAP_BUTTONS(p))


def _upload_file(p: dict, kind: str = "recap") -> str:
    name = f"{p['id']}.jpg" if kind == "recap" else f"{p['id']}-{kind}.jpg"
    return os.path.join(config.ROOT, "data", "uploads", name)


def _recap(state: dict, p: dict, reuse: bool = False) -> bool:
    """Arma la imagen post partido con datos de ESPN y te la manda. False si ESPN aún no tiene el final.
    reuse=True vuelve a dibujarla con los datos ya guardados (titular nuevo o tu foto)."""
    if not state.get("owner_chat") or not _recap_supported(p):
        return False
    if (p["legs"][0].get("sport") or "soccer") == "basketball":
        return _recap_nba(state, p, reuse)
    from . import commons, espn, postimage, recap
    l = p["legs"][0]
    old = p.get("recap") or {}
    rep = old.get("report") if reuse else None
    rep = rep or espn.match_report(l["home"], l["away"], l["kickoff"])
    if not rep:
        return False
    who = recap.hero(rep)
    if old.get("photo_src") == "user" and os.path.exists(_upload_file(p)):
        with open(_upload_file(p), "rb") as f:
            photo = (f.read(), None)
    else:
        photo = None
        if who:
            from . import matchphoto
            t = rep.get(who.get("side")) or {}
            photo = (matchphoto.for_scorer(who["full"], [x for x in (t.get("name"), t.get("short")) if x], "soccer")
                     or commons.team_photo(t.get("name") or "", "soccer"))   # sin foto segura: colores del equipo
    data = recap.build(p, rep, photo, old.get("custom_title"))
    data["credit"] = photo[1]["text"] if photo and photo[1] else None
    from . import layouts
    layout = old.get("layout") or layouts.next_layout(state, "recap")
    if old.get("mode") == "raw" and os.path.exists(_upload_file(p)):
        with open(_upload_file(p), "rb") as f:
            image = postimage.fit_instagram(f.read())
    else:
        image = layouts.render_recap(data, layout, old.get("theme") or "dark")
    path = _recap_file(p)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(image)
    credit = photo[1] if photo and old.get("mode") != "raw" else None
    p["recap"] = {"title": data["headline"], "custom_title": old.get("custom_title"), "credit": credit,
                  "msgs": old.get("msgs") or {}, "panel": old.get("panel"), "hero": who["full"] if who else None,
                  "report": rep, "photo_src": old.get("photo_src"), "mode": old.get("mode"), "v": RECAP_TEXT_V,
                  "theme": old.get("theme"), "layout": layout,
                  "tg": recap.telegram_caption(p, rep, data["headline"]),
                  "ig": recap.instagram_caption(p, rep, data["headline"], credit)}
    for k in ("auto_at", "auto_done", "auto_off"):
        if k in old:
            p["recap"][k] = old[k]
    if p.get("auto_free") and not p["recap"].get("auto_at"):
        p["recap"]["auto_at"] = _iso(store.now_utc() + timedelta(minutes=config.AUTO_FREE_RECAP_DELAY_MIN))
    if old.get("reel"):
        p["recap"]["reel"] = old["reel"]
    elif config.IG_REELS:
        try:   # Reel del postpartido (marcador que sube, goles y nuestro pick): va a Instagram en vez de la imagen
            from . import instagram, reel
            mp4, cover = reel.from_report(p, rep, photo if photo and old.get("photo_src") != "user" else None)
            instagram.save_video(f"res-{p['id']}", mp4, cover)
            p["recap"]["reel"] = f"res-{p['id']}"
            p["recap"]["reel_new"] = True
        except Exception:
            traceback.print_exc()
    p.pop("recap_pending", None)
    p["ig_kit_sent"] = True   # el post partido reemplaza a la imagen de celebración
    _recap_panel(state, p)
    return True


def _after_result(state: dict, p: dict) -> None:
    """Con el resultado listo: imagen post partido (fútbol, pick simple) o la celebración de siempre.
    Las rojas no llevan imagen: solo el mensaje corto que ya salió en los canales."""
    if p.get("result") == "L":
        p["ig_kit_sent"] = True
        p.pop("recap_pending", None)
        return
    if not _recap_supported(p):
        _instagram_kit(state, p)
        return
    p["recap_pending"] = True
    p["ig_kit_sent"] = True
    p.pop("recap_next", None)
    try:
        _recap(state, p)
    except Exception:
        traceback.print_exc()


def _recap_retry(state: dict, p: dict, now) -> None:
    """ESPN a veces tarda en cerrar el partido: reintenta cada 20 min durante 6 h y luego usa la celebración."""
    if not p.get("recap_pending") or p["status"] != "settled":
        return
    if p.get("recap_next") and now < store.parse_ts(p["recap_next"]):
        return
    if now - store.parse_ts(p.get("settled_at") or _iso(now)) > timedelta(minutes=config.RESULT_GIVE_UP_MIN):
        p.pop("recap_pending", None)
        if p.get("result") == "W":
            p["ig_kit_sent"] = False   # sin datos de ESPN: se ofrece la imagen de celebración
        return
    p["recap_next"] = _iso(now + timedelta(minutes=config.RESULT_RETRY_MIN))
    try:
        _recap(state, p)
    except Exception:
        traceback.print_exc()


RECAP_TEXT_V = 2


def _refresh_recap_texts(state: dict) -> None:
    """Textos nuevos del post partido para los que aún no salieron a Instagram."""
    from . import recap
    for p in state["picks"].values():
        r = p.get("recap") or {}
        if not r.get("report") or r.get("v") == RECAP_TEXT_V:
            continue
        r["v"] = RECAP_TEXT_V
        if p.get("ig_res_status") == "posted":
            continue
        r["tg"] = recap.telegram_caption(p, r["report"], r.get("title") or "")
        r["ig"] = recap.instagram_caption(p, r["report"], r.get("title") or "", r.get("credit"))
        if p.get("ig_res_status") == "queued":
            p["ig_res_caption"] = r["ig"]


# ---------------------------------------------------------------- Bet Builder
BUILDER_BUTTONS = lambda pid: [  # noqa: E731
    [("✏️ Cargar cuota", f"bq:{pid}")],
    [("❌ Descartar", f"r:{pid}")],
]


def _builder_send(state: dict, home: str, away: str, kickoff: str, league: str, sport: str, quiet: bool = False) -> bool:
    """Arma el Bet Builder de un partido y te lo manda. False si no hay 3 líneas que cumplan."""
    from . import builder
    owner = state.get("owner_chat")
    try:
        b = builder.suggest(home, away, kickoff, sport)
    except Exception:
        traceback.print_exc()
        b = None
    if not b:
        if not quiet and owner:
            telegram.send(owner, f"🧩 {formatting.escape(home)} vs {formatting.escape(away)}: no encontré 3 líneas "
                                 "que los jugadores cumplan en al menos 8 de cada 10 partidos (o faltan datos).")
        return False
    state["seq"] += 1
    pid = str(state["seq"])
    legs = [{"home": home, "away": away, "kickoff": kickoff, "league": league, "sport": sport, "mtype": "prop",
             "outcome": x["label"], "label": x["label"], "market": "Bet Builder", "price": None,
             "handicap": x["line"], "fixture_id": f"bb-{b['event']}"} for x in b["legs"]]
    p = {"id": pid, "kind": "builder", "status": "bb", "legs": legs, "bb": b, "price": b["target"],
         "prob": b["prob"], "edge": 0.0, "stake": 2, "tier": "justa", "created_at": _iso(store.now_utc()),
         "kickoff": kickoff, "sport": sport, "stake_v": 2}
    msg = telegram.send(owner, formatting.builder_owner(p), BUILDER_BUTTONS(pid))
    p["owner_msg"] = msg["message_id"]
    state["picks"][pid] = p
    return True


def _builder_command(state: dict, text: str) -> None:
    """/builder Thunder vs Nuggets · /builder Colo-Colo — Bet Builder de un partido de hoy o mañana."""
    from . import nba
    owner = state["owner_chat"]
    q = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
    words = q.lower().split()
    sport = "basketball" if "nba" in words else "soccer" if any(w in ("futbol", "fútbol") for w in words) else None
    q = " ".join(w for w in q.split() if w.lower() not in ("nba", "futbol", "fútbol"))
    if not q:
        telegram.send(owner, "Usa: /builder Thunder vs Nuggets · /builder Colo-Colo · /builder nba Lakers\n"
                             "Busca el partido de hoy o mañana y te arma 3 líneas fáciles de cumplir.")
        return
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    now = store.now_utc()
    found = None
    for k in (0, 1):
        day = (now + timedelta(days=k)).astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d")
        pools = []
        if sport in (None, "basketball"):
            pools.append(("basketball", nba._get("/scoreboard", dates=day).get("events") or [], "USA · NBA"))
        if sport in (None, "soccer"):
            from . import espn
            pools.append(("soccer", espn._scoreboard(day, "soccer"), None))
        for sp, evs, lg in pools:
            for e in evs:
                c = (e.get("competitions") or [{}])[0]
                if ((c.get("status") or {}).get("type") or {}).get("state") != "pre":
                    continue
                comp = c.get("competitors") or []
                h = next((x for x in comp if x.get("homeAway") == "home"), None)
                a = next((x for x in comp if x.get("homeAway") == "away"), None)
                if not h or not a:
                    continue
                hn, an = h["team"].get("displayName", ""), a["team"].get("displayName", "")
                if all(_name_hit(part, hn) or _name_hit(part, an) for part in re.split(r"\s+(?:vs\.?|v|-|contra)\s+", q, flags=re.I)):
                    ko = e["date"].replace("Z", ":00Z") if len(e["date"]) == 17 else e["date"]
                    from . import builder as _b
                    league = lg or _b.league_name((e.get("season") or {}).get("slug") or "")
                    found = (hn, an, ko, league, sp)
                    break
            if found:
                break
        if found:
            break
    if not found:
        telegram.send(owner, f"No encontré «{formatting.escape(q)}» entre los partidos de hoy y mañana que aún no empiezan.")
        return
    telegram.send(owner, f"🧩 Revisando las estadísticas de {formatting.escape(found[0])} vs {formatting.escape(found[1])}… "
                         "te llega en un par de minutos.")
    _builder_send(state, *found)


def _builder_odds(state: dict, text: str) -> bool:
    """Respuesta con la cuota real del Bet Builder. True si la usó."""
    from . import builder
    w = state.get("await_odds") or {}
    if not w or store.parse_ts(w["until"]) < store.now_utc():
        return False
    v = builder.parse_odds(text)
    if v is None:
        return False
    p = state["picks"].get(w["pid"])
    state.pop("await_odds", None)
    if not p or p["status"] != "bb":
        return False
    p["price"] = v
    p["edge"] = round(p["prob"] * v - 1, 4)
    p["status"] = "selected"
    telegram.send(state["owner_chat"], f"✅ Cuota {formatting.odds(v)} cargada en el Bet Builder #{p['id']} "
                  + (f"(valor +{formatting.pct(p['edge'])} según nuestros números)." if p["edge"] > 0 else
                     "(está por debajo de la cuota mínima: según los números no conviene, decide tú)."))
    _share_panel(state, p)
    return True


def _daily_builders(state: dict) -> None:
    """Tras el escaneo diario: un Bet Builder de NBA y uno de fútbol con los partidos de los candidatos de hoy."""
    today = _local_today()
    if state.get("bb_date") == today:
        return
    state["bb_date"] = today
    seen = set()
    for sport in ("soccer",):   # la NBA sale aparte, ~30 min antes de cada partido
        cands = [p for p in state["picks"].values() if p["status"] == "candidate" and p.get("kind") != "builder"
                 and (p["legs"][0].get("sport") or "soccer") == sport and not p.get("live")
                 and store.parse_ts(p["kickoff"]) > store.now_utc() + timedelta(hours=2)]
        cands.sort(key=lambda p: p.get("prob", 0), reverse=True)
        for p in cands[:3]:
            l = p["legs"][0]
            key = (l["home"], l["away"])
            if key in seen:
                continue
            seen.add(key)
            if _builder_send(state, l["home"], l["away"], l["kickoff"], l.get("league") or "", sport, quiet=True):
                break


def _nba_events(now) -> list:
    """Partidos NBA del día (ESPN, gratis): [(id, inicio, local, visita)]."""
    from . import nba
    from zoneinfo import ZoneInfo
    out = []
    day = now.astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d")
    for e in nba._get("/scoreboard", dates=day).get("events") or []:
        if not e.get("date"):
            continue
        ko = store.parse_ts(e["date"].replace("Z", ":00Z") if len(e["date"]) == 17 else e["date"])
        c = e["competitions"][0]["competitors"]
        out.append((e.get("id"), ko, next(x for x in c if x["homeAway"] == "home")["team"]["displayName"],
                    next(x for x in c if x["homeAway"] == "away")["team"]["displayName"]))
    return out


def _nba_pick_dict(fx, a, b, tier) -> dict:
    """Candidato NBA (opción A y B) sin número todavía; el contexto se arma al enviarlo."""
    from . import nba
    from .value import Pick

    def build(sel, t, role):
        d = Pick("simple", [sel], tier=t).to_dict()
        d["legs"][0]["label"] = formatting.outcome_label(d["legs"][0])
        d["why"] = nba.why_line(sel, role)
        return d

    d = build(a, tier, "A")
    if b:
        d["alt"] = build(b, "valor" if b.edge >= config.MIN_EDGE else "justa", "B")
    d["sport"] = "basketball"
    return d


def _nba_enrich(d: dict, ctx: dict | None, skip_absences: bool = False) -> None:
    """Contexto, bajas que pesan y contraste con datos para la opción A y la B."""
    from . import nbadata
    if not skip_absences:
        try:
            nbadata.key_absences(ctx, d["legs"][0]["kickoff"])
        except Exception:
            traceback.print_exc()
    for x in (d, d.get("alt")):
        if x:
            x["legs"][0]["nba_ctx"] = ctx
            x["legs"][0]["nba_ev"] = nbadata.check(x["legs"][0], ctx)
            x["analysis"] = formatting.analysis(x)


def _nba_send_candidate(state: dict, d: dict, now, ctx: dict | None = None) -> None:
    from . import nba
    l = d["legs"][0]
    if ctx is None:
        try:
            ctx = nba.context(l["home"], l["away"], l["kickoff"])   # bajas confirmadas a esta hora
        except Exception:
            traceback.print_exc()
    _nba_enrich(d, ctx, skip_absences=bool(ctx and any("key_out" in ctx[s_] for s_ in ("home", "away"))))
    contra = lambda x: (x["legs"][0].get("nba_ev") or {}).get("verdict") == "contra"  # noqa: E731
    if contra(d) and d.get("alt") and not contra(d["alt"]):
        alt = d.pop("alt")            # la B pasa a ser la sugerencia: la A va contra los datos
        alt["sport"] = "basketball"
        d.clear()
        d.update(alt)
    elif contra(d):
        ev = d["legs"][0]["nba_ev"]
        telegram.send(state["owner_chat"],
                      f"🏀 <b>{formatting.escape(formatting.team(l['home']))} vs {formatting.escape(formatting.team(l['away']))}</b>: "
                      f"sin pronóstico sugerido. La mejor opción ({formatting.escape(formatting.public_label(l))}) se habría "
                      f"cumplido solo en {ev['me'][0] + ev['op'][0]} de {ev['me'][1] + ev['op'][1]} partidos recientes. "
                      "El Bet Builder sí te llega.")
        return
    state["seq"] += 1
    pid = str(state["seq"])
    d.update(id=pid, status="candidate", created_at=_iso(now), stake_v=2, sport="basketball", pregame_pick=True)
    msg = telegram.send(state["owner_chat"], nba_candidate_text(d), NBA_BUTTONS(pid, bool(d.get("alt"))))
    d["owner_msg"] = msg["message_id"]
    state["picks"][pid] = d


def _nba_cover_odds(state: dict, now) -> None:
    """Una consulta de cuotas cubre los partidos de las próximas horas: deja en cola la opción A/B de cada uno
    (o una marca de «sin opción») para entregarla junto a la previa de su partido."""
    from . import nba
    queue = state.setdefault("nba_queue", [])
    frm, to = now, now + timedelta(hours=config.NBA_PICKS_LOOKAHEAD_H)
    markets = oddspapi.markets(sport_id=config.NBA_SPORT_ID)
    fixtures = oddspapi.upcoming_fixtures(_iso(frm), _iso(to), sport_id=config.NBA_SPORT_ID)
    by_id = {f["fixtureId"]: f for f in fixtures if f.get("tournamentId") == config.NBA_TOURNAMENT
             and frm <= store.parse_ts(f["startTime"]) <= to}
    busy = {l.get("fixture_id") for p in state["picks"].values() for l in p["legs"]
            if p["status"] in ("candidate", "selected", "published")}
    busy |= {(q.get("legs") or [q])[0].get("fixture_id") for q in queue}
    rows = oddspapi.odds_by_tournaments([config.NBA_TOURNAMENT]) if by_id else []
    state["nba_odds_until"] = _iso(to)   # cubierto (si la consulta falla, se reintenta en la próxima revisión)
    for row in rows:
        fx = by_id.get(row.get("fixtureId"))
        if not fx or fx["fixtureId"] in busy:
            continue
        opt = (nba.options_for_game(selections_for_fixture(fx, row, markets, "basketball"))
               if len(row.get("bookmakerOdds") or {}) >= 2 else None)
        queue.append(_nba_pick_dict(fx, *opt) if opt else
                     {"none": True, "fixture_id": fx["fixtureId"], "home": fx.get("participant1Name") or "",
                      "away": fx.get("participant2Name") or "", "kickoff": fx["startTime"]})


def _nba_take(state: dict, ko, h: str, a: str) -> dict | None:
    """Saca de la cola la entrada del partido (por hora y nombres de los equipos)."""
    queue = state.get("nba_queue") or []
    for q in queue:
        l = (q.get("legs") or [q])[0]
        if abs((store.parse_ts(q["kickoff"]) - ko).total_seconds()) > 20 * 60:
            continue
        names = (l.get("home") or "", l.get("away") or "")
        if any(_name_hit(h, n) for n in names) and any(_name_hit(a, n) for n in names):
            queue.remove(q)
            return q
    return None


def _ctx_for(ctx: dict | None, home: str) -> dict | None:
    """El contexto de ESPN en el orden local/visita del pick (OddsPapi puede tenerlos al revés)."""
    if not ctx or _name_hit(home, ctx["home"]["name"]):
        return ctx
    return dict(ctx, home=ctx["away"], away=ctx["home"])


def _nba_owner_flow(state: dict, now) -> None:
    """NBA, para cada partido y en este orden (todo a ti, ~70 min antes):
    1) previa: bajas (con aviso si falta alguien importante), forma, ESPN y noticias;
    2) pronóstico sugerido (opción A y B) armado con esas bajas;
    3) Bet Builder.
    Con eso decides y la apuesta va al VIP. A los ~30 min se revisan de nuevo las bajas y te aviso si cambió algo."""
    owner = state.get("owner_chat")
    if not owner or not config.NBA_ENABLED or not config.NBA_PREGAME_PICKS:
        return
    from . import nba, nbadata
    lo, hi = config.NBA_OWNER_BEFORE_MIN
    done = state.setdefault("nba_pre", {})
    events = _nba_events(now)
    due = [(eid, ko, h, a) for eid, ko, h, a in events
           if eid not in done and ko - timedelta(minutes=hi) <= now <= ko - timedelta(minutes=lo)]
    until = state.get("nba_odds_until")
    if due and not (until and max(ko for _e, ko, _h, _a in due) <= store.parse_ts(until)):
        try:
            _nba_cover_odds(state, now)
        except Exception:
            traceback.print_exc()
    for eid, ko, h, a in due:
        done[eid] = {"ko": _iso(ko), "key": [], "rechecked": False}
        mins = int((ko - now).total_seconds() // 60)
        ctx = None
        try:   # 1) previa
            ctx = nba.context(h, a, _iso(ko))
            nbadata.key_absences(ctx, _iso(ko))
            if ctx:
                done[eid]["key"] = [x["name"] for s_ in ("home", "away") for x in ctx[s_].get("key_out") or []]
                telegram.send(owner, nba.owner_previa(ctx, mins))
        except Exception:
            traceback.print_exc()
        try:   # 2) pronóstico A/B
            q = _nba_take(state, ko, h, a)
            if q and not q.get("none"):
                _nba_send_candidate(state, q, now, _ctx_for(ctx, q["legs"][0]["home"]))
            else:
                why = ("ninguna cuota en " f"{config.ODDS_MIN:.2f}–{config.ODDS_MAX:.2f} cerca de la justa" if q
                       else "no encontré sus cuotas")
                telegram.send(owner, f"🏀 {formatting.escape(a)} @ {formatting.escape(h)}: sin pronóstico sugerido ({why}).")
        except Exception:
            traceback.print_exc()
        try:   # 3) Bet Builder
            _builder_send(state, h, a, _iso(ko), "USA · NBA", "basketball", quiet=True)
        except Exception:
            traceback.print_exc()
    # Revisión de bajas a ~30 min: solo te escribo si apareció una baja importante nueva
    rlo, rhi = config.NBA_INJURY_RECHECK_MIN
    for eid, ko, h, a in events:
        info = done.get(eid)
        if not info or info.get("rechecked") or not (ko - timedelta(minutes=rhi) <= now <= ko - timedelta(minutes=rlo)):
            continue
        info["rechecked"] = True
        try:
            ctx = nba.context(h, a, _iso(ko))
            nbadata.key_absences(ctx, _iso(ko))
        except Exception:
            traceback.print_exc()
            continue
        if not ctx:
            continue
        new = [(ctx[s_]["name"], x) for s_ in ("home", "away") for x in ctx[s_].get("key_out") or []
               if x["name"] not in info["key"]]
        if not new:
            continue
        mine = [p for p in state["picks"].values() if p.get("sport") == "basketball" and p["status"] in ("candidate", "selected", "published")
                and abs((store.parse_ts(p["kickoff"]) - ko).total_seconds()) < 1200
                and _name_hit(h, p["legs"][0]["home"] + " " + p["legs"][0]["away"])]
        txt = (f"⚠️ <b>Cambio de último minuto · {formatting.escape(a)} @ {formatting.escape(h)}</b>\n"
               + "\n".join(f"• {formatting.escape(t)} no tendrá a {formatting.escape(x['name'])} "
                            f"({str(x['pts']).replace('.', ',')} pts por partido)" for t, x in new))
        if mine:
            txt += "\n\n" + "\n".join(f"Tu pick #{p['id']} ({'publicado' if p['status'] == 'published' else 'sin publicar'}): "
                                       "revisa si sigue valiendo antes del inicio." for p in mine)
        telegram.send(owner, txt)
    for eid in [k for k, v in done.items() if store.parse_ts(v["ko"]) < now - timedelta(hours=12)]:
        done.pop(eid)
    state["nba_queue"] = [q for q in state.get("nba_queue") or [] if store.parse_ts(q["kickoff"]) > now]


def _live_builders(state: dict) -> None:
    """Fútbol en vivo: avisos de líneas que se están cumpliendo al descanso (córners, tarjetas, goles, remates)."""
    owner = state.get("owner_chat")
    if not owner:
        return
    from . import livebb
    for text in livebb.scan(state):
        telegram.send(owner, text)


def _lineup_check(state: dict, p: dict, now) -> None:
    """Fútbol: con las alineaciones confirmadas (75-15 min antes), ¿juegan los goleadores? Si no, te aviso."""
    if (p["status"] != "published" or p.get("lineup_checked") or len(p["legs"]) != 1
            or (p["legs"][0].get("sport") or "soccer") != "soccer" or p.get("kind") == "builder"):
        return
    kick = store.parse_ts(p["kickoff"])
    if now > kick - timedelta(minutes=10):
        p["lineup_checked"] = "missed"
        return
    if now < kick - timedelta(minutes=75):
        return
    import requests as _rq
    from . import espn
    l = p["legs"][0]
    found = espn._find(l["home"], l["away"], l["kickoff"])
    if not found:
        return
    try:
        sm = _rq.get("https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary",
                     params={"event": found[0]["id"]}, timeout=25).json()
    except Exception:
        return
    starters = {str(((pl.get("athlete") or {}).get("id"))) for ro in sm.get("rosters") or []
                for pl in ro.get("roster") or [] if pl.get("starter")}
    if len(starters) < 18:
        return   # aún no están las alineaciones: se reintenta en la próxima revisión
    p["lineup_checked"] = "done"
    missing = []
    for t in sm.get("leaders") or []:
        team = (t.get("team") or {}).get("displayName") or ""
        for cat in t.get("leaders") or []:
            if cat.get("name") != "goalsLeaders":
                continue
            for ld in (cat.get("leaders") or [])[:1]:
                ath = ld.get("athlete") or {}
                goals = re.search(r"Goals: (\d+)", ld.get("displayValue") or "")
                if goals and int(goals.group(1)) >= 2 and str(ath.get("id")) not in starters:
                    missing.append(f"{ath.get('displayName')} ({team}, {goals.group(1)} goles)")
    owner = state.get("owner_chat")
    if not owner:
        return
    esc = formatting.escape
    head = f"📋 <b>Alineaciones confirmadas</b> · pick #{p['id']} · {esc(l['home'])} vs {esc(l['away'])}\n"
    if missing:
        telegram.send(owner, head + "⚠️ No es titular: " + esc("; ".join(missing))
                      + "\nRevisa si cambia algo para el pick (" + esc(formatting.outcome_label(l)) + ").")
    else:
        telegram.send(owner, head + "✅ Los goleadores de los dos equipos son titulares.")


def _nba_board(state: dict, p: dict, rep: dict, kind: str, photo=None, half_rep=None, title=None) -> tuple[bytes, dict]:
    """Imagen NBA (entretiempo o final) y datos usados."""
    from . import layouts, matchphoto, nbagame
    l = p["legs"][0]
    if kind == "half":
        st = nbagame.pick_status(l, rep, False, grade_leg)
    else:
        res = p.get("result") or grade_leg(l, rep["home"]["score"], rep["away"]["score"]) or "?"
        tot = rep["home"]["score"] + rep["away"]["score"]
        st = (res, {"W": "VERDE", "L": "ROJA", "V": "NULA"}.get(res, "Resultado")
              + f" · terminó {rep['home']['score']}-{rep['away']['score']} ({tot} puntos en total).")
    fig = nbagame.hero(rep)
    if kind == "half":   # en el descanso: el máximo anotador del partido
        allp = [(x, s) for s in ("home", "away") for x in rep[s]["leaders"][:1]]
        fig = max(allp, key=lambda t: t[0]["pts"]) if allp else None
    if photo is None and kind != "half":   # al final: la figura; si no hay foto suya, otro líder; luego referentes
        tries = ([(fig[0]["name"], fig[1])] if fig else []) + \
                [(x["name"], s_) for s_ in ("home", "away") for x in rep[s_]["leaders"][:3]
                 if not fig or x["name"] != fig[0]["name"]]
        try:
            for name, s_ in tries[:5]:
                photo = matchphoto.for_scorer(name, [rep[s_]["name"], rep[s_]["short"]], "basketball")
                if photo:
                    break
            for s_ in ([fig[1]] if fig else []) + ["home", "away"]:
                if photo:
                    break
                photo = matchphoto.referent([rep[s_]["name"], rep[s_]["short"]], "basketball")
        except Exception:
            traceback.print_exc()
    other = "away" if fig and fig[1] == "home" else "home"
    ld = rep[other]["leaders"][:1]
    sel = formatting.outcome_label(l)
    data = {"kind": kind, "report": rep, "eyebrow": "NBA · VIP" if kind == "half" else "NBA",
            "headline": title or nbagame.headline(rep, kind, half_rep),
            "photo": photo[0] if photo else None, "credit": photo[1]["text"] if photo and photo[1] else None,
            "figure": (fig[0]["name"], nbagame.line_of(fig[0])) if fig else None,
            "leaders_line": f"{rep[other]['short']}: {ld[0]['name']} {nbagame.line_of(ld[0])}" if ld else "",
            "stats": nbagame.stat_rows(rep)[:3], "pick_label": sel[:sel.index(" (")] if " (" in sel else sel,
            "odds": formatting.odds(p["price"]), "status": st,
            "photo_credit": photo[1] if photo else None}
    theme = (p.get("recap") or {}).get("theme") if kind == "final" else p.get("theme")
    return layouts.nba_board(data, theme or "dark"), data


def _halftime_nba(state: dict, p: dict, now) -> None:
    """NBA: al terminar el 2º cuarto, publica en el VIP marcador por cuarto, líderes, tiro y cómo va el pick."""
    if p["status"] != "published" or p.get("ht_done") or "vip" not in (p.get("channel_msgs") or {}):
        return
    kick = store.parse_ts(p["kickoff"])
    if now < kick + timedelta(minutes=50):
        return
    if now > kick + timedelta(minutes=170):
        p["ht_done"] = "missed"
        return
    from . import nbagame
    l = p["legs"][0]
    live = nbagame.report(l["home"], l["away"], l["kickoff"])
    if not live:
        return
    if live["completed"] or live["period"] > 3:
        p["ht_done"] = "missed"
        return
    clock = live.get("clock") or ""
    mins = int(clock.split(":")[0]) if ":" in clock and clock.split(":")[0].isdigit() else 0
    if not (live["status_name"] == "STATUS_HALFTIME" or (live["period"] == 3 and mins >= 8)):
        return
    rep = nbagame.report(l["home"], l["away"], l["kickoff"], half=True)
    p["ht_done"] = "sent"
    p["nba_half"] = {"home": rep["home"]["score"], "away": rep["away"]["score"]}
    try:
        image, data = _nba_board(state, p, rep, "half")
    except Exception:
        traceback.print_exc()
        image, data = None, None
    st = data["status"] if data else nbagame.pick_status(l, rep, False, grade_leg)
    text = nbagame.half_caption(p, rep, st)
    mid = p["channel_msgs"]["vip"]
    try:
        if image and formatting.caption_fits(text):
            telegram.send_photo(state["vip_chat"], image, caption=text, reply_to=mid)
        else:
            if image:
                telegram.send_photo(state["vip_chat"], image, reply_to=mid)
            telegram.send(state["vip_chat"], text, reply_to=mid)
    except telegram.TelegramError as e:
        print(f"No se pudo publicar el entretiempo NBA: {e}")
    if state.get("owner_chat"):
        telegram.send(state["owner_chat"], f"⏸️ Publiqué en el VIP el entretiempo NBA del pick #{p['id']} "
                                           f"({rep['home']['score']}-{rep['away']['score']}).")


def _recap_nba(state: dict, p: dict, reuse: bool = False) -> bool:
    """Final NBA: imagen con marcador por cuarto, figura y resultado del pick; para el VIP e Instagram."""
    from . import nbagame
    l = p["legs"][0]
    old = p.get("recap") or {}
    rep = old.get("report") if reuse else None
    if not rep:
        rep = nbagame.report(l["home"], l["away"], l["kickoff"])
        if not rep or not rep["completed"]:
            return False
    photo = None
    if old.get("photo_src") == "user" and os.path.exists(_upload_file(p)):
        with open(_upload_file(p), "rb") as f:
            photo = (f.read(), None)
    elif reuse and old.get("photo_cache") and os.path.exists(old["photo_cache"]):
        with open(old["photo_cache"], "rb") as f:
            photo = (f.read(), old.get("credit"))
    half = p.get("nba_half")
    half_rep = {"home": {"score": half["home"]}, "away": {"score": half["away"]}} if half else None
    if old.get("mode") == "raw" and os.path.exists(_upload_file(p)):
        from . import postimage
        with open(_upload_file(p), "rb") as f:
            image = postimage.fit_instagram(f.read())
        data = {"headline": old.get("custom_title") or nbagame.headline(rep, "final", half_rep), "photo_credit": None}
    else:
        image, data = _nba_board(state, p, rep, "final", photo=photo, half_rep=half_rep, title=old.get("custom_title"))
    path = _recap_file(p)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(image)
    cache = old.get("photo_cache") or _upload_file(p, "recapphoto")
    credit = data.get("photo_credit")
    if data.get("photo") and old.get("photo_src") != "user":   # guardar la foto para cambiar modo o titular
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "wb") as f:
            f.write(data["photo"])
    p["recap"] = {"title": data["headline"], "custom_title": old.get("custom_title"), "credit": credit,
                  "msgs": old.get("msgs") or {}, "panel": old.get("panel"), "hero": None, "report": rep,
                  "photo_src": old.get("photo_src"), "mode": old.get("mode"), "v": RECAP_TEXT_V,
                  "theme": old.get("theme"), "layout": "nba", "photo_cache": cache,
                  "tg": nbagame.final_caption(p, rep, data["headline"], credit),
                  "ig": nbagame.final_caption(p, rep, data["headline"], credit, ig=True)}
    p.pop("recap_pending", None)
    p["ig_kit_sent"] = True
    _recap_panel(state, p)
    return True


def _halftime_check(state: dict, p: dict, now) -> None:
    """Entretiempo: publica en los canales del pick el marcador al descanso, goles, estadísticas y cómo va."""
    if p.get("kind") == "builder":
        return
    if _vip_only(p) and len(p["legs"]) == 1:
        _halftime_nba(state, p, now)
        return
    if (p["status"] != "published" or p.get("ht_done") or len(p["legs"]) != 1
            or (p["legs"][0].get("sport") or "soccer") != "soccer" or not p.get("channel_msgs")):
        return
    kick = store.parse_ts(p["kickoff"])
    if now < kick + timedelta(minutes=44):
        return
    if now > kick + timedelta(minutes=85):
        p["ht_done"] = "missed"
        return
    from . import espn, halftime, layouts, matchphoto
    l = p["legs"][0]
    rep = espn.live_report(l["home"], l["away"], l["kickoff"])
    if not rep or rep.get("state") == "post":
        if rep:
            p["ht_done"] = "missed"
        return
    if not halftime.is_halftime(rep):
        return
    p["ht_done"] = "sent"
    st = halftime.status(l, rep["home"]["score"], rep["away"]["score"], grade_leg)
    photo = None   # en el entretiempo, sin fotos: solo marcador y estadísticas (las fotos quedan para el final)
    league = (l.get("league") or "").split("·")[-1].strip()
    sel = formatting.outcome_label(l)
    data = {"report": rep, "eyebrow": league or "Pick en juego", "photo": photo[0] if photo else None,
            "credit": photo[1]["text"] if photo and photo[1] else None, "stats": halftime.stats(rep),
            "pick_label": sel[:sel.index(" (")] if " (" in sel else sel, "odds": formatting.odds(p["price"]),
            "status": st}
    try:
        image = layouts.halftime(data, p.get("theme") or "dark")
    except Exception:
        traceback.print_exc()
        image = None
    text = halftime.caption(p, rep, st)
    for where, mid in (p.get("channel_msgs") or {}).items():
        chat = state["vip_chat"] if where == "vip" else config.FREE_CHANNEL
        try:
            if image and formatting.caption_fits(text):
                telegram.send_photo(chat, image, caption=text, reply_to=mid)
            else:
                if image:
                    telegram.send_photo(chat, image, reply_to=mid)
                telegram.send(chat, text, reply_to=mid)
        except telegram.TelegramError as e:
            print(f"No se pudo publicar el entretiempo en {where}: {e}")
    if state.get("owner_chat"):
        telegram.send(state["owner_chat"], f"⏸️ Publiqué el entretiempo del pick #{p['id']} "
                                           f"({rep['home']['score']}-{rep['away']['score']}).")


def _recap_share(state: dict, p: dict, where: str) -> None:
    chat = state["vip_chat"] if where == "vip" else config.FREE_CHANNEL
    r = p["recap"]
    with open(_recap_file(p), "rb") as f:
        image = f.read()
    reply = (p.get("channel_msgs") or {}).get(where)
    text = r["tg"]
    if formatting.caption_fits(text):
        r["msgs"][where] = telegram.send_photo(chat, image, caption=text, reply_to=reply)["message_id"]
    else:
        r["msgs"][where] = telegram.send_photo(chat, image, reply_to=reply)["message_id"]
        telegram.send(chat, text)


def _recap_fix(state: dict, p: dict) -> list[str]:
    """Rehace el postpartido de un pick (otra foto, mismo resumen) y lo corrige donde ya salió:
    edita la imagen en VIP/Gratis y prepara el Reel nuevo para Instagram."""
    notes = []
    r = p.get("recap") or {}
    old_reel = r.pop("reel", None)
    if r.get("photo_src") != "user":
        r.pop("credit", None)
    if not _recap(state, p, reuse=True):
        return ["⚠️ No pude rehacer el postpartido (ESPN no respondió). Reintenta en unos minutos."]
    r = p["recap"]
    with open(_recap_file(p), "rb") as f:
        image = f.read()
    for where, mid in (r.get("msgs") or {}).items():
        chat = state["vip_chat"] if where == "vip" else config.FREE_CHANNEL
        name = "VIP" if where == "vip" else "Gratis"
        cap = r["tg"] if formatting.caption_fits(r["tg"]) else None
        if telegram.edit_photo(chat, mid, image, cap):
            notes.append(f"{name}: imagen corregida (mismo mensaje)")
        else:
            notes.append(f"⚠️ {name}: no pude editar la imagen; bórrala y compártela de nuevo desde el panel")
    from . import instagram
    if r.get("reel") and old_reel:   # siempre un nombre nuevo: que Instagram no reciba la versión vieja en caché
        new_key = f"{old_reel}-v{int(store.now_utc().timestamp())}"
        os.replace(instagram.video_path(old_reel), instagram.video_path(new_key))
        r["reel"] = new_key
    st_ = p.get("ig_res_status")
    p.pop("ig_res_job", None)
    if st_ == "queued":
        notes.append("Instagram: aún no salía; saldrá el Reel corregido")
    elif st_ == "posted":
        owner = state.get("owner_chat")
        if owner and r.get("reel"):
            with open(instagram.video_path(r["reel"]), "rb") as f:
                msg = telegram.send_video(owner, f.read(), caption=f"🎬 <b>Reel corregido · pick #{p['id']}</b>\n"
                                          "Instagram no deja al bot borrar publicaciones: borra el Reel anterior desde la app "
                                          "y toca «Publicar versión nueva».")
            telegram.set_buttons(owner, msg["message_id"], [[("📸 Publicar versión nueva", f"rp:{p['id']}")],
                                                            [("Dejar Instagram como está", f"ipn:{p['id']}")]])
            notes.append("Instagram: te mandé el Reel corregido con el botón para publicarlo")
    return notes


def _recap_fix_file(state: dict) -> None:
    """data/recap_fix.json ({"id": "...", "pid": "117"}): rehace y corrige un postpartido ya compartido, una vez."""
    import json
    path = os.path.join(config.ROOT, "data", "recap_fix.json")
    owner = state.get("owner_chat")
    if not os.path.exists(path) or not owner:
        return
    try:
        with open(path, encoding="utf-8") as f:
            req = json.load(f)
    except Exception:  # noqa: BLE001
        return
    if not req.get("id") or req["id"] in (state.get("recap_fix_done") or []):
        return
    state.setdefault("recap_fix_done", []).append(req["id"])
    p = state["picks"].get(str(req.get("pid", "")).lstrip("#"))
    if not p:
        telegram.send(owner, "⚠️ No encontré el pick para corregir su postpartido.")
        return
    try:
        notes = _recap_fix(state, p)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        notes = [f"⚠️ falló la corrección: {e}"]
    telegram.send(owner, f"🔧 <b>Postpartido del pick #{p['id']} corregido</b> (la foto no era del partido)\n"
                  + "\n".join(f"• {formatting.escape(n)}" for n in notes))


def _revoke_command(state: dict, text: str) -> None:
    owner = state["owner_chat"]
    name = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
    inv = [i for i in state.get("invites") or [] if i["name"].lower() == name.lower() and not i.get("revoked")]
    codes = [c for c in (state.get("guest_codes") or {}).values()
             if c["name"].lower() == name.lower() and not c.get("used_by") and not c.get("revoked")]
    for c in codes:   # enlace personal aún sin usar: deja de servir
        c["revoked"] = True
    if codes and not inv:
        telegram.send(owner, f"🚫 Enlace personal de {formatting.escape(name)} anulado (todavía no lo usaba).")
        return
    if not inv:
        lista = ", ".join(i["name"] for i in state.get("invites") or [] if not i.get("revoked")) or "ninguno"
        telegram.send(owner, f"No encontré un enlace activo para «{formatting.escape(name)}». Activos: {formatting.escape(lista)}")
        return
    for i in inv:
        try:
            telegram._call("revokeChatInviteLink", chat_id=state["vip_chat"], invite_link=i["link"])
        except telegram.TelegramError as e:
            print(f"No se pudo anular el enlace: {e}")
        i["revoked"] = True
    telegram.send(owner, f"🚫 Enlace de {formatting.escape(name)} anulado. Si ya había entrado, sigue en el canal "
                         "(puedes sacarlo desde Suscriptores).")


def _teaser(state: dict, p: dict, reveal: str | None, vip: bool = False) -> None:
    """Adelanto en modo día para historias: pistas del pick y el pick tapado hasta la revelación."""
    from . import instagram, postimage, teaser
    owner = state["owner_chat"]
    image = postimage.render_teaser(teaser.teaser_data(p, reveal, vip))
    instagram.save_image(f"story-{p['id']}", image)
    p["teaser"] = {"reveal": reveal, "vip": vip}
    p.pop("ig_story_status", None)
    msg = telegram.send_photo(owner, image, caption=(
        f"📲 <b>Adelanto del pick #{p['id']}</b> (historia)\n"
        + (f"Se revela a las {reveal}." if reveal else
           f"Sin hora de revelación. Para ponerla: /adelanto {p['id']} 10:00")))
    p["teaser"]["msg"] = msg["message_id"]
    telegram.set_buttons(owner, msg["message_id"], TEASER_BUTTONS(p))


def TEASER_BUTTONS(p: dict) -> list:
    pid, st = p["id"], p.get("ig_story_status")
    return [[("✅ Historia publicada" if st == "posted" else "⏳ Historia en cola" if st == "queued"
              else "📲 Subir historia a Instagram", "noop" if st in ("queued", "posted") else f"ia:{pid}")],
            [("✅ En Gratis", "noop") if (p.get("teaser") or {}).get("free_msg")
             else ("🎁 Enviar también al canal Gratis", f"ag:{pid}")]]


def _teaser_command(state: dict, text: str) -> None:
    """/adelanto [N] [HH:MM] [vip]"""
    from . import teaser
    owner = state["owner_chat"]
    parts = text.split()[1:]
    now = store.now_utc()
    pid = next((x.lstrip("#") for x in parts if x.lstrip("#").isdigit()), None)
    if pid:
        p = state["picks"].get(pid)
    else:
        live = [x for x in state["picks"].values() if x["status"] in ("selected", "published")
                and store.parse_ts(x["kickoff"]) > now and not _vip_only(x)]
        live.sort(key=lambda x: (bool(x.get("free")), x.get("created_at") or ""), reverse=True)
        p = live[0] if live else None
    if not p or p["status"] not in ("selected", "published") or store.parse_ts(p["kickoff"]) <= now:
        telegram.send(owner, "Usa /adelanto, el número del pick y (si quieres) la hora en que lo revelas. "
                             "Ejemplo: /adelanto 8 10:00\nEl pick tiene que estar elegido y su partido aún no empieza.")
        return
    if _vip_only(p):
        telegram.send(owner, "La NBA es exclusiva del VIP: no lleva adelanto público.")
        return
    _teaser(state, p, teaser.parse_reveal(" ".join(x for x in parts if x.lstrip("#") != pid)),
            vip=any(x.lower() == "vip" for x in parts))


def _news_command(state: dict, text: str) -> None:
    """/postpartido Vasco vs Boca | Sudamericana — post partido de cualquier partido terminado (sin pick)."""
    import re as _re
    from . import espn
    owner = state["owner_chat"]
    body = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
    body, _, league = body.partition("|")
    teams = _re.split(r"\s+(?:vs\.?|v|-|contra)\s+", body.strip(), maxsplit=1, flags=_re.I)
    if len(teams) != 2 or not all(t.strip() for t in teams):
        telegram.send(owner, "Usa: /postpartido Vasco vs Boca | Sudamericana\n"
                             "(la liga después de la barra es opcional; busca partidos terminados de los últimos 3 días)")
        return
    found = espn.find_recent(teams[0].strip(), teams[1].strip())
    if not found:
        telegram.send(owner, "No encontré ese partido terminado en ESPN en los últimos 3 días. "
                             "Revisa los nombres (como aparecen en ESPN).")
        return
    rep, kickoff = found
    state["news_seq"] = state.get("news_seq", 0) + 1
    nid = f"N{state['news_seq']}"
    state["picks"][nid] = {"id": nid, "status": "news", "news": True, "kind": "news", "price": 0, "stake": 0,
                           "created_at": _iso(store.now_utc()), "kickoff": kickoff, "result": None,
                           "legs": [{"home": rep["home"]["name"], "away": rep["away"]["name"], "kickoff": kickoff,
                                     "league": league.strip(), "sport": "soccer"}],
                           "recap": {"report": rep}}
    telegram.send(owner, f"⚽ {formatting.escape(rep['home']['name'])} {rep['home']['score']}-"
                         f"{rep['away']['score']} {formatting.escape(rep['away']['name'])}: armando la imagen…")
    if not _recap(state, state["picks"][nid], reuse=True):
        telegram.send(owner, "⚠️ No pude armar la imagen. Intenta de nuevo en un rato.")


def _title_command(state: dict, text: str) -> None:
    owner = state["owner_chat"]
    parts = text.split(maxsplit=2)
    p = state["picks"].get(parts[1].lstrip("#")) if len(parts) > 1 else None
    if not p or len(parts) < 3:
        telegram.send(owner, "Usa /titular, el número del pick y el titular. Ejemplo: /titular 8 MARACA-NAZO\n"
                             "El guion marca dónde se parte en dos líneas (la segunda va en verde).")
        return
    if not p.get("recap"):
        telegram.send(owner, f"El pick #{p['id']} todavía no tiene imagen post partido.")
        return
    p["recap"]["custom_title"] = parts[2].strip()[:24]
    if p["recap"].get("mode") == "raw":
        telegram.send(owner, "Ese post usa tu imagen tal cual (sin titular). Para usar el diseño, adjunta la "
                             "imagen de nuevo y elige «Usar dentro del diseño».")
        return
    telegram.send(owner, "✏️ Generando la imagen con el nuevo titular…")
    if not _recap(state, p, reuse=True):
        telegram.send(owner, "⚠️ No pude volver a leer el partido en ESPN. Intenta de nuevo en un rato.")
    elif p.get("ig_res_status") in ("queued", "posted"):
        telegram.send(owner, "Ojo: en Instagram ya quedó la versión anterior.")



def _receive_upload(state: dict, msg: dict) -> None:
    """Llegó una imagen tuya para el post partido: la guarda y pregunta cómo usarla."""
    owner = state["owner_chat"]
    wait = state.get("await_photo") or {}
    kind = wait.get("kind") or "recap"
    p = state["picks"].get(wait.get("pid") or "")
    ok = p and (p.get("recap") if kind == "recap" else p["status"] in ("selected", "published"))
    if not ok or store.now_utc() > store.parse_ts(wait["until"]):
        state.pop("await_photo", None)
        telegram.send(owner, "Para usar una imagen tuya, primero toca «🖼 Adjuntar mi imagen» en el post partido.")
        return
    doc = msg.get("document") or {}
    if msg.get("photo"):
        file_id = max(msg["photo"], key=lambda x: x.get("file_size") or x.get("width", 0))["file_id"]
    elif (doc.get("mime_type") or "").startswith("image/"):
        file_id = doc["file_id"]
    else:
        telegram.send(owner, "Eso no parece una imagen. Mándala como foto o como archivo de imagen (JPG o PNG).")
        return
    import io
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(telegram.download(file_id))).convert("RGB")
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        telegram.send(owner, "⚠️ No pude abrir esa imagen. Prueba con otra (JPG o PNG).")
        return
    small_note = ("\n⚠️ Es una imagen chica ({}x{} px): puede verse pixelada. Si la tienes más grande, "
                  "mándala como archivo (📎 → Archivo) para que Telegram no la comprima.".format(*im.size)
                  if min(im.size) < 700 else "")
    if max(im.size) > 2160:
        k = 2160 / max(im.size)
        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    path = _upload_file(p, kind)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path, "JPEG", quality=92)
    state.pop("await_photo", None)
    pre = "x" if kind == "recap" else "y"
    what = "el post partido" if kind == "recap" else "la imagen"
    telegram.send(owner, f"📥 Recibí tu imagen para {what} del pick #{p['id']}. ¿Cómo la uso?\n"
                         "🎨 Dentro del diseño: la recorto sola dejando al protagonista a la derecha.\n"
                         "📤 Tal cual: la ajusto a 1080x1350 sin cortarla (si no calza, con fondo difuminado)."
                         + small_note,
                  [[("🎨 Usar dentro del diseño", f"{pre}d:{p['id']}")], [("📤 Subir tal cual", f"{pre}r:{p['id']}")],
                   [("Cancelar", f"xc:{p['id']}")]])


# ---------------------------------------------------------------- botones y mensajes
def _norm_code(x: str) -> str:
    return x.strip().strip("<>\"'`").strip().lower()


def _code_ok(text: str) -> bool:
    parts = text.split(maxsplit=1)
    return bool(config.LINK_CODE) and len(parts) == 2 and _norm_code(parts[1]) == _norm_code(config.LINK_CODE)


def _handle_update(state: dict, u: dict) -> None:
    owner = state.get("owner_chat")

    msg = u.get("message")
    if msg and msg.get("chat", {}).get("type") == "private":
        text = (msg.get("text") or "").strip()
        chat = msg["chat"]["id"]
        if chat == owner and (msg.get("photo") or msg.get("document")):
            _receive_upload(state, msg)
            return
        if chat == owner and text and not text.startswith("/") and _builder_odds(state, text):
            return
        if chat != owner and text.lower().startswith("/start"):
            from . import guests
            guests.handle_start(state, msg)
            return
        if text.lower().startswith("/vincular") and not text.lower().startswith("/vincular_vip"):
            if _code_ok(text):
                state["owner_chat"] = chat
                telegram.send(chat, "🔗 Listo, este chat quedó vinculado como dueño de Stakevision.")
            else:
                telegram.send(chat, "⚠️ Ese código no coincide con LINK_CODE. Revísalo y vuelve a enviar /vincular CODIGO")
        elif chat == owner and text.startswith("/estado"):
            telegram.send(chat, _status_text(state))
        elif chat == owner and text.lower().startswith("/builder"):
            _builder_command(state, text)
        elif chat == owner and text.lower().startswith("/hoy"):
            telegram.send(chat, _today_text(state))
        elif chat == owner and (text.lower().startswith(("/invitar", "/entretiempo", "/combinada", "/vivo"))
                                or (text.lower().startswith(("/buscar", "/envivo"))
                                    and "nba" in text.lower().split()[1:])):
            telegram.send(chat, _moved_hint(text))
        elif chat == owner and text.lower().startswith("/gratis"):
            _free_command(state, text)
        elif chat == owner and text.lower().startswith("/partido"):
            _request_search(state, text)
        elif chat == owner and text.lower().startswith("/enlace"):
            from . import guests
            guests.link_command(state, text)
        elif chat == owner and text.lower().startswith("/mensaje"):
            from . import guests
            guests.message_command(state, text)
        elif chat == owner and text.lower().startswith("/contactos"):
            from . import guests
            guests.contacts_command(state)
        elif chat == owner and text.lower().startswith("/anular"):
            _revoke_command(state, text)
        elif chat == owner and text.lower().startswith("/adelanto"):
            _teaser_command(state, text)
        elif chat == owner and text.lower().startswith("/postpartido"):
            _news_command(state, text)
        elif chat == owner and text.lower().startswith("/titular"):
            _title_command(state, text)
        elif chat == owner and text.lower().startswith("/compartir"):
            _share_command(state, text)
        elif chat == owner and text.lower().startswith("/envivo"):
            _request_search(state, text, live=True)
        elif chat == owner and text.lower().startswith("/buscar"):
            _request_search(state, text)
        elif chat == owner and text.lower().startswith(("/ayuda", "/start", "/help")):
            telegram.send(chat, HELP_TEXT)
        return

    post = u.get("channel_post")
    if post:
        text = (post.get("text") or "").strip()
        if text.lower().startswith("/vincular_vip") and _code_ok(text):
            state["vip_chat"] = post["chat"]["id"]
            if owner:
                telegram.send(owner, "🔗 Canal VIP vinculado. Ya puedes borrar el mensaje /vincular_vip del canal.")
        return

    cb = u.get("callback_query")
    if not cb:
        return
    if cb.get("message", {}).get("chat", {}).get("id") != owner:
        telegram.answer(cb["id"], "No autorizado")
        return
    action, _, pid = (cb.get("data") or "").partition(":")
    if action in ("nq", "nx", "np", "ni", "nn"):   # noticias para Instagram
        from . import newswatch
        newswatch.callback(state, cb, action, pid)
        return
    p = state["picks"].get(pid)
    if not p:
        telegram.answer(cb["id"])
        return
    if action in ("fa", "fo", "fc"):
        _auto_free_callback(state, cb, action, p)
        return

    if action == "sb":   # NBA: elegir la opción B (pasa a ser el pick)
        if p["status"] != "candidate" or not p.get("alt"):
            telegram.answer(cb["id"], "Ya estaba procesado")
            return
        alt = p.pop("alt")
        p["alt_original"] = {k: p[k] for k in ("legs", "price", "prob", "edge", "stake", "tier", "kind", "analysis")}
        p.update({k: alt[k] for k in ("legs", "price", "prob", "edge", "stake", "tier", "kind", "analysis")})
        p["chosen_option"] = "B"
        action = "s"

    if action == "s":   # elegir: generar la imagen y preguntar destinos
        if p["status"] != "candidate":
            telegram.answer(cb["id"], "Ya estaba procesado")
            return
        if _expires(p) <= store.now_utc():
            p["status"] = "expired"
            telegram.edit_buttons_off(owner, cb["message"]["message_id"], "⌛ Ya no está vigente")
            telegram.answer(cb["id"], "Llegó tarde")
            return
        p["status"] = "selected"
        telegram.edit_buttons_off(owner, cb["message"]["message_id"], "🖼 Elegido: imagen generada abajo")
        _share_panel(state, p)
        telegram.answer(cb["id"], "Imagen generada")
        return

    if action in ("pv", "pf", "pg", "pi"):
        if p["status"] not in ("selected", "published"):
            telegram.answer(cb["id"], "Este pick ya no está disponible")
            return
        if action != "pv" and _vip_only(p):
            telegram.answer(cb["id"], "La NBA es exclusiva del VIP")
            telegram.set_buttons(owner, cb["message"]["message_id"], SHARE_BUTTONS(p))
            return
        late = _expires(p) <= store.now_utc() and not p.get("live")
        if action in ("pv", "pf", "pg"):
            if late and not p.get("channel_msgs"):
                telegram.answer(cb["id"], "El partido ya empezó: no se publica")
                return
            if action != "pg" and not state.get("vip_chat"):
                telegram.answer(cb["id"], "Primero vincula el canal VIP con /vincular_vip")
                return
            _publish(state, p, free=(action in ("pf", "pg")), vip_too=(action != "pg"))
            telegram.answer(cb["id"], {"pv": "Publicado en VIP", "pg": "Publicado en Gratis"}.get(action, "Publicado en VIP + Gratis"))
        else:
            from . import instagram
            if not instagram.enabled(state):
                telegram.answer(cb["id"], "Instagram no está conectado")
                return
            image = _pick_image(p, "free")   # Instagram es público: versión «PICK GRATIS»
            if not image:
                telegram.answer(cb["id"], "No se pudo generar la imagen")
                return
            from . import postimage
            instagram.save_image(f"pre-{p['id']}", postimage.fit_instagram(image))
            p["ig_pre_status"] = "queued"
            p["ig_pre_caption"] = formatting.instagram_pick_caption(p)
            telegram.answer(cb["id"], "Se publica en Instagram en unos minutos")
        telegram.set_buttons(owner, cb["message"]["message_id"], SHARE_BUTTONS(p))
        return

    if action == "u":   # deshacer un descarte
        mid = cb["message"]["message_id"]
        if p["status"] != "rejected":
            telegram.answer(cb["id"], "Ya no estaba descartado")
            return
        if _expires(p) <= store.now_utc():
            p["status"] = "expired"
            telegram.edit_buttons_off(owner, mid, "⌛ Ya no está vigente")
            telegram.answer(cb["id"], "Llegó tarde: ya no está vigente")
            return
        p["status"] = p.pop("prev_status", None) or "candidate"
        telegram.set_buttons(owner, mid, CANDIDATE_BUTTONS(pid) if p["status"] == "candidate"
                             else BUILDER_BUTTONS(pid) if p["status"] == "bb" else SHARE_BUTTONS(p))
        telegram.answer(cb["id"], "Recuperado")
        return

    if action == "bq":   # Bet Builder: esperar la cuota real
        if p["status"] != "bb":
            telegram.answer(cb["id"], "Ya estaba procesado")
            return
        state["await_odds"] = {"pid": pid, "until": _iso(store.now_utc() + timedelta(hours=3))}
        telegram.send(owner, f"✏️ Escríbeme la cuota real del Bet Builder #{pid} tal como sale en tu app (ej. 3.10).")
        telegram.answer(cb["id"], "Esperando la cuota")
        return

    if action in ("a", "f", "r"):
        if p["status"] not in ("candidate", "selected", "bb") or (action != "r" and p["status"] != "candidate"):
            telegram.answer(cb["id"], "Ya estaba procesado")
            return
        if action == "r":
            if p.get("channel_msgs") or p.get("ig_pre_status"):
                telegram.answer(cb["id"], "Ya se publicó en algún lado")
                return
            p["prev_status"], p["status"] = p["status"], "rejected"
            telegram.set_buttons(owner, cb["message"]["message_id"], [[("❌ Descartado · ↩️ Deshacer", f"u:{pid}")]])
            telegram.answer(cb["id"], "Descartado (puedes deshacerlo)")
            return
        if store.parse_ts(p["kickoff"]) <= store.now_utc():
            p["status"] = "expired"
            telegram.edit_buttons_off(owner, cb["message"]["message_id"], "⌛ El partido ya empezó")
            telegram.answer(cb["id"], "Llegó tarde: el partido ya empezó")
            return
        if not state.get("vip_chat"):
            telegram.answer(cb["id"], "Primero vincula el canal VIP con /vincular_vip")
            return
        _publish(state, p, free=(action == "f") and not _vip_only(p))
        note = "✅ Publicado en VIP + Gratis" if action == "f" else "✅ Publicado en VIP"
        telegram.edit_buttons_off(owner, cb["message"]["message_id"], note)
        telegram.answer(cb["id"], "Publicado")

    elif action in ("th", "dl"):   # modo día / noche u otro diseño de la versión con foto del pick
        if p["status"] not in ("selected", "published") or p.get("pick_style") != "photo":
            telegram.answer(cb["id"], "No disponible")
            return
        from . import layouts
        if action == "th":
            p["theme"] = "dark" if p.get("theme") == "light" else "light"
            telegram.answer(cb["id"], "Cambiando a modo " + ("día…" if p["theme"] == "light" else "noche…"))
        else:
            p["pick_layout"] = layouts.cycle(p.get("pick_layout"), "pick")
            telegram.answer(cb["id"], "Diseño: " + layouts.LAYOUT_NAMES[p["pick_layout"]])
        try:
            _make_pick_photo(p, reuse=True)
        except Exception:
            traceback.print_exc()
            telegram.send(owner, "⚠️ No pude cambiar el modo.")
            return
        if p.get("share_msg"):
            telegram.edit_buttons_off(owner, p["share_msg"], "↪️ Reemplazada por la versión de abajo")
        _share_panel(state, p)
        return

    elif action in ("st", "ad", "ia", "ag"):   # estilo de la imagen del pick y adelanto para historias
        if action == "st":
            if p["status"] not in ("selected", "published"):
                telegram.answer(cb["id"], "Este pick ya no está disponible")
                return
            p["pick_style"] = "coupon"   # volver al cupón (antes del partido, solo la apuesta)
            p.pop("pick_raw", None)
            if p.get("share_msg"):
                telegram.edit_buttons_off(owner, p["share_msg"], "↪️ Reemplazada por la versión de abajo")
            _share_panel(state, p)
            telegram.answer(cb["id"])
            return
        if action in ("ad", "ia", "ag") and _vip_only(p):
            telegram.answer(cb["id"], "La NBA es exclusiva del VIP: sin adelanto público")
            return
        if action == "ad":
            if store.parse_ts(p["kickoff"]) <= store.now_utc():
                telegram.answer(cb["id"], "El partido ya empezó")
                return
            telegram.answer(cb["id"], "Generando el adelanto…")
            _teaser(state, p, None)
            return
        if not p.get("teaser"):
            telegram.answer(cb["id"], "Primero genera el adelanto")
            return
        if action == "ia":
            from . import instagram
            if not instagram.enabled(state):
                telegram.answer(cb["id"], "Instagram no está conectado")
                return
            p["ig_story_status"] = "queued"
            telegram.answer(cb["id"], "La historia se publica en un par de minutos")
        else:
            if p["teaser"].get("free_msg"):
                telegram.answer(cb["id"], "Ya estaba en Gratis")
                return
            from . import instagram
            with open(instagram.image_path(f"story-{p['id']}"), "rb") as f:
                p["teaser"]["free_msg"] = telegram.send_photo(config.FREE_CHANNEL, f.read())["message_id"]
            telegram.answer(cb["id"], "Enviado al canal Gratis")
        telegram.set_buttons(owner, cb["message"]["message_id"], TEASER_BUTTONS(p))
        return

    elif action in ("yp", "yd", "yr"):   # tu propia imagen para el pick (antes del partido)
        if p["status"] not in ("selected", "published"):
            telegram.answer(cb["id"], "Este pick ya no está disponible")
            return
        if action == "yp":
            state["await_photo"] = {"pid": pid, "kind": "pick", "until": _iso(store.now_utc() + timedelta(hours=2))}
            telegram.send(owner, f"🖼 Mándame ahora la imagen para el pick #{pid} (como foto o como archivo).\n"
                                 "Usa solo imágenes tuyas o con permiso de uso: las fotos de agencias o "
                                 "medios pueden traer reclamos de copyright en Instagram.")
            telegram.answer(cb["id"], "Esperando tu imagen")
            return
        up = _upload_file(p, "pick")
        if not os.path.exists(up):
            telegram.answer(cb["id"], "No encuentro tu imagen, mándala de nuevo")
            return
        with open(up, "rb") as f:
            raw = f.read()
        telegram.edit_buttons_off(owner, cb["message"]["message_id"],
                                  "🎨 Dentro del diseño" if action == "yd" else "📤 Tal cual")
        telegram.answer(cb["id"], "Generando…")
        try:
            if action == "yd":
                _make_pick_photo(p, user_photo=raw)
            else:
                from . import postimage
                path = _pick_photo_file(p)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(postimage.fit_instagram(raw))
                p["pick_raw"] = True   # tal cual: sin diseño ni sello de canal
            p["pick_photo_credit"] = None
            p["pick_style"] = "photo"
        except Exception:
            traceback.print_exc()
            telegram.send(owner, "⚠️ No pude usar esa imagen. Prueba con otra.")
            return
        if p.get("share_msg"):
            telegram.edit_buttons_off(owner, p["share_msg"], "↪️ Reemplazada por la versión de abajo")
        _share_panel(state, p)
        if p.get("ig_pre_status") in ("queued", "posted"):
            telegram.send(owner, "Ojo: en Instagram ya quedó la versión anterior.")
        return

    elif action in ("xh", "xl"):   # modo día / noche u otro diseño del post partido
        r = p.get("recap") or {}
        if not r or r.get("mode") == "raw":
            telegram.answer(cb["id"], "Esta imagen va tal cual: no tiene diseño")
            return
        if action == "xh":
            r["theme"] = "dark" if r.get("theme") == "light" else "light"
            telegram.answer(cb["id"], "Cambiando a modo " + ("día…" if r["theme"] == "light" else "noche…"))
        else:
            from . import layouts
            r["layout"] = layouts.cycle(r.get("layout"), "recap")
            telegram.answer(cb["id"], "Diseño: " + layouts.LAYOUT_NAMES[r["layout"]])
        if not _recap(state, p, reuse=True):
            telegram.send(owner, "⚠️ No pude cambiar el modo. Intenta de nuevo en un rato.")
        return

    elif action in ("xp", "xd", "xr", "xc"):   # tu propia imagen para el post partido
        if action == "xc":
            telegram.edit_buttons_off(owner, cb["message"]["message_id"], "Cancelado: sigue la imagen anterior")
            telegram.answer(cb["id"])
            return
        if not p.get("recap"):
            telegram.answer(cb["id"], "Este pick no tiene post partido")
            return
        if action == "xp":
            state["await_photo"] = {"pid": pid, "until": _iso(store.now_utc() + timedelta(hours=2))}
            telegram.send(owner, f"🖼 Mándame ahora la imagen para el pick #{pid} (como foto o como archivo).\n"
                                 "Usa solo imágenes tuyas o con permiso de uso: las fotos de agencias o "
                                 "medios pueden traer reclamos de copyright en Instagram.")
            telegram.answer(cb["id"], "Esperando tu imagen")
            return
        if action == "xc":
            telegram.edit_buttons_off(owner, cb["message"]["message_id"], "Cancelado: sigue la imagen anterior")
            telegram.answer(cb["id"])
            return
        if not os.path.exists(_upload_file(p)):
            telegram.answer(cb["id"], "No encuentro tu imagen, mándala de nuevo")
            return
        p["recap"]["photo_src"] = "user" if action == "xd" else p["recap"].get("photo_src")
        p["recap"]["mode"] = "raw" if action == "xr" else None
        telegram.edit_buttons_off(owner, cb["message"]["message_id"],
                                  "🎨 Dentro del diseño" if action == "xd" else "📤 Tal cual")
        telegram.answer(cb["id"], "Generando…")
        if not _recap(state, p, reuse=True):
            telegram.send(owner, "⚠️ No pude volver a armar el post partido. Intenta de nuevo en un rato.")
        elif p.get("ig_res_status") in ("queued", "posted"):
            telegram.send(owner, "Ojo: en Instagram ya quedó la versión anterior.")
        return

    elif action == "xn":   # no compartir sola la imagen post partido del gratis automático
        r = p.get("recap") or {}
        r["auto_off"] = True
        telegram.set_buttons(owner, cb["message"]["message_id"], RECAP_BUTTONS(p))
        telegram.answer(cb["id"], "Listo: la compartes tú cuando quieras")

    elif action in ("xv", "xf", "xi", "xt"):   # compartir la imagen post partido
        if not p.get("recap") or not os.path.exists(_recap_file(p)):
            telegram.answer(cb["id"], "La imagen post partido ya no está disponible")
            return
        if action == "xt":
            telegram.send(owner, f"Escribe /titular {pid} y el titular nuevo. Ejemplo: /titular {pid} MARACA-NAZO\n"
                                 "El guion marca dónde se parte en dos líneas (la segunda va en verde).")
            telegram.answer(cb["id"])
            return
        if action in ("xv", "xf"):
            where = "vip" if action == "xv" else "free"
            if where == "free" and _vip_only(p):
                telegram.answer(cb["id"], "La NBA es exclusiva del VIP")
                return
            if where in p["recap"]["msgs"]:
                telegram.answer(cb["id"], "Ya estaba compartida ahí")
                return
            if where == "vip" and not state.get("vip_chat"):
                telegram.answer(cb["id"], "Primero vincula el canal VIP con /vincular_vip")
                return
            _recap_share(state, p, where)
            telegram.answer(cb["id"], "Compartida")
        else:
            from . import instagram
            if not instagram.enabled(state):
                telegram.answer(cb["id"], "Instagram no está conectado")
                return
            if p.get("ig_res_status") in ("queued", "posted"):
                telegram.answer(cb["id"], "Ya estaba en proceso")
                return
            p["ig_res_status"] = "queued"
            p["ig_res_caption"] = p["recap"]["ig"]
            telegram.answer(cb["id"], "Se publica en Instagram en unos minutos")
        telegram.set_buttons(owner, cb["message"]["message_id"], RECAP_BUTTONS(p))

    elif action == "rp":   # Reel corregido del postpartido (tras borrar el anterior)
        if p.get("ig_res_status") == "queued":
            telegram.answer(cb["id"], "Ya está en cola")
        else:
            p["ig_res_status"] = "queued"
            p.pop("ig_res_job", None)
            p.pop("ig_res_tries", None)
            telegram.edit_buttons_off(owner, cb["message"]["message_id"], "⏳ Se publica en Instagram en unos minutos")
            telegram.answer(cb["id"], "Se publica en unos minutos")

    elif action in ("ip", "ipn"):   # versión nueva del pick en Instagram (tras borrar la antigua)
        if action == "ipn":
            telegram.edit_buttons_off(owner, cb["message"]["message_id"], "Instagram queda como está")
            telegram.answer(cb["id"], "Listo")
        elif p.get("ig_pre_status") == "queued":
            telegram.answer(cb["id"], "Ya está en cola")
        else:
            p["ig_pre_status"] = "queued"
            p.pop("ig_pre_tries", None)
            telegram.edit_buttons_off(owner, cb["message"]["message_id"], "⏳ Se publica en Instagram en unos minutos")
            telegram.answer(cb["id"], "Se publica en unos minutos")

    elif action in ("ig", "ign"):  # publicar (o no) la celebración en Instagram
        if p.get("ig_status") in ("queued", "posted"):
            telegram.answer(cb["id"], "Ya estaba en proceso")
            return
        if action == "ign":
            p["ig_status"] = "skipped"
            telegram.edit_buttons_off(owner, cb["message"]["message_id"], "No se publica en Instagram")
            telegram.answer(cb["id"], "Listo, no se publica")
        else:
            p["ig_status"] = "queued"
            telegram.edit_buttons_off(owner, cb["message"]["message_id"], "⏳ Se publica en Instagram en unos minutos")
            telegram.answer(cb["id"], "Se publica en unos minutos")

    elif action == "c":  # corregir un resultado automático: mostrar las 3 opciones
        if p["status"] != "settled":
            telegram.answer(cb["id"])
            return
        telegram.set_buttons(owner, cb["message"]["message_id"], RESULT_BUTTONS(pid))
        telegram.answer(cb["id"], "Elige el resultado correcto")

    elif action in ("W", "L", "V"):
        mid = cb["message"]["message_id"]
        if p["status"] == "published":
            _settle(state, p, action)
            telegram.edit_buttons_off(owner, mid, formatting.RESULT_LABEL[action])
            telegram.answer(cb["id"], "Resultado guardado")
        elif p["status"] == "settled":
            if p.get("result") != action:
                _correct(state, p, action)
                telegram.answer(cb["id"], "Resultado corregido")
            else:
                telegram.answer(cb["id"], "Sin cambios")
            telegram.set_buttons(owner, mid, [[(formatting.RESULT_LABEL[action], "noop")],
                                              [("✏️ Corregir", f"c:{pid}")]])
        else:
            telegram.answer(cb["id"], "Ya estaba cerrado")


HELP_TEXT = (
    "👁 <b>Comandos de Stakevision</b>\n\n"
    "<b>Día a día</b>\n"
    "/hoy · resumen del día: picks publicados, en juego, resultados y unidades\n"
    "/estado · pendientes, números de cada pick, búsquedas que te quedan y estado del gratis\n"
    "/compartir 8 · vuelve a mandarte la imagen del pick #8 (o su post partido)\n"
    "/titular 8 MARACA-NAZO · cambia el titular del post partido del pick #8\n\n"
    "<b>Buscar picks</b> (comparten 4 usos al día; si /partido no encuentra el partido, no se descuenta)\n"
    "/partido Celtics vs Knicks · un partido específico, en vivo o próximo (fútbol o NBA), con opción A y B\n"
    "/buscar · el top 3 de fútbol de las próximas 30 h · /buscar 40 · mirando 40 h (máx. 47)\n"
    "/envivo · lo que tenga valor en los partidos de fútbol que se juegan ahora\n"
    "/builder Thunder vs Nuggets · Bet Builder de 3 líneas que los jugadores cumplen casi siempre (sin límite)\n\n"
    "<b>Pick gratis</b>\n"
    "/gratis · estado del gratis automático · /gratis 37 · ese pick es el gratis y sale ya\n"
    "/gratis prueba · qué elegiría (solo tú) · /gratis apagar · /gratis encender\n\n"
    "<b>Redes</b>\n"
    "/postpartido Vasco vs Boca · imagen post partido de cualquier partido terminado\n"
    "/adelanto 8 10:00 · historia de adelanto del pick #8 (no aplica a NBA)\n\n"
    "<b>Contactos y VIP</b>\n"
    "/enlace Juan · enlace personal al bot con acceso VIP (vence en 7 días; /enlace Juan 30 para 30 días)\n"
    "/anular Juan · anula su acceso VIP si aún no lo usa\n"
    "/mensaje Juan hola · le escribe a un contacto · /contactos · la lista\n\n"
    "El escaneo sale a las 00:05 (solo partidos de ese día) y el gratis automático ~30 min después. La NBA y los Bet Builder te llegan "
    "solos antes de cada partido."
)


def _request_search(state: dict, text: str, live: bool = False) -> None:
    from zoneinfo import ZoneInfo
    owner = state["owner_chat"]
    parts = text.split()
    hours = config.WINDOW_END_H
    is_nba = any(x.lower() in ("nba", "basket", "basquet", "básquet", "baloncesto") for x in parts[1:])
    match_q = None
    if parts[0].lower().startswith("/partido"):
        words = [w for w in parts[1:] if w.lower() not in ("nba", "futbol", "fútbol", "basket", "basquet", "básquet",
                                                           "baloncesto")]
        match_q = " ".join(words).strip()
        if not match_q:
            telegram.send(owner, "Usa: /partido Celtics vs Knicks · /partido Colo-Colo · /partido nba Lakers\n"
                                 "Busca ese partido en juego o en las próximas 47 horas y te da la opción A y B.")
            return
    if match_q is not None:
        pass
    elif is_nba:
        live = live or any(x.lower() in ("vivo", "envivo", "live") for x in parts[1:])
    elif len(parts) > 1 and parts[1].lower() in ("vivo", "envivo", "live"):
        live = True
    elif len(parts) > 1 and not live:
        try:
            hours = max(2, min(47, int(parts[1])))
        except ValueError:
            telegram.send(owner, "Usa /buscar o /buscar 40 (horas hacia adelante, máximo 47).")
            return
    today = store.now_utc().astimezone(ZoneInfo(config.TIMEZONE)).date().isoformat()
    m = state.get("manual") or {}
    if m.get("date") != today:
        m = {"date": today, "n": 0}
    if m["n"] >= config.MANUAL_SEARCHES_PER_DAY:
        telegram.send(owner, f"⚠️ Ya hiciste {m['n']} búsquedas hoy (máximo {config.MANUAL_SEARCHES_PER_DAY}, "
                             f"para no agotar el plan gratis de OddsPapi). Mañana se reinicia.")
        return
    m["n"] += 1
    state["manual"] = m
    if match_q is not None:
        sport = "basketball" if is_nba else ("soccer" if any(x.lower() in ("futbol", "fútbol") for x in parts[1:]) else None)
        state["scan_request"] = {"match": match_q, "sport": sport}
        telegram.send(owner, f"🔎 Buscando «{formatting.escape(match_q)}»… te llega en un par de minutos. "
                             f"(Búsqueda {m['n']} de {config.MANUAL_SEARCHES_PER_DAY} hoy)")
        return
    if is_nba:
        state["scan_request"] = "nba-live" if live else "nba"
        telegram.send(owner, "🏀 Buscando en la NBA" + (" (partidos en juego)" if live else "")
                      + f"… te llega en un par de minutos. (Búsqueda {m['n']} de {config.MANUAL_SEARCHES_PER_DAY} hoy)")
        return
    if live:
        state["scan_request"] = "live"
        telegram.send(owner, f"🔴 Buscando valor en los partidos que se están jugando… te llega en un par de "
                             f"minutos. (Búsqueda {m['n']} de {config.MANUAL_SEARCHES_PER_DAY} hoy)")
        return
    state["scan_request"] = hours
    telegram.send(owner, f"🔎 Buscando los mejores picks de las próximas {hours} horas… "
                         f"te llegan en un par de minutos. (Búsqueda {m['n']} de {config.MANUAL_SEARCHES_PER_DAY} hoy)")


def _pick_line(p: dict) -> str:
    l = p["legs"][0]
    sp = "🏀" if (l.get("sport") or "soccer") == "basketball" else "⚽"
    what = "🧩 Bet Builder" if p.get("kind") == "builder" else formatting.escape(formatting.outcome_label(l))
    if p.get("kind") == "doble":
        what = "Doble: " + " + ".join(formatting.escape(formatting.outcome_label(x)) for x in p["legs"])
    price = f" @ {formatting.odds(p['price'])}" if p.get("price") and p.get("status") != "bb" else ""
    return (f"#{p['id']} {sp} {formatting.escape(l['home'])} vs {formatting.escape(l['away'])} · {what}{price}"
            f" · {formatting.local_time(l['kickoff'])}")


def _status_text(state: dict) -> str:
    """/estado: lo que espera una decisión tuya, con el número de cada pick."""
    from zoneinfo import ZoneInfo
    now = store.now_utc()
    ps = sorted(state["picks"].values(), key=lambda x: x["kickoff"])
    cand = [p for p in ps if p["status"] == "candidate" and _expires(p) > now]
    sel = [p for p in ps if p["status"] == "selected"]
    bb = [p for p in ps if p["status"] == "bb" and _expires(p) > now]
    pub = [p for p in ps if p["status"] == "published"]
    m = state.get("manual") or {}
    used = m.get("n", 0) if m.get("date") == _local_today() else 0
    af = state.get("auto_free") or {}
    free = ("apagado ⏸️" if state.get("auto_free_off") else
            {"pending": f"pendiente (pick #{af.get('pid')})", "published": f"publicado (pick #{af.get('pid')})",
             "cancelled": "cancelado hoy", "none": "hoy no hubo opción"}.get(af.get("status"), "aún no se elige")
            if af.get("date") == _local_today() else ("apagado ⏸️" if state.get("auto_free_off") else "aún no se elige"))
    out = ["📊 <b>Estado</b>", f"🔎 Búsquedas hoy: {used} de {config.MANUAL_SEARCHES_PER_DAY} "
                              f"(te quedan {max(0, config.MANUAL_SEARCHES_PER_DAY - used)})",
           f"🎁 Gratis automático: {free}"]
    for title, rows in (("🆕 Candidatos por elegir", cand), ("🖼 Elegidos sin publicar", sel),
                        ("🧩 Bet Builder sin cuota cargada", bb), ("⏳ Publicados en juego", pub)):
        out += ["", f"<b>{title}</b> ({len(rows)})"] + ([_pick_line(p) for p in rows[:10]] or ["—"])
    w = sum(1 for p in ps if p.get("result") == "W")
    l_ = sum(1 for p in ps if p.get("result") == "L")
    out += ["", f"📈 Historial: {w} verdes, {l_} rojas · /hoy para el resumen del día"]
    try:
        out.append("OddsPapi: " + oddspapi.quota_text())
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(out)


def _today_text(state: dict) -> str:
    """/hoy: los picks de hoy (hora Chile) con su estado y el balance en unidades."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(config.TIMEZONE)
    today = _local_today()
    rows = [p for p in state["picks"].values()
            if p.get("published_at") and p.get("channel_msgs")
            and (store.parse_ts(p["kickoff"]).astimezone(tz).date().isoformat() == today
                 or store.parse_ts(p["published_at"]).astimezone(tz).date().isoformat() == today)]
    rows.sort(key=lambda p: p["kickoff"])
    now = store.now_utc()
    out = [f"📅 <b>Hoy · {store.now_utc().astimezone(tz):%d/%m}</b>", ""]
    units = 0.0
    if not rows:
        out.append("Todavía no se publica ningún pick hoy.")
    for p in rows:
        where = " + ".join({"vip": "VIP", "free": "Gratis"}[k] for k in p["channel_msgs"])
        if p.get("result"):
            mark = {"W": "✅ verde", "L": "❌ roja", "V": "↩️ nula"}[p["result"]]
            units += (p["stake"] * (p["price"] - 1) if p["result"] == "W" else -p["stake"] if p["result"] == "L" else 0)
        elif store.parse_ts(p["kickoff"]) <= now:
            mark = "🔴 en juego"
        else:
            mark = "🕒 por jugarse"
        out.append(f"{_pick_line(p)}\n   {mark} · {where} · stake {p['stake']}/10")
    done = [p for p in rows if p.get("result") in ("W", "L")]
    if done:
        out += ["", f"💰 Balance del día: {'+' if units >= 0 else ''}{units:.2f} unidades "
                    f"({sum(p['result'] == 'W' for p in done)} verdes, {sum(p['result'] == 'L' for p in done)} rojas)"]
    return "\n".join(out)


def _moved_hint(text: str) -> str:
    """Comandos retirados: a cuál usar ahora."""
    t = text.lower()
    if t.startswith("/invitar"):
        return "Ese comando se reemplazó por /enlace Juan (acceso VIP personal; /enlace Juan 30 para 30 días)."
    if t.startswith("/entretiempo"):
        return "Ese comando se retiró: el entretiempo de tus picks sale solo en sus canales."
    if t.startswith("/combinada"):
        return "Usa /builder (por ejemplo /builder Thunder vs Nuggets)."
    if t.startswith("/vivo"):
        return "Usa /envivo."
    return ("La NBA ya te llega sola (escaneo de las 00:05 y Bet Builder antes de cada partido). "
            "Para un partido puntual usa /partido Lakers.")

def _migrate_stakes(state: dict, now) -> None:
    """Escala de stake v2: recalcula picks que aún no empiezan y corrige sus mensajes."""
    from .value import stake_for
    for p in state["picks"].values():
        if p.get("stake_v") == 2:
            continue
        if p["status"] in ("candidate", "published") and store.parse_ts(p["kickoff"]) > now:
            p["stake"] = stake_for(p.get("tier", "valor"), p["kind"], p["price"], p["edge"])
            if p["status"] == "published":
                for where, mid in (p.get("channel_msgs") or {}).items():
                    chat = state["vip_chat"] if where == "vip" else config.FREE_CHANNEL
                    try:
                        telegram.edit_text(chat, mid, formatting.channel_post(p, where))
                    except telegram.TelegramError as e:
                        print(f"No se pudo editar el pick {p['id']} en {where}: {e}")
        p["stake_v"] = 2


def _process_updates(state: dict, wait: int = 0) -> int:
    ups = telegram.updates(state["tg_offset"], wait=wait)
    kinds = [k for u in ups for k in ("message", "channel_post", "callback_query") if k in u]
    if ups or not wait:
        print(f"Actualizaciones recibidas: {len(ups)} ({', '.join(sorted(set(kinds))) or 'ninguna'}); "
              f"dueño vinculado: {'sí' if state.get('owner_chat') else 'no'}; "
              f"VIP vinculado: {'sí' if state.get('vip_chat') else 'no'}")
    for u in ups:
        state["tg_offset"] = u["update_id"] + 1
        try:
            _handle_update(state, u)
        except Exception:
            traceback.print_exc()
        store.save(state)
    return len(ups)


def _checkpoint(msg: str = "Actualizar estado") -> None:
    """Guarda el estado en el repo a mitad de la escucha (solo en GitHub Actions)."""
    import subprocess
    if not os.environ.get("GIT_CHECKPOINT"):
        return
    try:
        subprocess.run("git add data docs/historial.json docs/ig", shell=True, check=False)
        if subprocess.run("git diff --cached --quiet", shell=True).returncode != 0:
            subprocess.run(f'git commit -q -m "{msg}" && git pull -q --rebase && git push -q', shell=True, check=False)
    except Exception:  # noqa: BLE001
        traceback.print_exc()


def _run_scan_request(state: dict) -> dict:
    request = state.pop("scan_request", None)
    if not request:
        return state
    store.save(state)
    if isinstance(request, dict) and request.get("match"):
        scan_match(request["match"], request.get("sport"))
    elif request in ("nba", "nba-live"):
        scan_nba(top=config.MANUAL_TOP, manual=True, live=request == "nba-live")
    elif request == "live":
        scan(top=config.MANUAL_TOP, manual=True, live=True)
    else:
        scan(hours=request, top=config.MANUAL_TOP, manual=True)
    return store.load()


def listen(seconds: int = 270) -> None:
    """Revisión completa y luego queda escuchando: los botones responden al instante (1-2 s)."""
    import time
    end = time.time() + seconds
    poll()
    _checkpoint()
    last_ig = time.time()
    while time.time() < end - 25:
        state = store.load()
        try:
            n = _process_updates(state, wait=20)
        except Exception:
            traceback.print_exc()
            time.sleep(5)
            continue
        state = _run_scan_request(state)
        if n:
            store.save(state)
            _checkpoint()
        if time.time() - last_ig > 60:   # Instagram necesita que la imagen ya esté en la web
            last_ig = time.time()
            try:
                from . import instagram
                if instagram.enabled(state) and any(
                        p.get(f) == "queued" for p in state["picks"].values()
                        for f in ("ig_status", "ig_pre_status", "ig_res_status", "ig_story_status")):
                    _instagram_queue(state, store.now_utc())
                    store.save(state)
                    _checkpoint()
            except Exception:
                traceback.print_exc()


def poll() -> None:
    state = store.load()
    _process_updates(state)

    now = store.now_utc()
    owner = state.get("owner_chat")
    if owner and state.get("cmds_v") != 12:
        try:  # menú de comandos en Telegram (solo visible en tu chat con el bot)
            telegram._call("setMyCommands", scope={"type": "chat", "chat_id": owner}, commands=[
                {"command": "hoy", "description": "Resumen del día: picks, resultados y unidades"},
                {"command": "estado", "description": "Pendientes, números de pick y búsquedas que quedan"},
                {"command": "partido", "description": "Analizar un partido (ej. /partido Celtics vs Knicks)"},
                {"command": "buscar", "description": "Top 3 de fútbol de las próximas 30 h"},
                {"command": "envivo", "description": "Valor en partidos de fútbol en juego"},
                {"command": "builder", "description": "Bet Builder de un partido (ej. /builder Thunder)"},
                {"command": "gratis", "description": "Pick gratis automático: estado, prueba, apagar"},
                {"command": "compartir", "description": "Imagen de un pick o su post partido (ej. /compartir 8)"},
                {"command": "titular", "description": "Cambiar el titular del post partido"},
                {"command": "postpartido", "description": "Post partido de cualquier partido (ej. Vasco vs Boca)"},
                {"command": "adelanto", "description": "Historia de adelanto (ej. /adelanto 8 10:00)"},
                {"command": "enlace", "description": "Acceso VIP personal para un contacto (ej. /enlace Juan)"},
                {"command": "anular", "description": "Anular el acceso VIP de un contacto"},
                {"command": "mensaje", "description": "Escribirle a un contacto (ej. /mensaje Juan hola)"},
                {"command": "contactos", "description": "Quiénes iniciaron el bot"},
                {"command": "ayuda", "description": "Lista de comandos"}])
            state["cmds_v"] = 12
        except Exception as e:
            print(f"No se pudo registrar el menú de comandos: {e}")
    _migrate_stakes(state, now)
    _refresh_recap_texts(state)
    _nba_daily(state)
    def _news(st, _now):
        from . import newswatch
        newswatch.ready(st)
        newswatch.check(st)
    for fn in (_nba_owner_flow, lambda st, _now: _live_builders(st), _news):
        try:
            fn(state, now)
        except Exception:
            traceback.print_exc()
    try:
        _cancel_file(state)
        _repair_file(state)
        _refresh_file(state)
        _recap_fix_file(state)
        _manual_free_file(state)
        _force_free_file(state)
        _auto_free_tick(state, now)
    except Exception:
        traceback.print_exc()
    for p in state["picks"].values():   # picks aprobados con el flujo antiguo: ofrecer la imagen para compartir
        if (owner and p["status"] == "published" and not p.get("share_msg") and not p.get("share_offered")
                and store.parse_ts(p["kickoff"]) > now):
            p["share_offered"] = True
            try:
                _share_panel(state, p)
            except Exception:
                traceback.print_exc()
    for p in state["picks"].values():
        if p["status"] in ("candidate", "selected", "bb") and _expires(p) <= now:
            was = p["status"]
            p["status"] = "expired"
            if owner and p.get("owner_msg") and was in ("candidate", "bb"):
                telegram.edit_buttons_off(owner, p["owner_msg"], "⌛ Sin aprobar a tiempo")
            if owner and p.get("share_msg"):
                telegram.edit_buttons_off(owner, p["share_msg"], "⌛ Ya no está vigente")
        _remind(state, p, now)
        try:
            _lineup_check(state, p, now)
        except Exception:
            traceback.print_exc()
        _recap_retry(state, p, now)
        try:
            _auto_recap_tick(state, p, now)
        except Exception:
            traceback.print_exc()
        try:
            _halftime_check(state, p, now)
        except Exception:
            traceback.print_exc()
        if (p["status"] == "settled" and p.get("result") == "W" and p.get("settled_at")
                and now - store.parse_ts(p["settled_at"]) < timedelta(hours=48)):
            from . import instagram
            if p.get("ig_kit_sent") and p.get("ig_kit_mode") != "api" and instagram.enabled(state) and not p.get("ig_status"):
                p["ig_kit_sent"] = False   # Instagram recién conectado: ofrecer publicar los verdes recientes
            if not p.get("ig_kit_sent"):
                _instagram_kit(state, p)
        last_kick = max(store.parse_ts(l["kickoff"]) for l in p["legs"])
        if (p["status"] == "published" and not p.get("result_asked") and owner
                and now >= last_kick + timedelta(minutes=config.RESULT_CHECK_AFTER_MIN)
                and not (p.get("next_check") and now < store.parse_ts(p["next_check"]))):
            _auto_result(state, p, owner, now, last_kick)
    try:
        from . import history
        history.update(max_fetch=1)   # arma el historial de resultados de a poco (1 consulta por revisión)
    except Exception:
        traceback.print_exc()
    try:
        from . import instagram
        if instagram.enabled(state):
            ig = state.setdefault("ig", {})
            fp = instagram._fp(config.INSTAGRAM_TOKEN)
            if ig.get("checked") != fp and state.get("owner_chat"):
                try:
                    me = instagram._call("GET", "me", state, fields="username")
                    telegram.send(state["owner_chat"], f"📸 Instagram conectado: @{formatting.escape(me.get('username', '?'))}. "
                                  "Los verdes te llegarán con el botón para publicarlos.")
                except instagram.InstagramError as e:
                    telegram.send(state["owner_chat"], f"⚠️ El token de Instagram no funcionó: {formatting.escape(str(e))}")
                ig["checked"] = fp
            instagram.refresh_token(state)
            _instagram_queue(state, now)
            from . import newswatch
            newswatch.publish_jobs(state)
            from . import ig_inbox
            ig_inbox.run(state)   # responde comentarios y mensajes directos
    except Exception:
        traceback.print_exc()
    store.save(state)
    state = _run_scan_request(state)
    from zoneinfo import ZoneInfo
    local = store.now_utc().astimezone(ZoneInfo(config.TIMEZONE))
    if (config.AUTO_SCAN_FALLBACK and state.get("owner_chat") and state.get("auto_scan_date") != _local_today()
            and (local.hour, local.minute) >= config.DAILY_SCAN_AT):
        scan()   # escaneo diario: sale apenas pasa la hora configurada (00:05)


def setup() -> None:
    import os
    if not os.path.exists(config.MARKETS_CACHE):
        m = oddspapi.markets(force=True)
        print(f"Mercados de fútbol guardados: {len(m)}")
    t = oddspapi.tournaments()
    print(f"Torneos de fútbol guardados: {len(t)}")
    print("Uso OddsPapi:", oddspapi.quota_text())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "poll"
    {"scan": scan, "poll": poll, "listen": listen, "setup": setup}[cmd]()
