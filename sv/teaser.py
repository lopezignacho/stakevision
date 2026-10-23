"""Adelanto del pick (historia en modo día) y versión del pick con foto real (estilo revista).

El adelanto da pistas sin revelar el partido: zona de la liga, hora, un dato real de forma
y la cuota aproximada. El pick queda tapado con un candado hasta la hora de revelación.
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config, formatting

AMERICA = ("argentina", "brasil", "brazil", "chile", "colombia", "uruguay", "paraguay", "peru", "perú", "ecuador",
           "bolivia", "venezuela", "mexico", "méxico", "estados unidos", "usa", "mls", "costa rica", "honduras",
           "guatemala", "panama", "panamá", "el salvador", "canada", "canadá")
SUDAMERICA_COPAS = ("libertadores", "sudamericana", "conmebol")
EURO_COPAS = ("champions", "europa league", "conference", "uefa")
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _local(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ZoneInfo(config.TIMEZONE))


def _zone(league: str) -> tuple[str, str]:
    low = (league or "").lower()
    if any(w in low for w in SUDAMERICA_COPAS):
        return "Copa internacional de ", "Sudamérica"
    if any(w in low for w in EURO_COPAS):
        return "Copa internacional de ", "Europa"
    country = low.split("·")[0].strip()
    return "Primera División de ", "América" if any(country.startswith(c) for c in AMERICA) else "Europa"


def _form_clue(l: dict) -> tuple[str, str, str]:
    ctx = l.get("context") or {}
    best = None
    for ms in (ctx.get("home") or [], ctx.get("away") or []):
        if len(ms) < 3:
            continue
        res = ["G" if m["gf"] > m["ga"] else "E" if m["gf"] == m["ga"] else "P" for m in ms]
        w = next((i for i, r in enumerate(res) if r != "G"), len(res))
        nl = next((i for i, r in enumerate(res) if r == "P"), len(res))
        gf = sum(m["gf"] for m in ms[:6]) / len(ms[:6])
        for score, clue in ((w * 10, ("Uno de los equipos ganó sus ", f"últimos {w}", "")) if w >= 3 else (0, None),
                            (nl * 5, ("Uno de los equipos lleva ", f"{nl} sin perder", "")) if nl >= 4 else (0, None),
                            (gf * 8, ("Uno de los equipos promedia ", f"{formatting._n(gf)} goles", " por partido"))
                            if gf >= 2 else (0, None)):
            if clue and (best is None or score > best[0]):
                best = (score, clue)
    if best:
        return best[1]
    edge = l.get("edge") or 0
    return ("Nuestro modelo ve ", f"+{formatting.pct(edge)} de valor", " en la cuota") if edge > 0 else \
        ("Partido con ", "valor detectado", " por el modelo")


def teaser_data(p: dict, reveal: str | None, vip: bool = False) -> dict:
    """Datos para postimage.render_teaser. reveal: 'HH:MM' o None."""
    l = p["legs"][0]
    ko = _local(l["kickoff"])
    today = datetime.now(ZoneInfo(config.TIMEZONE)).date()
    day = "HOY" if ko.date() == today else "MAÑANA" if (ko.date() - today).days == 1 else f"EL {DIAS[ko.weekday()].upper()}"
    z1, z2 = _zone(l.get("league") or "")
    when = f"{ko:%H:%M}" + ("" if day in ("HOY", "MAÑANA") else f" del {ko.day} {MESES[ko.month - 1]}")
    clues = [(z1, z2, ""), ("Se juega a las ", when, " (hora Chile)"), _form_clue(l),
             ("Cuota cercana a ", f"{round(p['price'], 1):.1f}", "")]
    reveal_day = day.capitalize() if day in ("HOY", "MAÑANA") else "Muy pronto"
    cta2 = (f"{reveal_day} a las {reveal} lo revelamos en Telegram" if reveal
            else f"{reveal_day} lo revelamos en Telegram" if day in ("HOY", "MAÑANA") else "Lo revelamos en Telegram")
    return {"pill": "ADELANTO · PICK VIP" if vip else "ADELANTO · PICK GRATIS",
            "line1": day, "line2": "SE REVELA", "clues": clues, "lock": reveal or "PRONTO",
            "cta": ("¿Adivinas el partido?", cta2)}


def parse_reveal(text: str) -> str | None:
    m = re.search(r"\b([01]?\d|2[0-3])[:.h]([0-5]\d)\b", text or "")
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


# ---------------------------------------------------------------- pick con foto (estilo revista)
def _plain(html: str) -> str:
    import html as _h
    return _h.unescape(re.sub(r"<[^>]+>", "", html or "")).strip()


def _compact_form(team: str, ms: list[dict]) -> str:
    if len(ms) < 3:
        return ""
    last = ms[:6]
    g = sum(m["gf"] > m["ga"] for m in last)
    e = sum(m["gf"] == m["ga"] for m in last)
    pp = len(last) - g - e
    streak = formatting._streak_phrase(ms)
    return f"{team}: " + (f"{streak}, " if streak else "") + f"{g}G {e}E {pp}P en sus últimos {len(last)}"


def pick_photo_data(p: dict, teams: dict | None, photo: tuple[bytes, dict | None] | None) -> dict:
    l = p["legs"][0]
    ko = _local(l["kickoff"])
    league = (l.get("league") or "").split("·")[-1].strip()
    eyebrow = f"{league} · {DIAS[ko.weekday()]} {ko.day} {MESES[ko.month - 1]} · {ko:%H:%M}".strip(" ·")
    if not teams:
        teams = {"home": {"name": l["home"], "short": l["home"], "abbr": l["home"][:3].upper()},
                 "away": {"name": l["away"], "short": l["away"], "abbr": l["away"][:3].upper()}}
    ctx = l.get("context") or {}
    lines = [x for x in (_compact_form(l["home"], ctx.get("home") or []),
                         _compact_form(l["away"], ctx.get("away") or [])) if x]
    if ctx.get("v") == 2 and len(ctx.get("home") or []) >= 3 and len(ctx.get("away") or []) >= 3:
        ml = _plain(formatting._market_line(l, ctx["home"], ctx["away"]))
        if ml:
            lines.append(ml)
    if not lines:
        lines = [f"Cuota justa estimada {formatting.odds(l['fair_odds'])} contra {formatting.odds(l['price'])} disponible."]
    sel = formatting.outcome_label(l)
    return {"eyebrow": eyebrow, "headline": ("PICK VIP" if (l.get("sport") or "soccer") == "basketball"
                                 else "PICK GRATIS" if p.get("free") else "PICK DEL DÍA"),
            "teams": teams, "selection": sel[:sel.index(" (")] if " (" in sel else sel,
            "odds": formatting.odds(p["price"]), "stake": p.get("stake"), "lines": lines[:3],
            "photo": photo[0] if photo else None, "credit": photo[1]["text"] if photo and photo[1] else None}
