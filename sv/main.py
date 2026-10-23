"""Punto de entrada.

    python -m sv.main scan    # busca valor y te manda candidatos (1 vez al día)
    python -m sv.main poll    # procesa tus botones, publica y pide resultados (cada ~10 min)
    python -m sv.main setup   # descarga la lista de mercados (1 vez)
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import timedelta

from . import apifootball, config, formatting, oddspapi, store, telegram
from .value import build_picks, selections_for_fixture

CANDIDATE_BUTTONS = lambda pid: [  # noqa: E731
    [("🖼 Elegir y generar imagen", f"s:{pid}")],
    [("❌ Descartar", f"r:{pid}")],
]


def SHARE_BUTTONS(p: dict) -> list:
    """Destinos para un pick elegido. Cada uno se puede usar; lo ya hecho queda marcado."""
    pid, msgs = p["id"], p.get("channel_msgs") or {}
    rows = []
    vip_done, free_done = "vip" in msgs, "free" in msgs
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
    photo = p.get("pick_style") == "photo"
    rows.append([("🧾 Volver al cupón" if photo else "📰 Versión con foto", f"st:{pid}"),
                 ("🖼 Adjuntar mi imagen", f"yp:{pid}")])
    if photo:
        rows.append([("🌙 Modo noche" if p.get("theme") == "light" else "☀️ Modo día", f"th:{pid}"),
                     ("🔀 Otro diseño", f"dl:{pid}")])
        rows.append([("📲 Adelanto (historia)", f"ad:{pid}")])
    else:
        rows.append([("📲 Adelanto (historia)", f"ad:{pid}")])
    if not msgs and not st:
        rows.append([("❌ Descartar", f"r:{pid}")])
    return rows


def _share_panel(state: dict, p: dict) -> None:
    """Te manda la imagen del pick con los botones de destino (VIP, VIP + Gratis, Instagram)."""
    owner = state.get("owner_chat")
    if not owner:
        return
    image = _pick_image(p)
    head = (f"🖼 <b>Pick #{p['id']} listo para compartir</b>\n"
            "Elige dónde publicarlo (puedes usar varios botones). Este es el texto que sale con la imagen:")
    text = formatting.channel_post(p)
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
        if not manual and not live and config.NBA_ENABLED:
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


# ---------------------------------------------------------------- pick gratis automático
AUTO_KEYS = ("legs", "price", "prob", "edge", "stake", "tier", "kind", "analysis")


def AUTO_FREE_BUTTONS(pid: str) -> list:
    return [[("🚀 Publicar ya", f"fa:{pid}"), ("🔁 Elegir otro", f"fo:{pid}")],
            [("✋ No publicar hoy", f"fc:{pid}")]]


def _auto_pool(state: dict, publish_at) -> list:
    """Opciones del escaneo de hoy que sirven para el gratis, de la más probable a la menos."""
    lead = publish_at + timedelta(minutes=config.AUTO_FREE_MIN_LEAD_MIN)
    today = _local_today()
    from zoneinfo import ZoneInfo
    pool = []
    for p in state["picks"].values():
        if p["status"] != "candidate" or p.get("live") or p.get("kind") != "simple":
            continue
        made = store.parse_ts(p["created_at"]).astimezone(ZoneInfo(config.TIMEZONE)).date().isoformat()
        if made != today or store.parse_ts(p["kickoff"]) < lead:
            continue
        for opt, d in (("A", p), ("B", p.get("alt"))):
            if not d or len(d.get("legs") or []) != 1:
                continue
            if not (config.ODDS_MIN <= d["price"] <= config.ODDS_MAX) or d["edge"] < config.AUTO_FREE_MIN_EDGE:
                continue
            pool.append((d["prob"], d["edge"], p["id"], opt))
    pool.sort(key=lambda x: (round(x[0], 3), x[1]), reverse=True)   # más probable; a igualdad, más valor
    return [[pid, opt] for _pr, _ed, pid, opt in pool]


def _free_given_today(state: dict) -> bool:
    from zoneinfo import ZoneInfo
    today = _local_today()
    for p in state["picks"].values():
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
        telegram.send(owner, "🤖 Pick gratis automático: hoy ninguna opción cumple (cuota 1.65–2.00, cerca de la "
                             "cuota justa y con tiempo antes del partido). Si quieres, elige uno a mano con 🎁.")
        return False
    pid, opt = pool[0]
    p = state["picks"][pid]
    _use_option(p, opt)
    p["status"] = "selected"
    p["auto_free"] = True
    try:
        from . import layouts
        p["pick_layout"] = p.get("pick_layout") or layouts.next_layout(state, "pick")
        _make_pick_photo(p)
        p["pick_style"] = "photo"
    except Exception:
        traceback.print_exc()
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
           f"Es la opción más probable de las {len(pool)} que cumplen hoy. "
           f"Se publica sola a las <b>{hhmm}</b> en {where}.\n"
           "Revisa la cuota en tu app. Puedes publicarlo ya, cambiarlo por la siguiente opción"
           + (f" (quedan {others})" if others else "") + " o no publicar gratis hoy.")
    image = _pick_image(p)
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
        image = _pick_image(p)
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
        telegram.send(owner, "▶️ Pick gratis automático encendido: sale cada día tras el escaneo de las 09:07.")
        return
    if arg in ("ahora", "elegir", "ya"):
        af = state.get("auto_free") or {}
        if af.get("date") == _local_today() and af.get("status") == "pending":
            telegram.send(owner, "Ya hay un pick gratis automático pendiente para hoy (mira el mensaje de arriba).")
            return
        if state.get("auto_free_off"):
            telegram.send(owner, "Está apagado. Usa /gratis encender primero.")
            return
        if _free_given_today(state):
            telegram.send(owner, "Hoy ya salió un pick en el canal Gratis.")
            return
        state["auto_free"] = {}
        _auto_free_choose(state)
        return
    af = state.get("auto_free") or {}
    on = "apagado ⏸️" if state.get("auto_free_off") else "encendido ▶️"
    st = {"pending": "pendiente de publicar", "published": "publicado", "cancelled": "cancelado",
          "none": "sin opción que cumpla"}.get(af.get("status"), "aún no se elige")
    telegram.send(owner, f"🤖 Pick gratis automático: {on}\nHoy: {st}"
                  + (f" (pick #{af['pid']})" if af.get("pid") and af.get("date") == _local_today() else "")
                  + "\n\n/gratis ahora · elegirlo ya con los candidatos de hoy\n/gratis apagar · /gratis encender")


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
    picks = build_picks(selections, max_n=top, min_n=top)

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
        for leg in d["legs"]:
            leg["label"] = formatting.outcome_label(leg)
            leg["context"] = apifootball.context(leg["home"], leg["away"], leg["kickoff"])
        state["seq"] += 1
        pid = str(state["seq"])
        d.update(id=pid, status="candidate", created_at=_iso(now), stake_v=2)
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
    from . import nba
    l = d["legs"][0]
    sign = "+" if d["edge"] >= 0 else ""
    return (f"<b>Opción {role}</b> · 🎯 <b>{formatting.escape(l['label'])}</b> @ {formatting.odds(d['price'])} "
            f"· valor {sign}{formatting.pct(d['edge'])} · stake {d['stake']}/10\n"
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
        telegram.send(owner, f"🔎 No encontré «{formatting.escape(query)}» con cuotas, ni en juego ni en las próximas 47 horas.")
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
    from . import commons, espn, postimage, teaser
    l = p["legs"][0]
    teams = espn.preview(l["home"], l["away"], l["kickoff"])
    side = {"1": "home", "2": "away"}.get(str(l.get("outcome")), "home")
    names = [l[side], l["away" if side == "home" else "home"]]
    if teams:
        names = [teams[side]["name"], teams["away" if side == "home" else "home"]["name"]] + names
    cache = _upload_file(p, "pickphoto")
    photo = (user_photo, None) if user_photo else None
    if not photo and reuse and os.path.exists(cache):
        with open(cache, "rb") as f:
            photo = (f.read(), p.get("pick_photo_credit"))
    for n in ([] if photo or reuse else dict.fromkeys(names)):
        photo = commons.photo(n, team=True)
        if photo:
            break
    if photo:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "wb") as f:
            f.write(photo[0])
    from . import layouts
    image = layouts.render_pick(teaser.pick_photo_data(p, teams, photo), p.get("pick_layout") or "revista",
                                p.get("theme") or "dark")
    path = _pick_photo_file(p)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(image)
    p["pick_photo_credit"] = photo[1] if photo else None
    return True


def _pick_image(p: dict) -> bytes | None:
    if p.get("pick_style") == "photo" and os.path.exists(_pick_photo_file(p)):
        with open(_pick_photo_file(p), "rb") as f:
            return f.read()
    try:
        from . import postimage
        return postimage.render(p)
    except Exception:
        traceback.print_exc()
        return None


def _publish(state: dict, p: dict, free: bool, vip_too: bool = True) -> None:
    """Publica en VIP (si vip_too) y en Gratis (si free). Si ya estaba en un canal, no lo repite."""
    text = formatting.channel_post(p)
    image = _pick_image(p)
    msgs = p.setdefault("channel_msgs", {})
    vip = state.get("vip_chat")
    if vip_too and vip and "vip" not in msgs:
        msgs["vip"] = _post(vip, text, image)
    if free and "free" not in msgs:
        msgs["free"] = _post(config.FREE_CHANNEL, text, image)
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


def _settle(state: dict, p: dict, result: str) -> None:
    p.update(result=result, status="settled", settled_at=_iso(store.now_utc()))
    _post_result(state, p, formatting.result_post(p))
    _after_result(state, p)


def _remind(state: dict, p: dict, now) -> None:
    """Aviso en los canales cuando faltan ~30 minutos para el partido."""
    if p["status"] != "published" or p.get("reminded"):
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
    """Verdes seguidos terminando en este pick (las nulas no cortan la racha)."""
    done = sorted((x for x in state["picks"].values() if x.get("status") == "settled"),
                  key=lambda x: (x.get("settled_at") or "", x["kickoff"]))
    n = 0
    for x in reversed(done[:done.index(p) + 1] if p in done else done):
        if x.get("result") == "V":
            continue
        if x.get("result") != "W":
            break
        n += 1
    return max(n, 1)


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
            jobs.append((p, "ig_pre_status", f"pre-{p['id']}", p.get("ig_pre_caption") or ""))
        if p.get("ig_res_status") == "queued":
            jobs.append((p, "ig_res_status", f"res-{p['id']}", p.get("ig_res_caption") or ""))
        if p.get("ig_story_status") == "queued":
            jobs.append((p, "ig_story_status", f"story-{p['id']}", None))
    for p, field, key, caption in jobs:
        if not instagram.image_live(key):
            continue   # la web aún no la publica; se reintenta en la próxima revisión
        try:
            if field == "ig_story_status":
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
    _post_result(state, p, formatting.result_correction(p))
    _after_result(state, p)


# ---------------------------------------------------------------- post partido (formato revista)
def RECAP_BUTTONS(p: dict) -> list:
    pid, msgs = p["id"], (p.get("recap") or {}).get("msgs") or {}
    st = p.get("ig_res_status")
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
    return len(p["legs"]) == 1 and (p["legs"][0].get("sport") or "soccer") == "soccer"


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
    with open(_recap_file(p), "rb") as f:
        msg = telegram.send_photo(owner, f.read(), caption=cap)
    r["panel"] = msg["message_id"]
    telegram.set_buttons(owner, r["panel"], RECAP_BUTTONS(p))


def _upload_file(p: dict, kind: str = "recap") -> str:
    name = f"{p['id']}.jpg" if kind == "recap" else f"{p['id']}-{kind}.jpg"
    return os.path.join(config.ROOT, "data", "uploads", name)


def _recap(state: dict, p: dict, reuse: bool = False) -> bool:
    """Arma la imagen post partido con datos de ESPN y te la manda. False si ESPN aún no tiene el final.
    reuse=True vuelve a dibujarla con los datos ya guardados (titular nuevo o tu foto)."""
    if not state.get("owner_chat") or not _recap_supported(p):
        return False
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
        photo = commons.photo(who["full"]) if who else None
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
    p.pop("recap_pending", None)
    p["ig_kit_sent"] = True   # el post partido reemplaza a la imagen de celebración
    _recap_panel(state, p)
    return True


def _after_result(state: dict, p: dict) -> None:
    """Con el resultado listo: imagen post partido (fútbol, pick simple) o la celebración de siempre."""
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


def _halftime_check(state: dict, p: dict, now) -> None:
    """Entretiempo: publica en los canales del pick el marcador al descanso, goles, estadísticas y cómo va."""
    if (p["status"] != "published" or p.get("ht_done") or len(p["legs"]) != 1
            or (p["legs"][0].get("sport") or "soccer") != "soccer" or not p.get("channel_msgs")):
        return
    kick = store.parse_ts(p["kickoff"])
    if now < kick + timedelta(minutes=44):
        return
    if now > kick + timedelta(minutes=85):
        p["ht_done"] = "missed"
        return
    from . import commons, espn, halftime, layouts
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
    photo = None
    cache = _upload_file(p, "pickphoto")
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            photo = (f.read(), p.get("pick_photo_credit"))
    if not photo:
        scorers = [g["full"] for g in reversed(rep["goals"]) if g["kind"] != "own" and g["full"]]
        for name, team in [(n, False) for n in scorers[:2]] + [(rep["home"]["name"], True), (rep["away"]["name"], True)]:
            photo = commons.photo(name, team=team)
            if photo:
                break
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


def _halftime_preview(state: dict, text: str) -> None:
    """/entretiempo Local vs Visita — vista previa SOLO para ti, con el marcador actual (no publica en canales)."""
    import re as _re
    from . import commons, espn, halftime, layouts
    owner = state["owner_chat"]
    body = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
    teams = _re.split(r"\s+(?:vs\.?|v|-|contra)\s+", body.strip(), maxsplit=1, flags=_re.I)
    if len(teams) != 2:
        telegram.send(owner, "Usa: /entretiempo Vasco vs Boca (un partido en juego o de los últimos 3 días). "
                             "Es solo una vista previa para ti.")
        return
    found = espn.find_recent(teams[0].strip(), teams[1].strip(), finished_only=False)
    if not found:
        telegram.send(owner, "No encontré ese partido en ESPN (en juego o de los últimos 3 días).")
        return
    rep, _ko = found
    l = {"home": rep["home"]["name"], "away": rep["away"]["name"], "mtype": "totals", "outcome": "Más de",
         "handicap": 2.5}
    st = halftime.status(l, rep["home"]["score"], rep["away"]["score"], grade_leg)
    scorers = [g["full"] for g in reversed(rep["goals"]) if g["kind"] != "own" and g["full"]]
    photo = None
    for name, team in [(n, False) for n in scorers[:2]] + [(rep["home"]["name"], True), (rep["away"]["name"], True)]:
        photo = commons.photo(name, team=team)
        if photo:
            break
    data = {"report": rep, "eyebrow": "Vista previa", "photo": photo[0] if photo else None,
            "credit": photo[1]["text"] if photo and photo[1] else None, "stats": halftime.stats(rep),
            "pick_label": "Más de 2.5 goles (ejemplo)", "odds": "1.85", "status": st}
    image = layouts.halftime(data, "dark")
    p = {"price": 1.85, "legs": [dict(l, label="Más de 2.5 goles (pick de ejemplo)")]}
    cap = "🧪 <b>Vista previa (solo tú la ves)</b>\n\n" + halftime.caption(p, rep, st)
    if formatting.caption_fits(cap):
        telegram.send_photo(owner, image, caption=cap)
    else:
        telegram.send_photo(owner, image)
        telegram.send(owner, cap)


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


def _invite_command(state: dict, text: str) -> None:
    """/invitar Nombre [días] — enlace de un solo uso al canal VIP (para invitar sin cobrar)."""
    import re as _re
    owner = state["owner_chat"]
    if not state.get("vip_chat"):
        telegram.send(owner, "Primero vincula el canal VIP con /vincular_vip.")
        return
    body = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
    days = 7
    m = _re.search(r"\s(\d{1,3})\s*(d|días|dias)?$", " " + body)
    if m:
        days = max(1, min(365, int(m.group(1))))
        body = body[:m.start()].strip() if m.start() > 0 else ""
    name = (body or "Invitado")[:32]
    expire = int((store.now_utc() + timedelta(days=days)).timestamp())
    try:
        link = telegram._call("createChatInviteLink", chat_id=state["vip_chat"], name=name,
                              member_limit=1, expire_date=expire)
    except telegram.TelegramError as e:
        telegram.send(owner, "⚠️ No pude crear el enlace. Revisa que el bot sea administrador del canal VIP con el "
                             "permiso «Invitar usuarios mediante enlace».\n" + formatting.escape(str(e)))
        return
    state.setdefault("invites", []).append({"name": name, "link": link["invite_link"], "created": _iso(store.now_utc()),
                                            "days": days})
    telegram.send(owner, f"🎟 Enlace VIP para <b>{formatting.escape(name)}</b> (1 sola persona, vence en {days} días):\n"
                         f"{link['invite_link']}\n\nCópialo y envíaselo. Para anularlo: /anular {formatting.escape(name)}")


def _revoke_command(state: dict, text: str) -> None:
    owner = state["owner_chat"]
    name = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
    inv = [i for i in state.get("invites") or [] if i["name"].lower() == name.lower() and not i.get("revoked")]
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
                and store.parse_ts(x["kickoff"]) > now]
        live.sort(key=lambda x: (bool(x.get("free")), x.get("created_at") or ""), reverse=True)
        p = live[0] if live else None
    if not p or p["status"] not in ("selected", "published") or store.parse_ts(p["kickoff"]) <= now:
        telegram.send(owner, "Usa /adelanto, el número del pick y (si quieres) la hora en que lo revelas. "
                             "Ejemplo: /adelanto 8 10:00\nEl pick tiene que estar elegido y su partido aún no empieza.")
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
        elif chat == owner and text.lower().startswith("/gratis"):
            _free_command(state, text)
        elif chat == owner and text.lower().startswith("/partido"):
            _request_search(state, text)
        elif chat == owner and text.lower().startswith("/entretiempo"):
            _halftime_preview(state, text)
        elif chat == owner and text.lower().startswith("/enlace"):
            from . import guests
            guests.link_command(state, text)
        elif chat == owner and text.lower().startswith("/mensaje"):
            from . import guests
            guests.message_command(state, text)
        elif chat == owner and text.lower().startswith("/contactos"):
            from . import guests
            guests.contacts_command(state)
        elif chat == owner and text.lower().startswith("/invitar"):
            _invite_command(state, text)
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
        elif chat == owner and text.lower().startswith(("/envivo", "/vivo")):
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
            image = _pick_image(p)
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
        telegram.set_buttons(owner, mid, CANDIDATE_BUTTONS(pid) if p["status"] == "candidate" else SHARE_BUTTONS(p))
        telegram.answer(cb["id"], "Recuperado")
        return

    if action in ("a", "f", "r"):
        if p["status"] not in ("candidate", "selected") or (action != "r" and p["status"] != "candidate"):
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
        _publish(state, p, free=(action == "f"))
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
            if p.get("pick_style") == "photo":
                p["pick_style"] = "coupon"
            else:
                telegram.answer(cb["id"], "Armando la versión con foto…")
                try:
                    if not p.get("pick_layout"):
                        from . import layouts
                        p["pick_layout"] = layouts.next_layout(state, "pick")
                    _make_pick_photo(p)
                    p["pick_style"] = "photo"
                except Exception:
                    traceback.print_exc()
                    telegram.send(owner, "⚠️ No pude armar la versión con foto. Sigue la del cupón.")
                    return
            if p.get("share_msg"):
                telegram.edit_buttons_off(owner, p["share_msg"], "↪️ Reemplazada por la versión de abajo")
            _share_panel(state, p)
            telegram.answer(cb["id"])
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
    "/buscar · analiza ahora los partidos de las próximas 30 h y te manda el top 3\n"
    "/buscar 40 · igual, pero mirando 40 horas hacia adelante (máximo 47)\n"
    "/buscar nba · picks de NBA (opción A y B con argumentos) · /envivo nba · NBA en juego\n"
    "/partido Celtics vs Knicks · analiza un partido específico, en vivo o próximo (fútbol o NBA)\n"
    "/envivo · busca valor en partidos que se están jugando ahora\n"
    "/compartir 8 · vuelve a mandarte la imagen del pick #8 (o su post partido, si ya terminó)\n"
    "/titular 8 MARACA-NAZO · cambia el titular de la imagen post partido del pick #8\n"
    "/postpartido Vasco vs Boca | Sudamericana · imagen post partido de cualquier partido terminado\n"
    "/adelanto 8 10:00 · adelanto del pick #8 para historias (pistas + pick tapado hasta las 10:00)\n"
    "/invitar Juan · enlace VIP de un solo uso que vence en 7 días (/invitar Juan 30 para 30 días)\n"
    "/anular Juan · anula ese enlace\n"
    "/enlace Juan · enlace personal al bot: al tocar Iniciar recibe su acceso VIP y te aviso\n"
    "/mensaje Juan hola · le escribe a un contacto que ya inició el bot · /contactos · la lista\n"
    "/gratis · pick gratis automático (estado) · /gratis ahora · /gratis apagar · /gratis encender\n"
    "/estado · candidatos pendientes, picks en juego, historial y consultas usadas\n"
    "/ayuda · esta lista\n\n"
    "El escaneo automático sigue saliendo todos los días a las 09:07. Después, el bot elige solo el pick "
    "gratis (el más probable) y lo publica 30 min más tarde, salvo que lo cambies o lo canceles."
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


def _status_text(state: dict) -> str:
    ps = list(state["picks"].values())
    pend = sum(1 for p in ps if p["status"] == "candidate")
    live = sum(1 for p in ps if p["status"] == "published")
    w = sum(1 for p in ps if p.get("result") == "W")
    l = sum(1 for p in ps if p.get("result") == "L")
    quota = "\nOddsPapi: " + oddspapi.quota_text()
    return (f"📊 Candidatos por aprobar: {pend}\nPublicados en juego: {live}\n"
            f"Historial: {w} verdes, {l} rojas.{quota}")


def _migrate_stakes(state: dict, now) -> None:
    """Escala de stake v2: recalcula picks que aún no empiezan y corrige sus mensajes."""
    from .value import stake_for
    for p in state["picks"].values():
        if p.get("stake_v") == 2:
            continue
        if p["status"] in ("candidate", "published") and store.parse_ts(p["kickoff"]) > now:
            p["stake"] = stake_for(p.get("tier", "valor"), p["kind"], p["price"], p["edge"])
            if p["status"] == "published":
                text = formatting.channel_post(p)
                for where, mid in (p.get("channel_msgs") or {}).items():
                    chat = state["vip_chat"] if where == "vip" else config.FREE_CHANNEL
                    try:
                        telegram.edit_text(chat, mid, text)
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
    if owner and state.get("cmds_v") != 10:
        try:  # menú de comandos en Telegram (solo visible en tu chat con el bot)
            telegram._call("setMyCommands", scope={"type": "chat", "chat_id": owner}, commands=[
                {"command": "buscar", "description": "Analizar ahora y recibir el top 3"},
                {"command": "envivo", "description": "Buscar valor en partidos que se están jugando"},
                {"command": "compartir", "description": "Imagen de un pick para VIP, Gratis o Instagram"},
                {"command": "titular", "description": "Cambiar el titular de la imagen post partido"},
                {"command": "postpartido", "description": "Imagen post partido de cualquier partido (ej. Vasco vs Boca)"},
                {"command": "adelanto", "description": "Adelanto del pick para historias (ej. /adelanto 8 10:00)"},
                {"command": "invitar", "description": "Enlace VIP de un solo uso (ej. /invitar Juan)"},
                {"command": "enlace", "description": "Enlace personal al bot para un contacto (ej. /enlace Juan)"},
                {"command": "mensaje", "description": "Escribirle a un contacto (ej. /mensaje Juan hola)"},
                {"command": "contactos", "description": "Quiénes iniciaron el bot"},
                {"command": "partido", "description": "Analizar un partido específico (ej. /partido Celtics vs Knicks)"},
                {"command": "gratis", "description": "Pick gratis automático: estado, ahora, apagar o encender"},
                {"command": "estado", "description": "Pendientes, picks en juego e historial"},
                {"command": "ayuda", "description": "Lista de comandos"}])
            state["cmds_v"] = 10
        except Exception as e:
            print(f"No se pudo registrar el menú de comandos: {e}")
    _migrate_stakes(state, now)
    _refresh_recap_texts(state)
    _nba_daily(state)
    try:
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
        if p["status"] in ("candidate", "selected") and _expires(p) <= now:
            was = p["status"]
            p["status"] = "expired"
            if owner and p.get("owner_msg") and was == "candidate":
                telegram.edit_buttons_off(owner, p["owner_msg"], "⌛ Sin aprobar a tiempo")
            if owner and p.get("share_msg"):
                telegram.edit_buttons_off(owner, p["share_msg"], "⌛ Ya no está vigente")
        _remind(state, p, now)
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
            from . import ig_inbox
            ig_inbox.run(state)   # responde comentarios y mensajes directos
    except Exception:
        traceback.print_exc()
    store.save(state)
    state = _run_scan_request(state)
    from zoneinfo import ZoneInfo
    local = store.now_utc().astimezone(ZoneInfo(config.TIMEZONE))
    if (config.AUTO_SCAN_FALLBACK and state.get("owner_chat") and state.get("auto_scan_date") != _local_today()
            and (local.hour, local.minute) >= (9, 7) and local.hour < 22):
        scan()   # respaldo del escaneo diario por si el disparo de las 09:07 no corrió


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
