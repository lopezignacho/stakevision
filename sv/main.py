"""Punto de entrada.

    python -m sv.main scan    # busca valor y te manda candidatos (1 vez al día)
    python -m sv.main poll    # procesa tus botones, publica y pide resultados (cada ~10 min)
    python -m sv.main setup   # descarga la lista de mercados (1 vez)
"""
from __future__ import annotations

import sys
import traceback
from datetime import timedelta

from . import apifootball, config, formatting, oddspapi, store, telegram
from .value import build_picks, selections_for_fixture

CANDIDATE_BUTTONS = lambda pid: [  # noqa: E731
    [("✅ Solo VIP", f"a:{pid}"), ("✅ VIP + Gratis", f"f:{pid}")],
    [("❌ Descartar", f"r:{pid}")],
]
RESULT_BUTTONS = lambda pid: [  # noqa: E731
    [("✅ Verde", f"W:{pid}"), ("❌ Roja", f"L:{pid}"), ("↩️ Nula", f"V:{pid}")],
]


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- escaneo diario
def scan(hours: int | None = None, top: int | None = None, manual: bool = False) -> None:
    state = store.load()
    if not state["owner_chat"]:
        print("Aún no está vinculado tu chat. Escribe al bot: /vincular <tu código>")
        return
    now = store.now_utc()
    hours = min(hours or config.WINDOW_END_H, 47)
    title = f"🔎 Búsqueda manual ({hours} h)" if manual else "🔎 Escaneo de hoy"
    frm, to = now + timedelta(hours=config.WINDOW_START_H), now + timedelta(hours=hours)

    markets = oddspapi.markets()
    fixtures = oddspapi.upcoming_fixtures(_iso(frm), _iso(to))
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
        telegram.send(state["owner_chat"], f"{title}: ninguna de tus ligas tiene partidos en las "
                      f"próximas {hours} horas.")
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
                  f"Sugerencia: 1 para el canal gratis (✅ VIP + Gratis) y hasta 3 para el VIP. "
                  f"Revisa cada cuota en tu app antes de aprobar.")
    for p in picks:
        d = p.to_dict()
        for leg in d["legs"]:
            leg["label"] = formatting.outcome_label(leg)
            leg["context"] = apifootball.context(leg["home"], leg["away"], leg["kickoff"])
        state["seq"] += 1
        pid = str(state["seq"])
        d.update(id=pid, status="candidate", created_at=_iso(now), stake_v=2)
        d["analysis"] = formatting.analysis(d)
        msg = telegram.send(state["owner_chat"], formatting.owner_candidate(d), CANDIDATE_BUTTONS(pid))
        d["owner_msg"] = msg["message_id"]
        state["picks"][pid] = d
        store.save(state)  # guardar tras cada envío por si algo falla a mitad


# ---------------------------------------------------------------- resultados
def _suggest(pick: dict) -> str | None:
    """Sugiere verde/roja con el marcador de 90' de API-Football (no gasta OddsPapi).
    Solo para mercados que sabemos leer. Siempre lo confirmas tú."""
    results = []
    for l in pick["legs"]:
        sc = apifootball.final_score(l["home"], l["away"], l["kickoff"])
        if not sc:
            return None
        h, a = sc
        t, o, line = l.get("mtype", ""), str(l.get("outcome", "")).lower(), l.get("handicap")
        won = None
        if t == "1x2":
            won = {"1": h > a, "x": h == a, "2": h < a}.get(o)
        elif t == "bothteamsscore":
            won = (h > 0 and a > 0) == o.startswith("s")
        elif t in ("totals", "teamtotals-team1", "teamtotals-team2") and line is not None:
            goals = h + a if t == "totals" else (h if t.endswith("1") else a)
            if goals == float(line):
                results.append("V")
                continue
            won = goals > float(line) if o.startswith("m\u00e1s") or o.startswith("mas") else goals < float(line)
        elif t in ("toscore-team1", "toscore-team2"):
            goals = h if t.endswith("1") else a
            won = (goals > 0) == o.startswith("s")
        elif t == "drawnobet":
            if h == a:
                results.append("V")
                continue
            won = (h > a) if o == "1" else (a > h)
        if won is None:
            return None
        results.append("W" if won else "L")
    if "L" in results:
        return "L"
    if all(r == "V" for r in results):
        return "V"
    return "W"


def _publish(state: dict, p: dict, free: bool) -> None:
    text = formatting.channel_post(p)
    p["channel_msgs"] = {}
    vip = state.get("vip_chat")
    if vip:
        p["channel_msgs"]["vip"] = telegram.send(vip, text)["message_id"]
    if free:
        p["channel_msgs"]["free"] = telegram.send(config.FREE_CHANNEL, text)["message_id"]
    p.update(status="published", free=free, published_at=_iso(store.now_utc()))


def _settle(state: dict, p: dict, result: str) -> None:
    p.update(result=result, status="settled", settled_at=_iso(store.now_utc()))
    text = formatting.result_post(p)
    for where, mid in (p.get("channel_msgs") or {}).items():
        chat = state["vip_chat"] if where == "vip" else config.FREE_CHANNEL
        try:
            telegram.send(chat, text, reply_to=mid)
        except telegram.TelegramError as e:
            print(f"No se pudo publicar resultado en {where}: {e}")


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
        if text.lower().startswith("/vincular") and not text.lower().startswith("/vincular_vip"):
            if _code_ok(text):
                state["owner_chat"] = chat
                telegram.send(chat, "🔗 Listo, este chat quedó vinculado como dueño de Stakevision.")
            else:
                telegram.send(chat, "⚠️ Ese código no coincide con LINK_CODE. Revísalo y vuelve a enviar /vincular CODIGO")
        elif chat == owner and text.startswith("/estado"):
            telegram.send(chat, _status_text(state))
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

    if action in ("a", "f", "r"):
        if p["status"] != "candidate":
            telegram.answer(cb["id"], "Ya estaba procesado")
            return
        if action == "r":
            p["status"] = "rejected"
            telegram.edit_buttons_off(owner, cb["message"]["message_id"], "❌ Descartado")
            telegram.answer(cb["id"], "Descartado")
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

    elif action in ("W", "L", "V"):
        if p["status"] != "published":
            telegram.answer(cb["id"], "Ya estaba cerrado")
            return
        _settle(state, p, action)
        telegram.edit_buttons_off(owner, cb["message"]["message_id"], formatting.RESULT_LABEL[action])
        telegram.answer(cb["id"], "Resultado guardado")


HELP_TEXT = (
    "👁 <b>Comandos de Stakevision</b>\n\n"
    "/buscar · analiza ahora los partidos de las próximas 30 h y te manda el top 3\n"
    "/buscar 40 · igual, pero mirando 40 horas hacia adelante (máximo 47)\n"
    "/estado · candidatos pendientes, picks en juego, historial y consultas usadas\n"
    "/ayuda · esta lista\n\n"
    "El escaneo automático sigue saliendo todos los días a las 09:07."
)


def _request_search(state: dict, text: str) -> None:
    from zoneinfo import ZoneInfo
    owner = state["owner_chat"]
    parts = text.split()
    hours = config.WINDOW_END_H
    if len(parts) > 1:
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


def poll() -> None:
    state = store.load()
    ups = telegram.updates(state["tg_offset"])
    kinds = [k for u in ups for k in ("message", "channel_post", "callback_query") if k in u]
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

    now = store.now_utc()
    owner = state.get("owner_chat")
    if owner and state.get("cmds_v") != 1:
        try:  # menú de comandos en Telegram (solo visible en tu chat con el bot)
            telegram._call("setMyCommands", scope={"type": "chat", "chat_id": owner}, commands=[
                {"command": "buscar", "description": "Analizar ahora y recibir el top 3"},
                {"command": "estado", "description": "Pendientes, picks en juego e historial"},
                {"command": "ayuda", "description": "Lista de comandos"}])
            state["cmds_v"] = 1
        except Exception as e:
            print(f"No se pudo registrar el menú de comandos: {e}")
    _migrate_stakes(state, now)
    for p in state["picks"].values():
        if p["status"] == "candidate" and store.parse_ts(p["kickoff"]) <= now:
            p["status"] = "expired"
            if owner and p.get("owner_msg"):
                telegram.edit_buttons_off(owner, p["owner_msg"], "⌛ Sin aprobar a tiempo")
        last_kick = max(store.parse_ts(l["kickoff"]) for l in p["legs"])
        if (p["status"] == "published" and not p.get("result_asked") and owner
                and now >= last_kick + timedelta(minutes=config.RESULT_CHECK_AFTER_MIN)):
            sug = _suggest(p)
            telegram.send(owner, formatting.owner_result_request(p, sug), RESULT_BUTTONS(p["id"]))
            p["result_asked"] = True
    request = state.pop("scan_request", None)
    store.save(state)
    if request:
        scan(hours=request, top=config.MANUAL_TOP, manual=True)


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
    {"scan": scan, "poll": poll, "setup": setup}[cmd]()
