"""NBA: datos de ESPN (sin clave), argumentos de cada pick y resumen diario.

Fuentes:
- Cuotas: OddsPapi (Betano + Pinnacle, deporte 11, torneo NBA 132), igual que en fútbol.
- Contexto: ESPN (calendario y resultados, récord local/visita, lesiones, pronóstico de ESPN,
  probabilidad en vivo, noticias y traspasos).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from . import config, formatting

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
SPORT_ID = 11
TOURNAMENT_ID = 132
MARKET_TYPES = {"moneyline", "spreads", "totals", "teamtotals-team1", "teamtotals-team2"}


def _get(path: str, **params):
    try:
        r = requests.get(f"{ESPN}{path}", params=params, timeout=25)
        return r.json() if r.ok else {}
    except Exception:  # noqa: BLE001
        return {}


def _plain(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _same_team(a: str, b: str) -> bool:
    """«LA Clippers» = «Los Angeles Clippers», «Boston Celtics» = «Celtics»: basta con el apodo."""
    ta, tb = _plain(a).split(), _plain(b).split()
    return bool(ta and tb and ta[-1] == tb[-1])


def _ny_day(iso: str) -> str:
    d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
    return d.strftime("%Y%m%d")


def find_event(home: str, away: str, kickoff_iso: str) -> tuple[dict, bool] | None:
    """(evento ESPN, invertido). invertido=True si el «local» de OddsPapi es la visita en ESPN."""
    data = _get("/scoreboard", dates=_ny_day(kickoff_iso))
    for e in data.get("events") or []:
        comp = (e.get("competitions") or [{}])[0].get("competitors") or []
        h = next((x for x in comp if x.get("homeAway") == "home"), {})
        a = next((x for x in comp if x.get("homeAway") == "away"), {})
        hn, an = (h.get("team") or {}).get("displayName", ""), (a.get("team") or {}).get("displayName", "")
        if _same_team(home, hn) and _same_team(away, an):
            return e, False
        if _same_team(home, an) and _same_team(away, hn):
            return e, True
    return None


def final_score(home: str, away: str, kickoff_iso: str):
    """Marcador final (con prórroga) en el orden home/away de OddsPapi, o None si no terminó."""
    found = find_event(home, away, kickoff_iso)
    if not found:
        return None
    e, inv = found
    if not ((e.get("status") or {}).get("type") or {}).get("completed"):
        return None
    comp = e["competitions"][0]["competitors"]
    h = int(float(next(x for x in comp if x["homeAway"] == "home").get("score") or 0))
    a = int(float(next(x for x in comp if x["homeAway"] == "away").get("score") or 0))
    return (a, h) if inv else (h, a)


# ---------------------------------------------------------------- contexto de cada equipo
def _team_games(team_id: str, now: datetime, n: int = 10) -> list[dict]:
    """Últimos partidos terminados (temporada actual y, si faltan, la anterior), del más reciente al más antiguo."""
    out = []
    season = now.year + 1 if now.month >= 9 else now.year
    for s in (season, season - 1):
        data = _get(f"/teams/{team_id}/schedule", season=s)
        games = []
        for e in data.get("events") or []:
            c = (e.get("competitions") or [{}])[0]
            if not ((c.get("status") or {}).get("type") or {}).get("completed"):
                continue
            me = next((x for x in c.get("competitors") or [] if str(x.get("team", {}).get("id")) == str(team_id)), None)
            op = next((x for x in c.get("competitors") or [] if str(x.get("team", {}).get("id")) != str(team_id)), None)
            if not me or not op:
                continue
            sc = lambda x: int(float((x.get("score") or {}).get("value") or 0))  # noqa: E731
            games.append({"date": e.get("date"), "pf": sc(me), "pa": sc(op), "home": me.get("homeAway") == "home",
                          "opp": (op.get("team") or {}).get("displayName", ""), "season": s})
        games.sort(key=lambda g: g["date"] or "", reverse=True)
        out += games
        if len(out) >= n:
            break
    return out[:n]


def _record(comp: dict, kind: str) -> str:
    return next((r.get("summary") for r in comp.get("records") or [] if r.get("type") == kind), "")


def context(home: str, away: str, kickoff_iso: str) -> dict | None:
    """Datos para los argumentos: forma, récord, descanso, lesiones y pronóstico de ESPN."""
    found = find_event(home, away, kickoff_iso)
    if not found:
        return None
    e, inv = found
    comp = e["competitions"][0]["competitors"]
    by_side = {x["homeAway"]: x for x in comp}
    summary = _get("/summary", event=e.get("id"))
    pred = summary.get("predictor") or {}
    leaders = set()
    for t in summary.get("leaders") or []:
        for cat in t.get("leaders") or []:
            for ld in (cat.get("leaders") or [])[:1]:
                leaders.add(((ld.get("athlete") or {}).get("displayName") or "").lower())
    inj_by_team = {}
    for t in summary.get("injuries") or []:
        rows = []
        for i in t.get("injuries") or []:
            name = (i.get("athlete") or {}).get("displayName") or ""
            rows.append({"name": name, "status": i.get("status") or "", "key": name.lower() in leaders,
                         "type": (i.get("details") or {}).get("type") or ""})
        inj_by_team[str((t.get("team") or {}).get("id"))] = rows
    now = datetime.now(timezone.utc)
    ko = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00"))
    out = {"event": e.get("id")}
    for side in ("home", "away"):
        x = by_side.get(side) or {}
        tid = str((x.get("team") or {}).get("id") or "")
        games = _team_games(tid, now) if tid else []
        last = next((g for g in games if g["date"]), None)
        rest = None
        if last:
            rest = (ko - datetime.fromisoformat(last["date"].replace("Z", "+00:00"))).total_seconds() / 86400
        proj = (pred.get("homeTeam" if side == "home" else "awayTeam") or {}).get("gameProjection")
        out[side] = {"name": (x.get("team") or {}).get("displayName", ""), "id": tid,
                     "record": _record(x, "total"), "home_rec": _record(x, "home"), "road_rec": _record(x, "road"),
                     "games": games, "rest_days": rest, "injuries": inj_by_team.get(tid, []),
                     "espn_prob": float(proj) / 100 if proj else None}
    if inv:   # dejarlo en el orden de OddsPapi (participante 1 = «home» del pick)
        out["home"], out["away"] = out["away"], out["home"]
    out["inverted"] = inv
    return out


# ---------------------------------------------------------------- argumentos
def _avg(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _form(t: dict) -> dict:
    g = t["games"][:10]
    w = sum(x["pf"] > x["pa"] for x in g)
    newest = max((x["season"] for x in g), default=0)
    n_cur = sum(x["season"] == newest for x in g)
    return {"n": len(g), "w": w, "pf": _avg([x["pf"] for x in g]), "pa": _avg([x["pa"] for x in g]),
            "margin": _avg([x["pf"] - x["pa"] for x in g]), "streak": _streak(g),
            "only_last_season": bool(g) and n_cur < 3}


def _streak(g: list[dict]) -> str:
    if not g:
        return ""
    won = g[0]["pf"] > g[0]["pa"]
    k = 0
    for x in g:
        if (x["pf"] > x["pa"]) != won:
            break
        k += 1
    return f"{k} {'victorias' if won else 'derrotas'} seguidas" if k >= 3 else ""


def arguments(leg: dict, ctx: dict | None) -> tuple[list[str], list[str]]:
    """(a favor, en contra) del pick, con datos concretos. Sirve para la opción A y la B."""
    pros, cons = [], []
    edge = leg.get("edge", 0)
    if edge >= config.MIN_EDGE:
        pros.append(f"Valor: la cuota justa es {formatting.odds(leg['fair_odds'])} y la disponible "
                    f"{formatting.odds(leg['price'])} (+{formatting.pct(edge)}).")
    elif edge >= 0:
        pros.append(f"Cuota en línea con la justa ({formatting.odds(leg['fair_odds'])}): el mercado no la regala, "
                    "la elección se apoya en los datos de abajo.")
    else:
        cons.append(f"Paga un poco menos que la cuota justa ({formatting.odds(leg['fair_odds'])}).")
    if not ctx:
        return pros, cons
    t, o = leg.get("mtype", ""), str(leg.get("outcome", "")).lower()
    side = {"1": "home", "2": "away"}.get(o)
    if t == "teamtotals-team1":
        side = "home"
    if t == "teamtotals-team2":
        side = "away"
    H, A = ctx["home"], ctx["away"]
    fh, fa = _form(H), _form(A)
    tag = lambda f: " (incluye la temporada pasada)" if f["only_last_season"] else ""  # noqa: E731
    if t in ("moneyline", "spreads") and side:
        me, op = (H, A) if side == "home" else (A, H)
        fm, fo = (fh, fa) if side == "home" else (fa, fh)
        if fm["n"] >= 5:
            line = (f"{me['name']}: {fm['w']}-{fm['n'] - fm['w']} en sus últimos {fm['n']}{tag(fm)}, "
                    f"diferencia media {fm['margin']:+.1f} pts")
            (pros if fm["margin"] > fo["margin"] else cons).append(line + (f" ({fm['streak']})." if fm["streak"] else "."))
        if fo["n"] >= 5:
            line = f"{op['name']}: diferencia media {fo['margin']:+.1f} pts en sus últimos {fo['n']}{tag(fo)}."
            (pros if fo["margin"] < fm["margin"] else cons).append(line)
        rec = me["home_rec"] if side == "home" else me["road_rec"]
        if rec and rec != "0-0":
            pros.append(f"{me['name']} {'de local' if side == 'home' else 'de visita'} esta temporada: {rec}.")
        if me.get("espn_prob"):
            p = me["espn_prob"]
            (pros if p >= 0.5 else cons).append(f"El pronóstico de ESPN le da {formatting.pct(p)} de ganar.")
        if t == "spreads" and leg.get("handicap") is not None:
            h = float(leg["handicap"]) if side == "home" else -float(leg["handicap"])
            if fm["n"] >= 5 and fo["n"] >= 5:
                proj = (fm["margin"] - fo["margin"]) / 2 + (1.5 if side == "home" else -1.5)
                txt = f"Proyección simple por diferencia de puntos: {proj:+.1f} para {me['name']} (línea {h:+g})."
                (pros if proj + h > 0 else cons).append(txt)
    if t in ("totals", "teamtotals-team1", "teamtotals-team2") and leg.get("handicap") is not None:
        line = float(leg["handicap"])
        over = o.startswith(("más", "mas", "over"))
        if t == "totals" and fh["n"] >= 5 and fa["n"] >= 5:
            exp = (fh["pf"] + fa["pa"]) / 2 + (fa["pf"] + fh["pa"]) / 2
            txt = (f"Promedios recientes: {H['name']} anota {fh['pf']:.1f} y recibe {fh['pa']:.1f}; "
                   f"{A['name']} anota {fa['pf']:.1f} y recibe {fa['pa']:.1f} → proyección {exp:.1f} pts (línea {line:g}).")
            (pros if (exp > line) == over else cons).append(txt)
        elif side:
            me, fm = (H, fh) if side == "home" else (A, fa)
            op_f = fa if side == "home" else fh
            if fm["n"] >= 5:
                exp = (fm["pf"] + op_f["pa"]) / 2
                txt = f"{me['name']} anota {fm['pf']:.1f} de media y el rival recibe {op_f['pa']:.1f} → {exp:.1f} (línea {line:g})."
                (pros if (exp > line) == over else cons).append(txt)
    for s_name, T_ in (("home", H), ("away", A)):
        rd = T_.get("rest_days")
        if rd is not None and rd < 1.6:
            mine = side == s_name
            txt = f"{T_['name']} juega en back-to-back (jugó ayer): suele pesar en piernas y rotación."
            (cons if mine else pros).append(txt) if side else cons.append(txt)
    for s_name, T_ in (("home", H), ("away", A)):
        outs = [i for i in T_["injuries"] if i["status"].lower() in ("out", "doubtful")]
        if not outs:
            continue
        keys = [i["name"] for i in outs if i["key"]]
        names = ", ".join((i["name"] + (" ⭐" if i["key"] else "")) for i in outs[:4])
        txt = f"Bajas de {T_['name']}: {names}."
        if side:
            (cons if side == s_name else pros).append(txt)
        elif keys:
            cons.append(txt + " Con figuras afuera, el total puede moverse.")
    return pros[:7], cons[:3]


def arguments_text(leg: dict, ctx: dict | None) -> str:
    pros, cons = arguments(leg, ctx)
    out = []
    if pros:
        out.append("✅ <b>A favor:</b>\n" + "\n".join(f"• {formatting.escape(p)}" for p in pros))
    if cons:
        out.append("⚠️ <b>En contra:</b>\n" + "\n".join(f"• {formatting.escape(c)}" for c in cons))
    return "\n".join(out)


# ---------------------------------------------------------------- opciones A y B por partido
def options_for_game(sels: list) -> tuple | None:
    """Opción A: la mejor dentro de 1.65-2.00. Opción B: otra apuesta del mismo partido (otro mercado
    o fuera de rango) con buen valor. Devuelve (A, B, tier) o None."""
    in_range = [s for s in sels if config.ODDS_MIN <= s.price <= config.ODDS_MAX and s.edge <= config.MAX_EDGE]
    if not in_range:
        return None
    in_range.sort(key=lambda s: s.edge, reverse=True)
    a = in_range[0]
    if a.edge < config.FALLBACK_MIN_EDGE:
        return None
    tier = "valor" if a.edge >= config.MIN_EDGE else "justa"
    others = [s for s in sels if s is not a and 1.30 <= s.price <= 3.20 and s.edge <= config.MAX_EDGE
              and (s.mtype != a.mtype or not (config.ODDS_MIN <= s.price <= config.ODDS_MAX))]
    others.sort(key=lambda s: s.edge, reverse=True)
    b = others[0] if others and others[0].edge >= config.FALLBACK_MIN_EDGE else None
    return a, b, tier


def why_line(sel, role: str) -> str:
    """Una línea que explica qué tipo de apuesta es cada opción."""
    if role == "A":
        return "Opción principal: dentro de nuestro rango (1.65-2.00), la de más valor del partido."
    if sel.price < config.ODDS_MIN:
        return "Alternativa más conservadora: cuota más baja, pero más probable."
    if sel.price > config.ODDS_MAX:
        return "Alternativa de más riesgo: paga más, sale menos veces."
    return "Alternativa en otro mercado, por si prefieres no depender del mismo resultado."


# ---------------------------------------------------------------- resumen diario
def digest(now: datetime | None = None) -> str:
    """Noticias, lesiones y traspasos de las últimas 24 h + partidos del día (para el dueño)."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=26)
    esc = formatting.escape
    tz = ZoneInfo(config.TIMEZONE)

    def recent(iso: str | None) -> bool:
        try:
            return datetime.fromisoformat((iso or "").replace("Z", "+00:00")) >= since
        except ValueError:
            return False

    lines = [f"🏀 <b>NBA · resumen del día</b> ({now.astimezone(tz):%d/%m})", ""]
    sb = _get("/scoreboard", dates=now.astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d"))
    games = []
    for e in sb.get("events") or []:
        c = e["competitions"][0]
        h = next(x for x in c["competitors"] if x["homeAway"] == "home")
        a = next(x for x in c["competitors"] if x["homeAway"] == "away")
        t = datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(tz)
        games.append(f"• {t:%H:%M} {esc(a['team']['shortDisplayName'])} ({_record(a, 'total')}) @ "
                     f"{esc(h['team']['shortDisplayName'])} ({_record(h, 'total')})")
    lines += [f"📅 <b>Partidos de hoy</b> (hora Chile): {len(games)}"] + (games or ["• No hay partidos hoy."])
    inj = _get("/injuries")
    rows = []
    for t in inj.get("injuries") or []:
        for i in t.get("injuries") or []:
            if recent(i.get("date")) and (i.get("status") or "").lower() in ("out", "doubtful", "day-to-day",
                                                                                "questionable"):
                rows.append(f"• {esc((i.get('athlete') or {}).get('displayName', '?'))} "
                            f"({esc(t.get('displayName', ''))}): {esc(i.get('status', ''))}"
                            + (f" · {esc((i.get('details') or {}).get('type', ''))}" if (i.get('details') or {}).get('type') else ""))
    lines += ["", f"🚑 <b>Lesiones actualizadas (24 h)</b>: {len(rows)}"] + (rows[:15] or ["• Sin novedades."])
    tx = _get("/transactions", limit=40)
    trows = [f"• {esc((x.get('team') or {}).get('abbreviation', ''))}: {esc(x.get('description', ''))}"
             for x in tx.get("transactions") or [] if recent(x.get("date"))]
    lines += ["", f"🔁 <b>Movimientos (fichajes, traspasos, cortes)</b>: {len(trows)}"] + (trows[:10] or ["• Sin movimientos."])
    news = _get("/news", limit=8)
    nrows = [f"• {esc(a.get('headline', ''))}" for a in news.get("articles") or [] if recent(a.get("published"))]
    lines += ["", "📰 <b>Noticias</b> (titulares de ESPN, en inglés)"] + (nrows[:6] or ["• Sin titulares nuevos."])
    lines += ["", "Para ver picks de hoy: /buscar nba · en vivo: /envivo nba"]
    return "\n".join(lines)


# ---------------------------------------------------------------- en vivo: posibles remontadas
def live_alerts(state: dict) -> list[str]:
    """Revisa los partidos en juego (solo ESPN, sin gastar consultas de cuotas) y devuelve alertas nuevas:
    el favorito antes del partido pierde por 10+ en el 2º o 3er cuarto, o por 6-12 al inicio del 4º."""
    now = datetime.now(timezone.utc)
    sb = _get("/scoreboard", dates=now.astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d"))
    seen = state.setdefault("nba_live", {})
    alerts = []
    for e in sb.get("events") or []:
        st = e.get("status") or {}
        if (st.get("type") or {}).get("state") != "in":
            continue
        eid = e["id"]
        info = seen.setdefault(eid, {"sent": []})
        if "pre" not in info:
            pred = (_get("/summary", event=eid).get("predictor") or {})
            hp = (pred.get("homeTeam") or {}).get("gameProjection")
            info["pre"] = float(hp) / 100 if hp else None
        pre = info["pre"]
        if pre is None:
            continue
        c = e["competitions"][0]
        h = next(x for x in c["competitors"] if x["homeAway"] == "home")
        a = next(x for x in c["competitors"] if x["homeAway"] == "away")
        hs, as_ = int(float(h.get("score") or 0)), int(float(a.get("score") or 0))
        fav, fav_s, opp_s, fav_p = (h, hs, as_, pre) if pre >= 0.5 else (a, as_, hs, 1 - pre)
        deficit = opp_s - fav_s
        period = st.get("period") or 0
        clock = st.get("displayClock") or ""
        mins = int(clock.split(":")[0]) if ":" in clock else 0
        key = None
        if fav_p >= 0.55 and period in (2, 3) and deficit >= 10:
            key = f"q{period}"
        elif fav_p >= 0.55 and period == 4 and mins >= 8 and 6 <= deficit <= 12:
            key = "q4"
        if not key or key in info["sent"]:
            continue
        summ = _get("/summary", event=eid)
        wp = (summ.get("winprobability") or [])
        live_p = None
        if wp:
            hp = wp[-1].get("homeWinPercentage")
            live_p = hp if fav is h else 1 - hp if hp is not None else None
        info["sent"].append(key)
        name = fav["team"]["displayName"]
        rival = (a if fav is h else h)["team"]["displayName"]
        txt = [f"🏀🔴 <b>Posible remontada</b> · {formatting.escape(name)} vs {formatting.escape(rival)}",
               f"Marcador: {formatting.escape(name)} {fav_s} - {opp_s} · {period}º cuarto, {clock}",
               f"• Antes del partido era favorito: {formatting.pct(fav_p)} (pronóstico ESPN)."]
        if live_p:
            fair = 1 / max(live_p, 0.01)
            txt += [f"• Probabilidad en vivo (ESPN): {formatting.pct(live_p)} → cuota justa {fair:.2f}.",
                    f"👉 Si Betano paga <b>más de {fair * 1.05:.2f}</b> por {formatting.escape(name)} a ganar, hay valor "
                    "según ese modelo. Si paga menos, no conviene."]
        txt += ["Los partidos de NBA cambian rápido: revisa la cuota y el ritmo antes de entrar.",
                "Para comparar con las cuotas reales de Betano y Pinnacle: /envivo nba"]
        alerts.append("\n".join(txt))
    # limpiar partidos viejos
    if len(seen) > 60:
        for k in list(seen)[:-60]:
            seen.pop(k, None)
    return alerts
