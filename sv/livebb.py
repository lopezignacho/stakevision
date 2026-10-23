"""Fútbol en vivo: líneas que se están cumpliendo (córners, tarjetas, goles, remates al arco).

En el descanso, con las estadísticas de ESPN (gratis), se buscan señales como:
- un equipo que ya lleva 4 córners → «más de 5.5 córners» de ese equipo (al ritmo actual llega a 8);
- muchos córners entre los dos → total de córners;
- partido caliente (tarjetas y faltas) → más tarjetas;
- muchos remates al arco y pocos goles → un gol más;
- un jugador que remata mucho pero no le acierta al arco → remates al arco del jugador.
Solo si hay señales se piden las cuotas en vivo (con un tope diario para cuidar el plan gratis), y se avisa
al dueño únicamente cuando la línea existe y paga bien.
"""
from __future__ import annotations

import re
from datetime import timedelta
from zoneinfo import ZoneInfo

import requests

from . import config, espn, formatting, oddspapi, store

ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary"


def _n(v) -> int:
    try:
        return int(float(str(v)))
    except (TypeError, ValueError):
        return 0


def _plain(s: str) -> str:
    return " ".join(espn._toks(s))


def _halftime_matches() -> list[dict]:
    """Partidos de fútbol en el descanso (o recién empezado el 2º tiempo)."""
    now = store.now_utc()
    out = []
    days = {now.astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d"),
            (now - timedelta(hours=4)).astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d")}
    for day in days:
        for e in espn._scoreboard(day, "soccer"):
            st = e.get("status") or {}
            name = (st.get("type") or {}).get("name") or ""
            clock = st.get("displayClock") or ""
            mins = int(re.match(r"\d+", clock).group()) if re.match(r"\d+", clock) else 0
            if name == "STATUS_HALFTIME" or (st.get("period") == 2 and mins and mins <= 50):
                out.append(e)
    return out


def _stats(summary: dict, e: dict) -> dict | None:
    c = (e.get("competitions") or [{}])[0]
    comp = c.get("competitors") or []
    h = next((x for x in comp if x.get("homeAway") == "home"), None)
    a = next((x for x in comp if x.get("homeAway") == "away"), None)
    if not h or not a:
        return None
    teams = {}
    for side, x in (("home", h), ("away", a)):
        tid = str(x["team"].get("id"))
        row = {"name": x["team"].get("displayName", ""), "id": tid, "goals": _n(x.get("score"))}
        for tb in (summary.get("boxscore") or {}).get("teams") or []:
            if str((tb.get("team") or {}).get("id")) == tid:
                st = {s.get("name"): s.get("displayValue") for s in tb.get("statistics") or []}
                row.update(corners=_n(st.get("wonCorners")), yellow=_n(st.get("yellowCards")),
                           red=_n(st.get("redCards")), fouls=_n(st.get("foulsCommitted")),
                           sot=_n(st.get("shotsOnTarget")), shots=_n(st.get("totalShots")))
        players = []
        for ro in summary.get("rosters") or []:
            if str((ro.get("team") or {}).get("id")) != tid:
                continue
            for pl in ro.get("roster") or []:
                s = {y.get("name"): _n(y.get("displayValue")) for y in pl.get("stats") or []}
                if s.get("totalShots"):
                    players.append({"name": (pl.get("athlete") or {}).get("displayName", ""),
                                    "shots": s.get("totalShots", 0), "sot": s.get("shotsOnTarget", 0)})
        row["players"] = players
        teams[side] = row
    if "corners" not in teams["home"] or "corners" not in teams["away"]:
        return None
    return {"id": e.get("id"), "home": teams["home"], "away": teams["away"],
            "league": ((e.get("season") or {}).get("slug") or "")}


def signals(m: dict) -> list[dict]:
    """Señales al descanso. Cada una: tipo de mercado de OddsPapi, línea y el porqué."""
    H, A = m["home"], m["away"]
    out = []
    for side, T, mtype in (("home", H, "teamtotals-corners-team1"), ("away", A, "teamtotals-corners-team2")):
        c = T["corners"]
        if c >= 3:
            line = c + 1.5
            out.append({"mtype": mtype, "line": line, "outcome": "Más", "strength": c,
                        "label": f"{T['name']}: más de {line:g} córners",
                        "why": f"Lleva {c} córners al descanso: al mismo ritmo termina cerca de {2 * c}."})
    tc = H["corners"] + A["corners"]
    if tc >= 5:
        line = tc + 2.5
        out.append({"mtype": "totals-corners", "line": line, "outcome": "Más", "strength": tc / 2,
                    "label": f"Más de {line:g} córners en el partido",
                    "why": f"Van {tc} córners entre los dos al descanso: el ritmo da para unos {2 * tc}."})
    cards = H["yellow"] + A["yellow"] + H["red"] + A["red"]
    fouls = H["fouls"] + A["fouls"]
    if cards >= 2 and fouls >= 12:
        line = cards + 1.5
        out.append({"mtype": "totals-bookings", "line": line, "outcome": "Más", "strength": cards + fouls / 10,
                    "label": f"Más de {line:g} tarjetas en el partido",
                    "why": f"Partido caliente: {cards} tarjetas y {fouls} faltas en el 1er tiempo, y el 2º suele traer más."})
    goals, sot = H["goals"] + A["goals"], H["sot"] + A["sot"]
    if sot >= 6 and goals * 3 <= sot:
        line = goals + 0.5
        out.append({"mtype": "totals", "line": line, "outcome": "Más", "strength": sot / 2,
                    "label": f"Más de {line:g} goles", "why": f"{sot} remates al arco y solo {goals} gol(es): el gol está cerca."})
    for T in (H, A):
        for p in T["players"]:
            if p["shots"] >= 3 and p["sot"] <= 1:
                need = p["sot"] + 1
                out.append({"mtype": "players-shotsongoal", "player": p["name"], "line": need, "outcome": f"{need + 0}+",
                            "strength": p["shots"], "label": f"{p['name']}: {need}+ remates al arco",
                            "why": f"Ya remató {p['shots']} veces en el 1er tiempo ({p['sot']} al arco)."})
    return sorted(out, key=lambda s: s["strength"], reverse=True)


def _find_market(odds_row: dict, markets: dict, sig: dict) -> tuple[float, float | None] | None:
    """(cuota de la casa, cuota justa de la referencia o None) de la línea exacta de la señal."""
    books = odds_row.get("bookmakerOdds") or {}
    book, ref = books.get(config.BOOK), books.get(config.REFERENCE)
    if not book:
        return None
    from .value import _price
    for mid, meta in markets.items():
        if meta.get("type") != sig["mtype"]:
            continue
        if sig["mtype"] == "players-shotsongoal":
            if meta.get("period") not in ("result", "fulltime"):
                continue
        elif meta.get("period") != "fulltime" or abs(float(meta.get("handicap") or 0) - sig["line"]) > 1e-6:
            continue
        if mid not in (book.get("markets") or {}):
            continue
        oid = next((o for o, nm in (meta.get("outcomes") or {}).items() if nm == sig["outcome"]), None)
        if not oid:
            continue
        if sig["mtype"] == "players-shotsongoal":   # buscar al jugador por nombre
            outs = ((book["markets"][mid].get("outcomes") or {}).get(oid) or {}).get("players") or {}
            want = set(_plain(sig["player"]).split())
            price = None
            for pl in outs.values():
                nm = _plain(pl.get("playerName") or pl.get("name") or "")
                if want and want & set(nm.split()) and pl.get("active") is not False and (pl.get("price") or 0) > 1:
                    price = float(pl["price"])
                    break
            if price:
                return price, None
            continue
        bp = _price(book, mid, oid)
        if not bp:
            continue
        fair = None
        if ref and mid in (ref.get("markets") or {}):
            oids = list((ref["markets"][mid].get("outcomes") or {}).keys())
            rp = [_price(ref, mid, o) for o in oids]
            if all(rp):
                tot = sum(1 / x for x in rp)
                fair = 1 / ((1 / _price(ref, mid, oid)) / tot)
        return bp, fair
    return None


def scan(state: dict) -> list[str]:
    """Alertas para el dueño (texto HTML). Marca cada partido como revisado."""
    if not config.LIVE_BB:
        return []
    done = state.setdefault("livebb_done", [])
    cands = []
    for e in _halftime_matches():
        if e.get("id") in done:
            continue
        done.append(e.get("id"))
        try:
            sm = requests.get(ESPN_SUMMARY, params={"event": e["id"]}, timeout=25).json()
        except Exception:  # noqa: BLE001
            continue
        m = _stats(sm, e)
        if not m:
            continue
        sig = [s for s in signals(m) if s["strength"] >= 3]
        if sig:
            cands.append((m, sig[:4]))
    del done[:-400]
    if not cands:
        return []
    today = store.now_utc().astimezone(ZoneInfo(config.TIMEZONE)).date().isoformat()
    q = state.setdefault("livebb_quota", {})
    if q.get("date") != today:
        q.clear()
        q.update(date=today, n=0)
    if q["n"] >= config.LIVE_BB_CHECKS_PER_DAY:
        return []
    q["n"] += 1
    now = store.now_utc()
    try:
        fixtures = oddspapi.live_fixtures((now - timedelta(hours=2, minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                          now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    except oddspapi.OddsPapiError as ex:
        print(f"OddsPapi en vivo: {ex}")
        return []
    pairs = []
    for m, sig in cands:
        fx = next((f for f in fixtures if espn._match(f.get("participant1Name") or "", {"displayName": m["home"]["name"]})
                   and espn._match(f.get("participant2Name") or "", {"displayName": m["away"]["name"]})), None)
        if fx:
            pairs.append((m, sig, fx))
    if not pairs:
        return []
    tids = list(dict.fromkeys(fx["tournamentId"] for _m, _s, fx in pairs))[:config.MAX_TOURNAMENTS_PER_CALL]
    try:
        rows = {r["fixtureId"]: r for r in oddspapi.odds_by_tournaments(tids)}
    except oddspapi.OddsPapiError as ex:
        print(f"OddsPapi en vivo: {ex}")
        return []
    markets = oddspapi.markets()
    alerts = []
    for m, sig, fx in pairs:
        row = rows.get(fx["fixtureId"])
        if not row:
            continue
        good = []
        for s in sig:
            got = _find_market(row, markets, s)
            if not got:
                continue
            price, fair = got
            if price < config.LIVE_BB_MIN_ODDS or (fair and price < fair * 0.98):
                continue
            good.append((s, price, fair))
        if not good:
            continue
        esc = formatting.escape
        H, A = m["home"], m["away"]
        lines = [f"🔴 <b>EN VIVO · descanso</b> · {esc(H['name'])} {H['goals']}-{A['goals']} {esc(A['name'])}",
                 f"📊 Córners {H['corners']}-{A['corners']} · Tarjetas {H['yellow'] + H['red']}-{A['yellow'] + A['red']} · "
                 f"Al arco {H['sot']}-{A['sot']}", ""]
        for s, price, fair in good[:3]:
            lines.append(f"🎯 <b>{esc(s['label'])}</b> @ {formatting.odds(price)}"
                         + (f" (justa {formatting.odds(fair)})" if fair else ""))
            lines.append(f"   {esc(s['why'])}")
        lines += ["", "⏱ Las cuotas en vivo cambian rápido: confírmala en tu app antes de entrar."]
        alerts.append("\n".join(lines))
    return alerts
