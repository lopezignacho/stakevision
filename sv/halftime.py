"""Publicación de entretiempo de nuestros picks: marcador, goles, estadísticas y cómo va la apuesta."""
from __future__ import annotations

import math

from . import formatting

STATS = [("possessionPct", "Posesión", "%"), ("totalShots", "Remates", ""), ("shotsOnTarget", "Al arco", ""),
         ("wonCorners", "Córners", "")]


def _num(v) -> float:
    try:
        return float(str(v).replace("%", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def stats(rep: dict) -> list[tuple[str, float, float, str]]:
    out = []
    for key, label, unit in STATS:
        h, a = rep["home"].get("stats", {}).get(key), rep["away"].get("stats", {}).get(key)
        if h is None and a is None:
            continue
        out.append((label, _num(h), _num(a), unit))
    return out


def is_halftime(rep: dict) -> bool:
    if rep.get("status_name") == "STATUS_HALFTIME":
        return True
    # si justo no lo pillamos en el descanso: primeros minutos del 2º tiempo
    clock = rep.get("clock") or ""
    mins = int(clock.split(":")[0]) if clock[:1].isdigit() else 99
    return rep.get("state") == "in" and rep.get("period") == 2 and mins <= 52


LOCKED_W = ["¡VERDE ASEGURADO! 🔒", "¡VERDAZO AL DESCANSO! 💚", "¡YA ESTÁ COBRADA! ✅"]


def locked(l: dict, h: int, a: int) -> tuple[str, str] | None:
    """¿El pick ya quedó decidido, pase lo que pase en el 2º tiempo? Los goles no se borran:
    un «más de» ya superado es verde seguro; un «menos de» ya superado es roja segura.
    Devuelve (W|L, por qué) o None si todavía puede cambiar."""
    t, o, line = l.get("mtype", ""), str(l.get("outcome", "")).lower(), l.get("handicap")
    over, yes = o.startswith(("más", "mas", "over")), o.startswith(("s", "y"))
    gl = lambda n: f"{n} gol{'es' if n != 1 else ''}"  # noqa: E731
    if t in ("totals", "teamtotals-team1", "teamtotals-team2") and line is not None:
        line = float(line)
        if t == "totals":
            g, who = h + a, None
        else:
            g, who = (h, l["home"]) if t.endswith("1") else (a, l["away"])
        need = math.floor(line) + 1
        if g > line:
            if over:
                return "W", ((f"{formatting.team(who)} ya marcó {g} y necesitábamos {need}" if who
                              else f"Ya van {gl(g)} y necesitábamos {need}") + ": pase lo que pase, este pick ya se cobró.")
            return "L", (f"{formatting.team(who)} ya marcó {g}" if who else f"Ya van {gl(g)}") + ": se pasó la línea."
        return None
    if t == "bothteamsscore" and h > 0 and a > 0:
        return ("W", "Ya marcaron los dos: pase lo que pase, este pick ya se cobró.") if yes else \
               ("L", "Ya marcaron los dos.")
    if t in ("toscore-team1", "toscore-team2"):
        g, who = (h, l["home"]) if t.endswith("1") else (a, l["away"])
        if g > 0:
            return ("W", f"{formatting.team(who)} ya marcó: pase lo que pase, este pick ya se cobró.") if yes else \
                   ("L", f"{formatting.team(who)} ya marcó.")
    return None


def status(l: dict, h: int, a: int, grade, seed: str = "") -> tuple[str, str]:
    """(estado W/L/V si terminara así, frase de cómo va el pick). Si ya está decidido, lo dice claro."""
    lk = locked(l, h, a)
    if lk:
        res, why = lk
        if res == "W":
            head = LOCKED_W[sum(map(ord, seed or "x")) % len(LOCKED_W)]
            return "W", f"✅ {head} · {why}"
        return "L", f"❌ Esta ya no se da · {why}"
    res = grade(l, h, a) or "?"
    t, o, line = l.get("mtype", ""), str(l.get("outcome", "")).lower(), l.get("handicap")
    total = h + a
    extra = ""
    if t == "totals" and line is not None:
        line = float(line)
        if o.startswith(("más", "mas")):
            need = math.floor(line) + 1 - total
            extra = (f"Falta{'n' if need > 1 else ''} {need} gol{'es' if need > 1 else ''} en el 2º tiempo."
                     if need > 0 else "¡Ya está cumplido! 🔒")
            if need > 0:
                res = "?"
        else:
            room = math.ceil(line) - 1 - total
            extra = (f"Pueden caer hasta {room} gol{'es' if room != 1 else ''} más." if room > 0
                     else "No puede caer ni un gol más." if room == 0 else "Ya se pasó la línea.")
    elif t == "bothteamsscore":
        yes = o.startswith(("s", "y"))
        missing = [n for n, g in ((l["home"], h), (l["away"], a)) if g == 0]
        if yes:
            extra = "¡Ya marcaron los dos! 🔒" if not missing else "Falta que marque " + " y ".join(missing) + "."
            if missing:
                res = "?"
        else:
            extra = "Hasta ahora, uno de los dos sigue en cero." if missing else "Ya marcaron los dos."
    head = {"W": "✅ Si terminara así: VERDE", "L": "❌ Por ahora no se da", "V": "↩️ Por ahora sería nula"}.get(
        res, "⏳ En camino")
    return res, head + (f" · {extra}" if extra else "")


def caption(p: dict, rep: dict, st: tuple[str, str]) -> str:
    esc = formatting.escape
    h, a = rep["home"], rep["away"]
    sh = lambda t: (t.get("short") or t.get("name") or "").strip()  # noqa: E731
    lines = [f"⏸️ <b>ENTRETIEMPO</b> · {esc(sh(h))} {h['score']}-{a['score']} {esc(sh(a))}", ""]
    for g in rep["goals"]:
        extra = " (penal)" if g["kind"] == "penalty" else " (en contra)" if g["kind"] == "own" else ""
        lines.append(f"⚽ {esc(g['label'])} {esc(g['player'])}{extra} · {esc(sh(rep[g['side']]))}")
    for r in rep.get("reds") or []:
        lines.append(f"🟥 {esc(r['label'])} {esc(r['player'])} · {esc(sh(rep[r['side']]))}")
    if not rep["goals"]:
        lines.append("Todavía sin goles.")
    sts = stats(rep)
    if sts:
        lines.append("")
        for label, hv, av, unit in sts:
            fmt = (lambda v: f"{v:.0f}{unit}")
            lines.append(f"📊 {label}: {fmt(hv)} - {fmt(av)}")
    sel = formatting.public_label(p["legs"][0])
    lk = locked(p["legs"][0], h["score"], a["score"])
    if lk and lk[0] == "W":   # ya ganado: se celebra, sin «si terminara así»
        head, _, why = st[1].partition(" · ")
        lines += ["", f"🎯 Nuestro pick: <b>{esc(sel)}</b> @ {formatting.odds(p['price'])}",
                  f"<b>{esc(head)}</b>", esc(why), "", "Ahora, a disfrutar el 2º tiempo 🍿", "🔞 +18 · Juega con responsabilidad."]
    else:
        lines += ["", f"🎯 Nuestro pick: <b>{esc(sel)}</b> @ {formatting.odds(p['price'])}", esc(st[1]),
                  "", "Se viene el 2º tiempo 👀", "🔞 +18 · Juega con responsabilidad."]
    return "\n".join(lines)
