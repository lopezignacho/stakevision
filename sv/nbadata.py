"""NBA: contraste con datos, igual que en el fútbol.

- ¿En cuántos de los últimos 10 partidos de cada equipo se habría cumplido el pick? (hándicap, ganador, totales)
- Bajas que importan: solo jugadores que vienen jugando y pesan (≥ 24 min o ≥ 12 pts de media en sus últimos 5).
  Una baja larga no es noticia: el equipo ya juega sin él.
- Probabilidad publicada = 65 % casas + 35 % datos (como en el fútbol). Si los datos van claramente en contra,
  el pronóstico no se sugiere (el Bet Builder sí llega).
"""
from __future__ import annotations

import math
import traceback
from datetime import datetime

CONTRA = 0.35


def _side(l: dict) -> str | None:
    t, o = l.get("mtype", ""), str(l.get("outcome", "")).lower()
    if t == "teamtotals-team1":
        return "home"
    if t == "teamtotals-team2":
        return "away"
    return {"1": "home", "2": "away"}.get(o)


def _line_for_team(l: dict) -> float | None:
    """Hándicap visto desde el equipo elegido (+9.5 = puede perder por 9)."""
    h = l.get("handicap")
    if h is None:
        return None
    return float(h) if str(l.get("outcome")) == "1" else -float(h)


def hit_fns(l: dict):
    """(¿se cumple en un partido del equipo elegido?, ¿y en uno del rival?) con g = {pf, pa}. None si no aplica."""
    t, o = l.get("mtype", ""), str(l.get("outcome", "")).lower()
    line = l.get("handicap")
    over = o.startswith(("más", "mas", "over"))
    if t == "moneyline":
        return (lambda g: g["pf"] > g["pa"]), (lambda g: g["pf"] < g["pa"])
    if t == "spreads" and line is not None:
        hh = _line_for_team(l)
        return (lambda g: g["pf"] - g["pa"] + hh > 0), (lambda g: g["pa"] - g["pf"] + hh > 0)
    if t == "totals" and line is not None:
        f = lambda g: (g["pf"] + g["pa"] > float(line)) == over  # noqa: E731
        return f, f
    if t in ("teamtotals-team1", "teamtotals-team2") and line is not None:
        return (lambda g: (g["pf"] > float(line)) == over), (lambda g: (g["pa"] > float(line)) == over)
    return None


def check(l: dict, ctx: dict | None) -> dict | None:
    """Tasa de cumplimiento en los últimos 10 de cada equipo + veredicto."""
    if not ctx:
        return None
    fns = hit_fns(l)
    if not fns:
        return None
    side = _side(l) or "home"
    me, op = (ctx["home"], ctx["away"]) if side == "home" else (ctx["away"], ctx["home"])
    gm, go = me.get("games")[:10], op.get("games")[:10]
    km, ko = sum(map(fns[0], gm)), sum(map(fns[1], go))
    n = len(gm) + len(go)
    if n < 8:
        return None
    rate = (km + ko) / n
    return {"me": [km, len(gm)], "op": [ko, len(go)], "rate": round(rate, 3),
            "verdict": "contra" if rate < CONTRA else "debil" if rate < 0.5 else "ok"}


def blend(p: float, ev: dict | None) -> float:
    return p if not ev else round(0.65 * p + 0.35 * ev["rate"], 4)


def key_absences(ctx: dict | None, kickoff_iso: str) -> None:
    """Marca en ctx[lado]['key_out'] las bajas que pesan (con sus puntos por partido)."""
    if not ctx:
        return
    from . import builder
    before = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00"))
    for side in ("home", "away"):
        t = ctx.get(side) or {}
        outs = [i for i in t.get("injuries") or [] if (i.get("status") or "").lower() in ("out", "doubtful")]
        t["key_out"] = []
        if not outs or not t.get("id"):
            continue
        try:
            logs = builder._nba_logs(t["id"], before, 5)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            continue
        agg: dict[str, list] = {}
        for g in logs:
            for r in g.values():
                agg.setdefault(r["name"].lower(), []).append(r)
        for i in outs:
            rows = agg.get(i["name"].lower()) or []
            if len(rows) < 2:
                continue   # no viene jugando: su baja no cambia nada
            mins = sum(r["min"] for r in rows) / len(rows)
            pts = sum(r["pts"] for r in rows) / len(rows)
            if mins >= 24 or pts >= 12:
                t["key_out"].append({"name": i["name"], "pts": round(pts, 1), "min": round(mins)})


def need_txt(x: float) -> int:
    return int(math.ceil(abs(x)))
