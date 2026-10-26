"""Mensaje de una roja: corto, directo y sin imagen.

Una línea con lo que pasó en el partido (solo con datos reales: marcador y, si ESPN los tiene,
remates al arco), el pick que se perdió y un cierre sobrio. Las frases cambian de un partido a
otro para no repetir siempre el mismo texto.
"""
from __future__ import annotations

from . import formatting

CLOSERS = [
    "Se pierde, se anota y seguimos con la misma disciplina.",
    "Queda en el historial como todas, y mañana seguimos con el mismo método.",
    "Es parte del juego: se registra y seguimos.",
    "Se anota en el historial y seguimos con la misma gestión de stake.",
    "No siempre sale. Seguimos con la misma disciplina.",
]
INTROS = [
    "🎯 Esta vez no se nos dio: {pick} ❌.",
    "🎯 No entró: {pick} ❌.",
    "🎯 Nuestro pick, {pick}, se pierde ❌.",
    "🎯 Roja para {pick} ❌.",
]


def _pick_one(options: list[str], seed: str) -> str:
    return options[sum(map(ord, seed or "x")) % len(options)]


def _int(v) -> int | None:
    try:
        return int(float(str(v).replace("%", "")))
    except (TypeError, ValueError):
        return None


def _shots(rep: dict | None, side: str) -> int | None:
    if not rep:
        return None
    return _int(((rep.get(side) or {}).get("stats") or {}).get("shotsOnTarget"))


def _goles(n: int) -> str:
    return "ningún gol" if n == 0 else "1 gol" if n == 1 else f"{n} goles"


def context_line(l: dict, rep: dict | None, seed: str) -> str:
    """Qué pasó, en una frase. Vacío si no hay datos para decir algo concreto."""
    sc = l.get("score")
    if not sc or (l.get("sport") or "soccer") != "soccer":
        return ""
    h, a = int(sc[0]), int(sc[1])
    total, home, away = h + a, l["home"], l["away"]
    t, o = l.get("mtype") or "", str(l.get("outcome") or "").lower()
    line = l.get("handicap")
    sot = [x for x in (_shots(rep, "home"), _shots(rep, "away")) if x is not None]
    sot_total = sum(sot) if len(sot) == 2 else None
    esc = formatting.escape
    if t == "totals" and line is not None:
        over = o.startswith(("más", "mas", "over"))
        if over:
            if sot_total and sot_total >= 8:
                return _pick_one([f"Hubo {sot_total} remates al arco, pero solo entraron {_goles(total)}.",
                                  f"Llegadas hubo ({sot_total} remates al arco), pero el balón no quiso entrar: {_goles(total)}."], seed)
            if total == int(float(line)):
                return f"Se quedó a un gol de la línea: terminó con {_goles(total)}."
            return _pick_one([f"Partido cerrado: apenas {_goles(total)}.",
                              f"Faltaron goles: terminó con {_goles(total)}."], seed)
        return _pick_one([f"El partido se abrió más de lo esperado: {_goles(total)}.",
                          f"Se rompió el partido y terminó con {_goles(total)}."], seed)
    if t in ("1x2", "drawnobet", "spreads") and o in ("1", "2"):
        mine, theirs = (home, h - a) if o == "1" else (away, a - h)
        side = "home" if o == "1" else "away"
        shots = _shots(rep, side)
        if theirs > 0:   # ganó, pero no por lo que pedía el hándicap
            return f"{esc(mine)} ganó, pero no por la diferencia que necesitábamos."
        if theirs == 0:
            return (f"{esc(mine)} remató {shots} veces al arco, pero no pasó del empate." if shots and shots >= 5
                    else f"{esc(mine)} no pudo pasar del empate.")
        return (f"{esc(mine)} lo intentó con {shots} remates al arco, pero no alcanzó." if shots and shots >= 5
                else f"No fue el día de {esc(mine)}.")
    if t == "bothteamsscore":
        return ("Uno de los dos no encontró el gol." if o.startswith(("s", "y"))
                else "Los dos encontraron el gol.")
    if t in ("teamtotals-team1", "teamtotals-team2") and line is not None:
        team, n = (home, h) if t.endswith("1") else (away, a)
        over = o.startswith(("más", "mas", "over"))
        return (f"{esc(team)} marcó {_goles(n)}: no le alcanzó." if over
                else f"{esc(team)} marcó más de lo esperado: {_goles(n)}.")
    return ""


def message(p: dict, rep: dict | None = None) -> str:
    """Texto de la roja para los canales."""
    esc = formatting.escape
    seed = str(p.get("id") or "")
    if p.get("kind") == "builder":
        pick = "nuestro Bet Builder @ " + formatting.odds(p["price"])
    else:
        pick = esc(" + ".join(formatting.public_label(l) for l in p["legs"])) + f" @ {formatting.odds(p['price'])}"
    head = []
    for l in p["legs"]:
        sc = l.get("score")
        emoji = "🏀" if l.get("sport") == "basketball" else "⚽"
        head.append(f"{emoji} <b>{esc(l['home'])} {sc[0]}-{sc[1]} {esc(l['away'])}</b>" if sc
                    else f"{emoji} <b>{esc(l['home'])} vs {esc(l['away'])}</b>")
    ctx = context_line(p["legs"][0], rep, seed) if len(p["legs"]) == 1 else ""
    lines = head + [""]
    if ctx:
        lines.append(ctx)
    lines.append(_pick_one(INTROS, seed).format(pick=pick) + " " + _pick_one(CLOSERS, seed + "c"))
    lines += ["", "🔞 +18 · Juega con responsabilidad."]
    return "\n".join(lines)
