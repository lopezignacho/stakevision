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
            "pick": None if p.get("news") else
            {"label": pick_label(p), "odds": formatting.odds(p["price"]), "result": p.get("result") or "V"},
            "dato": dato(rep),
            "photo": photo[0] if photo else None, "credit": photo[1]["text"] if photo and photo[1] else None}
    return data


def dato(rep: dict) -> str:
    """Una línea de contexto para los partidos que no fueron pick."""
    w = _winner(rep)
    sw = _series_winner(rep)
    total = rep["home"]["score"] + rep["away"]["score"]
    if sw and w == sw:
        loser = "away" if sw == "home" else "home"
        wb = (rep[sw].get("agg") or 0) - rep[sw]["score"]
        lb = (rep[loser].get("agg") or 0) - rep[loser]["score"]
        if wb < lb:
            return f"{_team(rep[sw])} dio vuelta el {wb}-{lb} de la ida"
    run, trailed = {"home": 0, "away": 0}, False
    for g in rep["goals"]:
        run[g["side"]] += 1
        if w and run[w] < run["away" if w == "home" else "home"]:
            trailed = True
    if w and trailed:
        return f"{_team(rep[w])} lo dio vuelta después de ir perdiendo"
    if total >= 5:
        return f"{total} goles en un partidazo"
    if rep["goals"] and rep["goals"][-1]["min"] >= 85:
        return f"Se definió en el minuto {rep['goals'][-1]['label']}"
    if total == 0:
        return "Ninguno pudo romper el cero"
    return f"Triunfo de {_team(rep[w])}" if w else "Reparto de puntos"


RESULT_TXT = {"W": "✅ VERDE", "L": "❌ ROJA", "V": "↩️ NULA"}

OPENERS = {
    "REMONTADA": ["¡QUÉ NOCHE! 🔥 Nadie lo daba por hecho y lo dieron vuelta.",
                  "¡LO DIERON VUELTA! 🔄🔥 Esto es fútbol en estado puro.",
                  "¡REMONTADA DE LAS QUE SE CUENTAN! 🔥 Corazón, garra y cabeza fría."],
    "GOLEADA": ["¡BAILE TOTAL! 💃⚽ Un partido para guardar.", "¡FESTIVAL DE GOLES! 🎉 No hubo equivalencias."],
    "AGÓNICO": ["¡INFARTO HASTA EL ÚLTIMO SEGUNDO! 😱", "¡SE DEFINIÓ CON EL CORAZÓN EN LA BOCA! ⏱️🔥"],
    "GOLPE DE VISITA": ["¡GOLPE EN CASA AJENA! 👊 Fueron a ganar y lo hicieron.",
                        "¡SILENCIO EN LAS TRIBUNAS! 🤫 Ganó la visita."],
    "IMPECABLE": ["¡SÓLIDO DE PRINCIPIO A FIN! 🧱 Ganó y no le hicieron goles.",
                  "¡PARTIDO REDONDO! 💯 Triunfo y valla invicta."],
    "VICTORIA": ["¡TRIUNFAZO! 💪 Tres puntos que valen oro.", "¡HICIERON LA TAREA! ✅ Triunfo trabajado."],
    "CERO A CERO": ["Partido trabado y de dientes apretados 🔒 Ninguno pudo romper el cero."],
    "TODO IGUAL": ["¡Se repartieron todo! ⚖️ Nadie se quiso ir con las manos vacías."],
    "SON CAMPEONES": ["¡CAMPEONES! 🏆🏆🏆 Noche histórica."],
}
QUESTIONS = {
    "REMONTADA": ["¿Dónde estabas cuando cayó el gol del triunfo? 👇", "¿La mejor remontada del año? Te leemos 👇"],
    "GOLEADA": ["¿Merecido o se les pasó la mano? 👇"],
    "AGÓNICO": ["¿Cuántos se comieron las uñas con este final? 🙋 👇"],
    "GOLPE DE VISITA": ["¿Lo viste venir o te sorprendió? 👇"],
    "CERO A CERO": ["¿Quién mereció más? 👇"],
    "TODO IGUAL": ["¿Justo el empate? 👇"],
}
DEFAULT_Q = ["¿Quién fue la figura para ti? 👇", "¿Qué te pareció el partido? Te leemos 👇"]


def _pick_one(options: list[str], seed: str) -> str:
    return options[sum(map(ord, seed or "x")) % len(options)]


def _how(g: dict) -> str:
    return " de cabeza" if g["kind"] == "header" else " de penal" if g["kind"] == "penalty" else ""


def _surname(g: dict) -> str:
    n = g.get("player") or g.get("full") or ""
    return n.split(". ", 1)[-1] if ". " in n else n


def story(rep: dict) -> list[str]:
    """Cuenta el partido en 2 a 4 frases a partir de los goles (sin inventar nada que no esté en los datos)."""
    goals = rep["goals"]
    if not goals:
        return [f"{_team(rep['home'])} y {_team(rep['away'])} chocaron de principio a fin, "
                "pero el arco quedó cerrado."]
    run = {"home": 0, "away": 0}
    lines, prev_kind = [], ""
    for i, g in enumerate(goals):
        side, other = g["side"], "away" if g["side"] == "home" else "home"
        before = run[side] - run[other]
        run[side] += 1
        team, who, m = _team(rep[side]), _surname(g), g["label"]
        if g["kind"] == "own":
            text, kind = f"un gol en contra a los {m} le dio vida a {team}", "own"
        elif i == 0:
            text, kind = f"{who} abrió el marcador{_how(g)} a los {m} y encendió todo para {team}", "open"
        elif before == -1:
            text, kind = f"{who} lo empató{_how(g)} a los {m} y volvió a meter a {team} en el partido", "tie"
        elif before == 0:
            last = g is goals[-1]
            text = (f"{who} apareció a los {m}{_how(g)} para poner a {team} arriba" +
                    (" cuando más pesaba" if last and g["min"] >= 80 else ""))
            kind = "lead"
        elif before < -1:
            text, kind = f"{who} descontó para {team} a los {m}{_how(g)} y le metió suspenso", "cut"
        else:
            last = g is goals[-1]
            text = (f"{who} la liquidó a los {m}{_how(g)}" if last and g["min"] >= 75 else
                    f"{who} amplió la ventaja a los {m}{_how(g)}")
            kind = "extend"
        if prev_kind in ("cut", "tie") and kind in ("lead", "extend"):
            text = "Pero " + text
        lines.append(text[0].upper() + text[1:] + ".")
        prev_kind = kind
    if len(lines) > 4:   # muchos goles: el primero, el resumen y el último
        lines = [lines[0], f"Después fue un ida y vuelta con {len(goals) - 2} goles más.", lines[-1]]
    return lines


def _stakes(rep: dict) -> str:
    s = rep.get("series")
    if not s:
        return ""
    sw = _series_winner(rep)
    ha, aa = rep["home"].get("agg"), rep["away"].get("agg")
    if sw:
        phrase = (STAGE.get(rep.get("stage") or "") or ("", "avanza"))[1]
        loser = "away" if sw == "home" else "home"
        wb = (rep[sw].get("agg") or 0) - rep[sw]["score"]
        lb = (rep[loser].get("agg") or 0) - rep[loser]["score"]
        back = f" Llegaba perdiendo {wb}-{lb} de la ida y lo dio vuelta." if wb < lb else ""
        return f"🏆 Global {ha}-{aa}: {_team(rep[sw])} {phrase}.{back}"
    if s.get("leg") == 1:
        return f"🔜 Esto recién empieza: la serie se define en la vuelta."
    return ""


def _hero_line(rep: dict) -> str:
    h = hero(rep)
    if not h:
        return ""
    mins = [g["label"] for g in rep["goals"] if g["full"] == h["full"] and g["kind"] != "own"]
    goles = f"doblete ({', '.join(mins)})" if len(mins) == 2 else f"triplete ({', '.join(mins)})" \
        if len(mins) >= 3 else f"gol al {mins[0]}"
    return f"⭐ Figura: {h['full']}, {goles}."


def _pick_story(p: dict) -> str:
    if p.get("news"):
        return ""
    lab, o = pick_label(p), formatting.odds(p["price"])
    return {"W": f"🎯 Y lo vimos venir: {lab} @ {o} ✅ ¡VERDE! 💚",
            "L": f"🎯 Esta vez no se nos dio: {lab} @ {o} ❌. Se pierde, se anota y seguimos con la misma disciplina.",
            "V": f"🎯 {lab} @ {o} ↩️ Nula: se devuelve lo apostado."}.get(p.get("result"), "")


def _goal_lines(rep: dict) -> list[str]:
    out = []
    for g in rep["goals"]:
        extra = " (penal)" if g["kind"] == "penalty" else " (en contra)" if g["kind"] == "own" else ""
        out.append(f"⚽ {g['label']} {g['player']}{extra} · {_team(rep[g['side']])}")
    return out


def _body(p: dict, rep: dict) -> tuple[str, list[str], str]:
    kind = headline(rep)
    seed = str(rep.get("id") or p.get("id"))
    opener = _pick_one(OPENERS.get(kind, OPENERS["VICTORIA"]), seed)
    question = _pick_one(QUESTIONS.get(kind, DEFAULT_Q), seed + "q")
    h, a = rep["home"], rep["away"]
    score = f"{_team(h)} {h['score']}-{a['score']} {_team(a)}"
    parts = [score, ""] + [" ".join(story(rep))]
    for extra in (_stakes(rep), _hero_line(rep)):
        if extra:
            parts += ["", extra]
    return opener, parts, question


def telegram_caption(p: dict, rep: dict, title: str) -> str:
    esc = formatting.escape
    opener, parts, question = _body(p, rep)
    lines = [f"📰 <b>{esc(opener)}</b>", ""]
    lines += [f"<b>{esc(parts[0])}</b>"] + [esc(x) for x in parts[1:]]
    ps = _pick_story(p)
    if ps:
        lines += ["", esc(ps)]
    lines += ["", "🔞 +18 · Juega con responsabilidad."]
    return "\n".join(lines)


def instagram_caption(p: dict, rep: dict, title: str, credit: dict | None) -> str:
    opener, parts, question = _body(p, rep)
    lines = [opener, ""] + parts + [""] + (_goal_lines(rep) or [])
    ps = _pick_story(p)
    if ps:
        lines += ["", ps]
    lines += ["", question, "",
              "📲 Pick gratis todos los días en nuestro canal de Telegram (link en la bio)."]
    if credit and credit.get("author"):
        lines += ["", f"📸 Foto: {credit['author']} / Wikimedia Commons ({credit['license']}), modificada. "
                      f"Esta imagen se comparte bajo la misma licencia."]
    lines += ["🔞 +18 · Juega con responsabilidad. Apostar implica riesgo de pérdida.", ""]
    tags = ["#Stakevision", "#Futbol"]
    h, a = rep["home"], rep["away"]
    for t in (formatting._tag((p["legs"][0].get("league") or "").split("·")[-1]),
              formatting._tag(_team(h)), formatting._tag(_team(a))):
        if t and t not in tags:
            tags.append(t)
    lines.append(" ".join(tags))
    return "\n".join(lines)
