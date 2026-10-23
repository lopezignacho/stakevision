"""Contraste con los datos: ¿la apuesta se habría cumplido en los partidos recientes y en el cara a cara?

El modelo de valor mira el mercado (cuota justa vs. disponible). Esto agrega una segunda opinión con datos:
- forma reciente de cada equipo (historial propio; si falta, los últimos 5 de ESPN);
- cara a cara (API-Football, últimos 10 enfrentamientos).

Para cada selección se cuenta en cuántos de esos partidos se habría cumplido. Si los datos la contradicen
(se cumplió en menos del 35 %), no puede ser el gratis automático y te llega marcada con ⚠️.
Ejemplo: «Menos de 1.5 goles» en Junior vs Águilas: 0 de 6 en el cara a cara → contradicción.
"""
from __future__ import annotations

import requests

from . import apifootball, espn

ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary"
CONTRA, WEAK = 0.35, 0.50
W_FORM, W_H2H = 0.6, 0.4


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


def _espn_form(home: str, away: str, kickoff: str) -> tuple[list, list]:
    """Últimos 5 de cada equipo desde ESPN, como (goles del equipo, goles del rival)."""
    found = espn._find(home, away, kickoff)
    if not found:
        return [], []
    e, _c, h, a = found
    try:
        sm = requests.get(ESPN_SUMMARY, params={"event": e["id"]}, timeout=25).json()
    except Exception:  # noqa: BLE001
        return [], []
    out = {}
    for lf in sm.get("lastFiveGames") or []:
        tid = str((lf.get("team") or {}).get("id"))
        rows = []
        for ev in lf.get("events") or []:
            try:
                hs, as_ = int(ev.get("homeTeamScore")), int(ev.get("awayTeamScore"))
            except (TypeError, ValueError):
                continue
            mine_home = str(ev.get("homeTeamId")) == tid
            rows.append((hs, as_) if mine_home else (as_, hs))
        out[tid] = rows
    return out.get(str(h["team"]["id"]), []), out.get(str(a["team"]["id"]), [])


def _h2h(home: str, away: str, kickoff: str) -> list[tuple[int, int]]:
    """Últimos enfrentamientos (goles del local del pick, goles del visitante del pick)."""
    fx = apifootball.find_fixture(home, away, kickoff[:10])
    if not fx:
        return []
    hid, aid = fx["teams"]["home"]["id"], fx["teams"]["away"]["id"]
    rows = apifootball._get("/fixtures/headtohead", h2h=f"{hid}-{aid}", last=10) or []
    out = []
    for r in rows:
        if ((r.get("fixture") or {}).get("status") or {}).get("short") not in ("FT", "AET", "PEN"):
            continue
        ft = (r.get("score") or {}).get("fulltime") or {}
        g_h, g_a = ft.get("home"), ft.get("away")
        if g_h is None or g_a is None:
            g_h, g_a = (r.get("goals") or {}).get("home"), (r.get("goals") or {}).get("away")
        if g_h is None or g_a is None:
            continue
        home_is_ours = r["teams"]["home"]["id"] == hid
        out.append((g_h, g_a) if home_is_ours else (g_a, g_h))
    return out


def check(l: dict) -> dict | None:
    """Evidencia de una selección de fútbol: tasas de forma y H2H, mezcla y veredicto."""
    if (l.get("sport") or "soccer") != "soccer" or _hit(l, 1, 0) is None and _hit(l, 0, 0) is None \
            and _hit(l, 2, 1) is None:
        return None
    ctx = l.get("context") or {}
    fh, fa = [], []
    if ctx.get("v") == 2 and isinstance(ctx.get("home"), list):
        fh = [(m["gf"], m["ga"]) for m in ctx.get("home") or []][:10]
        fa = [(m["gf"], m["ga"]) for m in ctx.get("away") or []][:10]
    if len(fh) < 4 or len(fa) < 4:
        try:
            eh, ea = _espn_form(l["home"], l["away"], l["kickoff"])
        except Exception:  # noqa: BLE001
            eh, ea = [], []
        fh, fa = (fh if len(fh) >= 4 else eh), (fa if len(fa) >= 4 else ea)
    # En los partidos del visitante, él hace de «2»: (rival, visitante)
    form_games = list(fh) + [(b, a) for a, b in fa]
    try:
        h2h = _h2h(l["home"], l["away"], l["kickoff"])
    except Exception:  # noqa: BLE001
        h2h = []
    fhits, fn = _rate(l, form_games)
    hhits, hn = _rate(l, h2h)
    if fn + hn < 4:
        return None
    parts, weights = [], []
    if fn:
        parts.append(fhits / fn)
        weights.append(W_FORM)
    if hn >= 3:
        parts.append(hhits / hn)
        weights.append(W_H2H)
    rate = sum(p * w for p, w in zip(parts, weights)) / sum(weights)
    goals_h2h = round(sum(a + b for a, b in h2h) / len(h2h), 1) if h2h else None
    verdict = "contra" if rate < CONTRA and fn + hn >= 6 else "debil" if rate < WEAK else "ok"
    return {"form": [fhits, fn], "h2h": [hhits, hn], "rate": round(rate, 3), "verdict": verdict,
            "h2h_goals": goals_h2h, "h2h_n": len(h2h)}


def blend(market_p: float, ev: dict | None) -> float:
    """Probabilidad final: 65 % mercado + 35 % datos (si hay datos suficientes)."""
    if not ev:
        return market_p
    n = ev["form"][1] + ev["h2h"][1]
    w = 0.35 if n >= 8 else 0.2
    return round((1 - w) * market_p + w * ev["rate"], 4)


def line(ev: dict | None) -> str:
    """Texto corto para el dueño: «📚 Datos: forma 3/10 · H2H 0/6 → ⚠️ los datos no acompañan»."""
    if not ev:
        return "📚 Datos: sin historial suficiente para contrastar."
    bits = []
    if ev["form"][1]:
        bits.append(f"forma reciente {ev['form'][0]}/{ev['form'][1]}")
    if ev["h2h"][1]:
        bits.append(f"cara a cara {ev['h2h'][0]}/{ev['h2h'][1]}"
                    + (f" ({str(ev['h2h_goals']).replace('.', ',')} goles por partido)" if ev.get("h2h_goals") is not None else ""))
    tag = {"ok": "✅ los datos acompañan", "debil": "🟡 los datos acompañan a medias",
           "contra": "⚠️ los datos lo contradicen"}[ev["verdict"]]
    return f"📚 Datos: {' · '.join(bits)} → {tag}"
