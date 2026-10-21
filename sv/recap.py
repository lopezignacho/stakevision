"""Post partido de nuestros picks: imagen estilo revista + textos para Telegram e Instagram.

Datos: marcador, goles, colores y global desde ESPN. Foto: Wikimedia Commons con licencia libre
(si no hay, la imagen sale sin foto). Escudos: propios, con los colores del club (no los oficiales).
"""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config, formatting

STAGE = {"final": ("FINAL", "es campeón"), "semifinals": ("SEMIFINAL", "es finalista"),
         "quarterfinals": ("CUARTOS DE FINAL", "pasa a semifinales"), "round-of-16": ("OCTAVOS DE FINAL", "pasa a cuartos"),
         "round-of-32": ("16AVOS DE FINAL", "pasa a octavos"), "knockout-round-playoffs": ("PLAYOFFS", "avanza")}
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def image_path(pid: str) -> str:
    return os.path.join(config.ROOT, "docs", "ig", f"pick-res-{pid}.jpg")


def _winner(rep: dict) -> str:
    h, a = rep["home"]["score"], rep["away"]["score"]
    return "home" if h > a else "away" if a > h else ""


def _series_winner(rep: dict) -> str:
    ha, aa = rep["home"].get("agg"), rep["away"].get("agg")
    if not rep.get("series") or not rep["series"].get("done") or ha is None or aa is None:
        return ""
    if ha == aa:   # definido por penales u otro criterio: ESPN marca el ganador
        return "home" if rep["home"].get("winner") else "away" if rep["away"].get("winner") else ""
    return "home" if ha > aa else "away"


def headline(rep: dict) -> str:
    """Titular automático según cómo se dio el partido (tú lo puedes cambiar con /titular)."""
    w = _winner(rep)
    sw = _series_winner(rep)
    slug = rep.get("stage") or ""
    if sw and slug == "final":
        return "SON CAMPEONES"
    if sw and w == sw:
        before = {s: (rep[s].get("agg") or 0) - rep[s]["score"] for s in ("home", "away")}
        loser = "away" if sw == "home" else "home"
        if before[sw] < before[loser]:
            return "REMONTADA"
    run, trailed, decisive = {"home": 0, "away": 0}, False, None
    for g in rep["goals"]:
        run[g["side"]] += 1
        if w:
            other = "away" if w == "home" else "home"
            if run[w] < run[other]:
                trailed = True
            if run[w] > run[other] and decisive is None:
                decisive = g
            if run[w] <= run[other]:
                decisive = None
    if w:
        diff = abs(rep["home"]["score"] - rep["away"]["score"])
        if trailed:
            return "REMONTADA"
        if diff >= 3:
            return "GOLEADA"
        if decisive and decisive["min"] >= 85:
            return "AGÓNICO"
        if w == "away":
            return "GOLPE DE VISITA"
        if rep["away"]["score"] == 0:
            return "IMPECABLE"
        return "VICTORIA"
    if rep["home"]["score"] == 0:
        return "CERO A CERO"
    if rep["goals"] and rep["goals"][-1]["min"] >= 85:
        return "AGÓNICO"
    return "TODO IGUAL"


def hero(rep: dict) -> dict | None:
    """Protagonista: el que más goles hizo para el ganador (si empatan, el del gol más tardío)."""
    w = _winner(rep)
    gs = [g for g in rep["goals"] if g["kind"] != "own" and (not w or g["side"] == w)]
    if not gs:
        return None
    count: dict[str, int] = {}
    for g in gs:
        count[g["full"]] = count.get(g["full"], 0) + 1
    best = max(gs, key=lambda g: (count[g["full"]], g["min"]))
    return best


def _team(t: dict) -> str:
    return (t.get("short") or t.get("name") or "").strip()


def eyebrow(rep: dict, league: str) -> str:
    name = (league or "").split("·")[-1].strip()
    st = STAGE.get(rep.get("stage") or "")
    return f"{name} · {st[0]}" if st and name else name or (st[0] if st else "")


def subline(rep: dict, kickoff_iso: str) -> tuple[str, str]:
    s = rep.get("series")
    ha, aa = rep["home"].get("agg"), rep["away"].get("agg")
    if s and ha is not None and aa is not None:
        if s.get("done"):
            sw = _series_winner(rep)
            phrase = (STAGE.get(rep.get("stage") or "") or ("", "avanza"))[1]
            return "Global", f"{ha}-{aa} · {_team(rep[sw])} {phrase}" if sw else f"{ha}-{aa}"
        return "Ida", "· la serie se define en la vuelta"
    try:
        k = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00")).astimezone(ZoneInfo(config.TIMEZONE))
        date = f"{k.day} {MESES[k.month - 1]}"
    except ValueError:
        date = ""
    return (rep.get("venue") or ""), (f"· {date}" if rep.get("venue") and date else date)


def pick_label(p: dict) -> str:
    if len(p["legs"]) > 1:
        return f"Combinada x{len(p['legs'])}"
    sel = formatting.outcome_label(p["legs"][0])
    return sel[:sel.index(" (")] if " (" in sel else sel


def build(p: dict, rep: dict, photo: tuple[bytes, dict] | None, title: str | None = None) -> dict:
    """Datos para postimage.render_recap y los textos que acompañan la imagen."""
    l = p["legs"][0]
    title = (title or headline(rep)).upper()
    data = {"report": rep, "eyebrow": eyebrow(rep, l.get("league") or ""), "headline": title,
            "subline": subline(rep, l["kickoff"]),
            "pick": {"label": pick_label(p), "odds": formatting.odds(p["price"]), "result": p.get("result") or "V"},
            "photo": photo[0] if photo else None, "credit": photo[1]["text"] if photo and photo[1] else None}
    return data


RESULT_TXT = {"W": "✅ VERDE", "L": "❌ ROJA", "V": "↩️ NULA"}


def _goal_lines(rep: dict) -> list[str]:
    out = []
    for g in rep["goals"]:
        extra = " (penal)" if g["kind"] == "penalty" else " (en contra)" if g["kind"] == "own" else ""
        out.append(f"⚽ {g['label']} {g['player']}{extra} · {_team(rep[g['side']])}")
    return out


def telegram_caption(p: dict, rep: dict, title: str) -> str:
    esc = formatting.escape
    h, a = rep["home"], rep["away"]
    lines = [f"📰 <b>{esc(title.replace('-', ''))}</b>",
             f"<b>{esc(_team(h))} {h['score']}-{a['score']} {esc(_team(a))}</b>", ""]
    lines += [esc(x) for x in _goal_lines(rep)] or ["Sin goles."]
    sub = subline(rep, p["legs"][0]["kickoff"])
    if sub[0] in ("Global", "Ida"):
        lines += ["", esc(" ".join(sub))]
    lines += ["", f"🎯 Nuestro pick: {esc(pick_label(p))} @ {formatting.odds(p['price'])} → "
                  f"<b>{RESULT_TXT.get(p.get('result'), '')}</b>",
              "🔞 +18 · Juega con responsabilidad."]
    return "\n".join(lines)


def instagram_caption(p: dict, rep: dict, title: str, credit: dict | None) -> str:
    h, a = rep["home"], rep["away"]
    lines = [f"🔥 {title.replace('-', '')} 🔥", f"{_team(h)} {h['score']}-{a['score']} {_team(a)}", ""]
    lines += _goal_lines(rep) or ["Sin goles."]
    sub = subline(rep, p["legs"][0]["kickoff"])
    if sub[0] in ("Global", "Ida"):
        lines += ["", " ".join(sub)]
    lines += ["", f"🎯 Nuestro pick: {pick_label(p)} @ {formatting.odds(p['price'])} → {RESULT_TXT.get(p.get('result'), '')}",
              "", "📲 Pick gratis todos los días en nuestro canal de Telegram (link en la bio)."]
    if credit:
        lines += ["", f"📸 Foto: {credit['author']} / Wikimedia Commons ({credit['license']}), modificada. "
                      f"Esta imagen se comparte bajo la misma licencia."]
    lines += ["🔞 +18 · Juega con responsabilidad. Apostar implica riesgo de pérdida.", ""]
    tags = ["#Stakevision", "#Futbol"]
    for t in (formatting._tag((p["legs"][0].get("league") or "").split("·")[-1]),
              formatting._tag(_team(h)), formatting._tag(_team(a))):
        if t and t not in tags:
            tags.append(t)
    lines.append(" ".join(tags))
    return "\n".join(lines)
