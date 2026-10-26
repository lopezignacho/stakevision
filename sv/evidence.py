"""Contraste con los datos: ¿la apuesta se habría cumplido en los partidos recientes y en el cara a cara?

El modelo de valor mira el mercado (cuota justa vs. disponible). Esto agrega una segunda opinión con datos (ESPN):
- forma reciente: últimos 10 partidos de cada equipo, en todas las competiciones;
- cara a cara: últimos 5 enfrentamientos entre los dos.

Para cada selección se cuenta en cuántos de esos partidos se habría cumplido. Si los datos la contradicen
(se cumplió en menos del 35 %), no puede ser el gratis automático y te llega marcada con ⚠️.
Ejemplo: «Junior: menos de 1.5 goles» con Junior marcando 2 o más en casi todos los cruces → contradicción.
"""
from __future__ import annotations

import requests

from . import espn

ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary"
CONTRA, WEAK = 0.35, 0.50
W_FORM, W_VENUE, W_H2H = 0.4, 0.2, 0.4
_LAST_TABLE: dict = {}


def _hit(l: dict, a: int, b: int) -> bool | None:
    """¿Se cumple la selección con a goles del equipo «1» (local del pick) y b del «2»? None si no aplica."""
    t, o, line = l.get("mtype", ""), str(l.get("outcome", "")).strip().lower(), l.get("handicap")
    if t == "1x2":
        return {"1": a > b, "x": a == b, "2": b > a}.get(o)
    if t == "drawnobet" and o in ("1", "2"):
        return None if a == b else ((a > b) if o == "1" else (b > a))
    if t == "bothteamsscore":
        return (a > 0 and b > 0) == o.startswith(("s", "y"))
    if t in ("totals", "teamtotals-team1", "teamtotals-team2") and line is not None:
        g = a + b if t == "totals" else (a if t.endswith("1") else b)
        if g == float(line):
            return None
        return (g > float(line)) == o.startswith(("más", "mas", "over"))
    if t == "spreads" and line is not None and o in ("1", "2"):
        d = (a - b + float(line)) if o == "1" else (b - a - float(line))
        return None if d == 0 else d > 0
    return None


def _rate(l: dict, games: list[tuple[int, int]]) -> tuple[int, int]:
    res = [_hit(l, a, b) for a, b in games]
    res = [r for r in res if r is not None]
    return sum(res), len(res)


def _score(c: dict) -> int | None:
    v = c.get("score")
    if isinstance(v, dict):
        v = v.get("value", v.get("displayValue"))
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _team_last(team_id: str, before: str, n: int = 10) -> list[tuple[int, int, bool]]:
    """Últimos n partidos terminados del equipo (todas las competiciones): (goles propios, del rival, ¿de local?)."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{team_id}/schedule"
    rows = set()
    for params in ({}, {"season": int(before[:4]) - 1}):
        try:
            evs = requests.get(url, params=params, timeout=25).json().get("events") or []
        except Exception:  # noqa: BLE001
            evs = []
        for ev in evs:
            if (ev.get("date") or "") >= before:
                continue
            c = (ev.get("competitions") or [{}])[0]
            if not ((c.get("status") or {}).get("type") or {}).get("completed"):
                continue
            comp = c.get("competitors") or []
            me = next((x for x in comp if str((x.get("team") or {}).get("id")) == str(team_id)), None)
            op = next((x for x in comp if str((x.get("team") or {}).get("id")) != str(team_id)), None)
            if not me or not op or _score(me) is None or _score(op) is None:
                continue
            rows.add((ev["date"], _score(me), _score(op), me.get("homeAway") == "home"))
        if len(rows) >= n:
            break
    return [(x, y, h) for _d, x, y, h in sorted(rows, reverse=True)[:n]]


def _espn(home: str, away: str, kickoff: str) -> tuple[list, list, list]:
    """(forma local, forma visita, cara a cara) desde ESPN."""
    found = espn._find(home, away, kickoff)
    if not found:
        return [], [], []
    e, _c, h, a = found
    hid, aid = str(h["team"]["id"]), str(a["team"]["id"])
    try:
        sm = requests.get(ESPN_SUMMARY, params={"event": e["id"]}, timeout=25).json()
    except Exception:  # noqa: BLE001
        sm = {}
    h2h = []
    for ser in sm.get("seasonseries") or []:
        if ser.get("type") != "head-to-head":
            continue
        for ev in ser.get("events") or []:
            if not (ev.get("statusType") or {}).get("completed") or ev.get("id") == e.get("id"):
                continue
            comp = ev.get("competitors") or []
            mine = next((x for x in comp if str((x.get("team") or {}).get("id")) == hid), None)
            other = next((x for x in comp if str((x.get("team") or {}).get("id")) == aid), None)
            if mine and other and _score(mine) is not None and _score(other) is not None:
                h2h.append((_score(mine), _score(other)))
    table = {}
    for grp in ((sm.get("standings") or {}).get("groups") or []):
        entries = ((grp.get("standings") or {}).get("entries") or [])
        for i, en in enumerate(entries):
            stv = {x.get("name"): x.get("value") for x in en.get("stats") or []}
            rank = stv.get("rank") or (i + 1)
            table[str(en.get("id"))] = {"rank": int(rank), "pts": int(stv.get("points") or 0),
                                        "gp": int(stv.get("gamesPlayed") or 0), "n": len(entries)}
    _LAST_TABLE.clear()
    _LAST_TABLE.update({"home": table.get(hid), "away": table.get(aid)})
    fh, fa = _team_last(hid, kickoff), _team_last(aid, kickoff)
    if len(fh) < 4 or len(fa) < 4:   # respaldo: los últimos 5 del resumen del partido
        lf_map = {}
        for lf in sm.get("lastFiveGames") or []:
            tid = str((lf.get("team") or {}).get("id"))
            rows = []
            for ev in lf.get("events") or []:
                try:
                    hs, as_ = int(ev.get("homeTeamScore")), int(ev.get("awayTeamScore"))
                except (TypeError, ValueError):
                    continue
                home_ = str(ev.get("homeTeamId")) == tid
                rows.append((hs, as_, True) if home_ else (as_, hs, False))
            lf_map[tid] = rows
        fh = fh if len(fh) >= 4 else lf_map.get(hid, [])
        fa = fa if len(fa) >= 4 else lf_map.get(aid, [])
    return fh, fa, h2h


def check(l: dict) -> dict | None:
    """Evidencia de una selección de fútbol: tasas de forma y cara a cara, mezcla y veredicto."""
    if (l.get("sport") or "soccer") != "soccer" or all(_hit(l, a, b) is None for a, b in ((1, 0), (0, 0), (2, 1))):
        return None
    try:
        fh, fa, h2h = _espn(l["home"], l["away"], l["kickoff"])
    except Exception:  # noqa: BLE001
        fh, fa, h2h = [], [], []
    table = dict(_LAST_TABLE)
    ctx = l.get("context") or {}
    if len(fh) < 4 and ctx.get("v") == 2 and isinstance(ctx.get("home"), list):
        fh = [(m["gf"], m["ga"], m.get("venue") == "L") for m in ctx["home"]][:10]
    if len(fa) < 4 and ctx.get("v") == 2 and isinstance(ctx.get("away"), list):
        fa = [(m["gf"], m["ga"], m.get("venue") == "L") for m in ctx["away"]][:10]
    fh = [tuple(x) + (None,) * (3 - len(x)) for x in fh]
    fa = [tuple(x) + (None,) * (3 - len(x)) for x in fa]
    # En los partidos del visitante, él hace de «2»: (rival, visitante)
    form_games = [(x, y) for x, y, _h in fh] + [(y, x) for x, y, _h in fa]
    # Localía: el local en sus partidos de local y el visitante en los suyos de visita
    venue_games = [(x, y) for x, y, h_ in fh if h_ is True] + [(y, x) for x, y, h_ in fa if h_ is False]
    fhits, fn = _rate(l, form_games)
    vhits, vn = _rate(l, venue_games)
    hhits, hn = _rate(l, h2h)
    if fn + hn < 4:
        return None
    parts, weights = [], []
    if fn:
        parts.append(fhits / fn)
        weights.append(W_FORM)
    if vn >= 4:
        parts.append(vhits / vn)
        weights.append(W_VENUE)
    if hn >= 3:
        parts.append(hhits / hn)
        weights.append(W_H2H)
    rate = sum(p * w for p, w in zip(parts, weights)) / sum(weights)
    goals_h2h = round(sum(x + y for x, y in h2h) / len(h2h), 1) if h2h else None
    verdict = "contra" if rate < CONTRA and fn + hn >= 6 else "debil" if rate < WEAK else "ok"
    # El cara a cara pesa por sí solo: si casi nunca se dio entre ellos, no puede ser «ok»
    if hn >= 4 and hhits / hn < 0.25 and verdict == "ok":
        verdict = "debil"
    # Tabla: apostar por un equipo muy por debajo del rival (8+ puestos, con 5+ fechas) no puede ser «ok»
    t_h, t_a = table.get("home"), table.get("away")
    o, t = str(l.get("outcome", "")).lower(), l.get("mtype", "")
    side = {"1": ("home", "away"), "2": ("away", "home")}.get(o) if t in ("1x2", "drawnobet", "spreads") else None
    if side and t_h and t_a and min(t_h["gp"], t_a["gp"]) >= 5:
        me, op = (t_h, t_a) if side[0] == "home" else (t_a, t_h)
        if me["rank"] - op["rank"] >= 8 and verdict == "ok":
            verdict = "debil"
    return {"form": [fhits, fn], "venue": [vhits, vn], "h2h": [hhits, hn], "rate": round(rate, 3),
            "verdict": verdict, "h2h_goals": goals_h2h, "h2h_n": len(h2h),
            "table": {"home": t_h, "away": t_a} if t_h and t_a else None,
            "raw": {"home": [list(x) for x in fh[:10]], "away": [list(x) for x in fa[:10]],
                    "h2h": [list(x) for x in h2h[:5]]}}


def blend(market_p: float, ev: dict | None) -> float:
    """Probabilidad final: 65 % mercado + 35 % datos (si hay datos suficientes)."""
    if not ev:
        return market_p
    n = ev["form"][1] + ev["h2h"][1]
    w = 0.35 if n >= 8 else 0.2
    return round((1 - w) * market_p + w * ev["rate"], 4)


def line(ev: dict | None) -> str:
    """Texto corto para el dueño: «📚 Datos: forma reciente 7/20 · cara a cara 1/5 → ⚠️ los datos lo contradicen»."""
    if not ev:
        return "📚 Datos: sin historial suficiente para contrastar."
    bits = []
    if ev["form"][1]:
        bits.append(f"forma reciente {ev['form'][0]}/{ev['form'][1]}")
    if (ev.get("venue") or [0, 0])[1] >= 4:
        bits.append(f"local/visita {ev['venue'][0]}/{ev['venue'][1]}")
    if ev["h2h"][1]:
        bits.append(f"cara a cara {ev['h2h'][0]}/{ev['h2h'][1]}"
                    + (f" ({str(ev['h2h_goals']).replace('.', ',')} goles por partido)"
                       if ev.get("h2h_goals") is not None else ""))
    tb = ev.get("table")
    if tb:
        bits.append(f"tabla {tb['home']['rank']}º vs {tb['away']['rank']}º")
    tag = {"ok": "✅ los datos acompañan", "debil": "🟡 los datos acompañan a medias",
           "contra": "⚠️ los datos lo contradicen"}[ev["verdict"]]
    return f"📚 Datos: {' · '.join(bits)} → {tag}"
