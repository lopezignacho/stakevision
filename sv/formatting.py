"""Textos de Telegram y análisis."""
from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from . import config

TZ = ZoneInfo(config.TIMEZONE)


def local_time(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)
    return dt.strftime("%d/%m %H:%M") + (" a. m." if dt.hour < 12 else " p. m.")


def pct(x: float) -> str:
    return f"{x * 100:.1f}%".replace(".", ",")


def odds(x: float) -> str:
    return f"{x:.2f}"


def _line(x) -> str:
    x = float(x)
    return f"{x:g}" if x != int(x) else f"{int(x)}"


def outcome_label(l: dict) -> str:
    """Texto claro de la selección, por ejemplo 'Más de 2.5 goles' o 'Colo-Colo -0.5 (hándicap asiático)'."""
    if l.get("label"):
        return l["label"]
    o = str(l["outcome"]).strip()
    t = l.get("mtype", "")
    h = l.get("handicap")
    team = {"1": l["home"], "2": l["away"]}
    push = h is not None and float(h) == int(float(h))   # línea entera: con ese número exacto se devuelve
    push_txt = f" (con {_line(h)} exactos se devuelve)" if push else ""
    if l.get("sport") == "basketball":
        unit = "puntos"
        if t == "moneyline" and o in team:
            return f"Gana {team[o]} (incluye prórroga)"
        if t == "totals" and h is not None:
            return f"{'Más' if o.lower().startswith(('más', 'mas', 'over')) else 'Menos'} de {_line(h)} {unit}{push_txt}"
        if t in ("teamtotals-team1", "teamtotals-team2") and h is not None:
            who = l["home"] if t.endswith("1") else l["away"]
            return f"{who}: {'más' if o.lower().startswith(('más', 'mas', 'over')) else 'menos'} de {_line(h)} {unit}{push_txt}"
        if t == "spreads" and h is not None and o in team:
            hh = float(h) if o == "1" else -float(h)
            return f"{team[o]} {'+' if hh > 0 else ''}{_line(hh)} (hándicap de puntos)"
    if t == "totals" and h is not None:
        return f"{'Más' if o.lower().startswith('más') else 'Menos'} de {_line(h)} goles{push_txt}"
    if t in ("teamtotals-team1", "teamtotals-team2") and h is not None:
        who = l["home"] if t.endswith("1") else l["away"]
        return f"{who}: {'más' if o.lower().startswith('más') else 'menos'} de {_line(h)} goles{push_txt}"
    if t in ("toscore-team1", "toscore-team2"):
        who = l["home"] if t.endswith("1") else l["away"]
        return f"{who} {'marca' if o.lower().startswith('s') else 'no marca'}"
    if t == "bothteamsscore":
        return "Ambos marcan: Sí" if o.lower().startswith("s") else "Ambos marcan: No"
    if t == "spreads" and h is not None and o in team:
        hh = float(h) if o == "1" else -float(h)   # la línea viene expresada para el local
        if hh == 0:
            return f"{team[o]} gana (si empatan, se devuelve)"
        return (f"{team[o]} {'+' if hh > 0 else ''}{_line(hh)} (hándicap asiático"
                + ("; si empata en la línea, se devuelve)" if push and hh != 0 else ")"))
    if t == "drawnobet" and o in team:
        return f"{team[o]} gana (si empatan, se devuelve)"
    if o in team:
        return f"Gana {team[o]}"
    if o.upper() == "X":
        return "Empate"
    return o


def _n(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def _streak_phrase(ms: list[dict]) -> str:
    """Racha actual, del partido más reciente hacia atrás."""
    res = ["G" if m["gf"] > m["ga"] else "E" if m["gf"] == m["ga"] else "P" for m in ms]
    def run(pred):
        k = 0
        for r in res:
            if not pred(r):
                break
            k += 1
        return k
    w, nl, l, nw = run(lambda r: r == "G"), run(lambda r: r != "P"), run(lambda r: r == "P"), run(lambda r: r != "G")
    if w >= 3:
        return f"{w} victorias seguidas"
    if nl >= 3:
        return f"{nl} partidos sin perder"
    if l >= 2:
        return f"{l} derrotas seguidas"
    if nw >= 3:
        return f"{nw} partidos sin ganar"
    return ""


def _team_line(team: str, ms: list[dict], venue: str) -> str:
    """Una línea con la forma del equipo: racha, balance, goles y rendimiento de local o de visita."""
    last = ms[:6]
    g = sum(m["gf"] > m["ga"] for m in last)
    e = sum(m["gf"] == m["ga"] for m in last)
    p = len(last) - g - e
    gf = sum(m["gf"] for m in last) / len(last)
    ga = sum(m["ga"] for m in last) / len(last)
    streak = _streak_phrase(ms)
    head = f"{escape(team)} llega con {streak}" if streak else f"{escape(team)}"
    line = (f"{head}{':' if streak else ''} {g}G {e}E {p}P en sus últimos {len(last)}, "
            f"con {_n(gf)} goles a favor y {_n(ga)} en contra por partido")
    at = [m for m in ms if m["venue"] == venue][:5]
    if len(at) >= 3:
        wins = sum(m["gf"] > m["ga"] for m in at)
        where = "de local" if venue == "L" else "de visita"
        line += f"; {where} ganó {wins} de {len(at)}"
    return line + "."


def _market_line(l: dict, h: list[dict], a: list[dict]) -> str:
    """Dato que respalda directamente el mercado elegido."""
    t, o, line = l.get("mtype", ""), str(l.get("outcome", "")).lower(), l.get("handicap")
    hh, aa = h[:6], a[:6]
    if t == "totals" and line is not None:
        over = o.startswith(("más", "mas"))
        cnt = lambda ms: sum(((m["gf"] + m["ga"]) > float(line)) == over for m in ms)  # noqa: E731
        txt = f"{'más' if over else 'menos'} de {_line(line)} goles"
        return (f"Se dieron {txt} en {cnt(hh)} de {len(hh)} partidos de {escape(l['home'])} "
                f"y en {cnt(aa)} de {len(aa)} de {escape(l['away'])}.")
    if t == "bothteamsscore":
        yes = o.startswith(("s", "y"))
        cnt = lambda ms: sum((m["gf"] > 0 and m["ga"] > 0) == yes for m in ms)  # noqa: E731
        return (f"{'Ambos marcaron' if yes else 'Al menos uno no marcó'} en {cnt(hh)} de {len(hh)} partidos de "
                f"{escape(l['home'])} y en {cnt(aa)} de {len(aa)} de {escape(l['away'])}.")
    if t.startswith(("teamtotals", "toscore")):
        side = hh if t.endswith("1") else aa
        team = l["home"] if t.endswith("1") else l["away"]
        scored = sum(m["gf"] > 0 for m in side)
        return f"{escape(team)} marcó en {scored} de sus últimos {len(side)} partidos."
    return ""


def analysis(pick: dict) -> str:
    """Valor de la cuota + forma real de los equipos (si hay datos) + probabilidad. Breve."""
    if any(l.get("sport") == "basketball" for l in pick["legs"]):
        from . import nba
        parts = [nba.arguments_text(l, l.get("nba_ctx")) for l in pick["legs"]]
        parts.append(f"Probabilidad estimada: {pct(pick['prob'])}. "
                     f"Para no perder a esta cuota se necesita {pct(1 / pick['price'])}.")
        return "\n".join(x for x in parts if x)
    parts = []
    for l in pick["legs"]:
        if len(pick["legs"]) > 1:
            parts.append(f"<b>{escape(outcome_label(l))}</b> en {escape(l['home'])} vs {escape(l['away'])}")
        pros, cons = soccer_arguments(l)
        if pros:
            parts.append("✅ <b>A favor:</b>\n" + "\n".join(f"• {p}" for p in pros))
        if cons:
            parts.append("⚠️ <b>En contra:</b>\n" + "\n".join(f"• {c}" for c in cons))
    parts.append(f"Probabilidad estimada: {pct(pick['prob'])}. "
                 f"Para no perder a esta cuota se necesita {pct(1 / pick['price'])}.")
    return "\n".join(parts)


def _pts(ms: list[dict]) -> int:
    return sum(3 if m["gf"] > m["ga"] else 1 if m["gf"] == m["ga"] else 0 for m in ms[:6])


def soccer_arguments(l: dict) -> tuple[list[str], list[str]]:
    """Argumentos a favor y en contra de una selección de fútbol, con datos reales (texto HTML escapado)."""
    pros, cons = [], []
    edge = l.get("edge", 0)
    if edge >= config.MIN_EDGE:
        pros.append(f"Valor: cuota justa {odds(l['fair_odds'])} y cuota disponible "
                    f"{odds(l['price'])}: +{pct(edge)}.")
    elif edge >= 0:
        pros.append(f"Cuota en línea con la justa ({odds(l['fair_odds'])}): no hay regalo de la casa, "
                    "la decisión se apoya en la forma de los equipos.")
    else:
        cons.append(f"Paga algo menos que la cuota justa ({odds(l['fair_odds'])}).")
    ctx = l.get("context") or {}
    if ctx.get("v") != 2:
        return pros, cons
    h, a = ctx.get("home") or [], ctx.get("away") or []
    t, o = l.get("mtype", ""), str(l.get("outcome", "")).strip().lower()
    side = {"1": "home", "2": "away"}.get(o) if t in ("1x2", "drawnobet", "spreads") else None
    if side and len(h) >= 3 and len(a) >= 3:
        me, op = (h, a) if side == "home" else (a, h)
        mn, on = (l["home"], l["away"]) if side == "home" else (l["away"], l["home"])
        mv, ov = ("L", "V") if side == "home" else ("V", "L")
        (pros if _pts(me) >= _pts(op) else cons).append("📊 " + _team_line(mn, me, mv))
        (pros if _pts(op) < _pts(me) else cons).append("📊 " + _team_line(on, op, ov))
    elif t == "1x2" and o == "x" and len(h) >= 3 and len(a) >= 3:
        draws = sum(m["gf"] == m["ga"] for m in h[:6]) + sum(m["gf"] == m["ga"] for m in a[:6])
        n = len(h[:6]) + len(a[:6])
        (pros if draws / n >= 0.3 else cons).append(f"Empates recientes: {draws} de {n} partidos entre los dos equipos.")
    elif len(h) >= 3 and len(a) >= 3:
        m_line = _market_line(l, h, a)
        hits = [int(x) for x in __import__("re").findall(r"en (\d+) de (\d+)", m_line or "") for x in x[:1]]
        tot = [int(x[1]) for x in __import__("re").findall(r"en (\d+) de (\d+)", m_line or "")]
        if m_line:
            ratio = sum(hits) / max(sum(tot), 1)
            (pros if ratio >= 0.5 else cons).append("🎯 " + m_line)
        pros.append("📊 " + _team_line(l["home"], h, "L"))
        pros.append("📊 " + _team_line(l["away"], a, "V"))
    if len(h) < 3 or len(a) < 3:
        cons.append("Poco historial reciente de uno de los equipos: el análisis se apoya sobre todo en la cuota.")
    return pros[:4], cons[:3]


def _legs_block(pick: dict) -> str:
    rows = []
    if pick.get("kind") == "builder":
        l0 = pick["legs"][0]
        emoji = "🏀" if l0.get("sport") == "basketball" else "⚽"
        marks = {"W": " ✅", "L": " ❌"}
        return (f"{emoji} <b>{escape(l0['home'])} vs {escape(l0['away'])}</b> · 🧩 Bet Builder @ {odds(pick['price'])}\n"
                + "\n".join(f"{NUM_EMOJI[i]} {escape(l['label'])}{marks.get(l.get('leg_result'), '')}"
                            for i, l in enumerate(pick["legs"])))
    for l in pick["legs"]:
        emoji = "🏀" if l.get("sport") == "basketball" else "⚽"
        rows.append(f"{emoji} <b>{escape(l['home'])} vs {escape(l['away'])}</b>\n"
                    f"🏆 {escape(l['league'])} · 🕒 {local_time(l['kickoff'])}\n"
                    f"🎯 <b>{escape(outcome_label(l))}</b> @ {odds(l['price'])}")
    return "\n\n".join(rows)


def _bank(stake: int) -> str:
    return f"{stake * 0.5:g}%".replace(".", ",")


def channel_post(pick: dict, tier: str | None = None) -> str:
    """Texto del pick en los canales: partido, cuota y stake + argumento (resumen, 3 datos y probabilidad).
    tier «free» / «vip» cambia el título y el cierre."""
    if pick.get("kind") == "builder":
        return builder_post(pick, "vip")
    from . import argument
    if any(l.get("sport") == "basketball" for l in pick["legs"]):
        tier = "vip"
    if pick["kind"] == "doble":
        title = "COMBINADA DOBLE" + (" · VIP" if tier == "vip" else " · GRATIS" if tier == "free" else "")
    else:
        title = {"vip": "PICK VIP 👑", "free": "PICK GRATIS 🎁"}.get(tier, "PICK DEL DÍA")
    close = ("👑 Exclusivo VIP · 🔞 +18 · Apuesta con responsabilidad" if tier == "vip" else
             "Más pronósticos en nuestro VIP 👑\n🔞 +18 · Apuesta con responsabilidad" if tier == "free" else
             "🔞 +18 · Apuesta con responsabilidad")
    return (f"👁 <b>STAKEVISION · {title}</b>\n\n"
            f"{_legs_block(pick)}\n\n"
            + (f"📈 Cuota total: <b>{odds(pick['price'])}</b> · " if len(pick["legs"]) > 1 else "")
            + f"💰 Stake: <b>{pick['stake']}/10</b> ({_bank(pick['stake'])} del bankroll)\n\n"
            + f"{argument.body(pick)}\n\n{close}")


def owner_candidate(pick: dict) -> str:
    tag = ("🟢 <b>Con valor</b>" if pick.get("tier", "valor") == "valor"
           else "⚖️ <b>Cuota justa</b> (sin ventaja medida: decide según tu lectura del partido)")
    sign = "+" if pick["edge"] >= 0 else ""
    live = ""
    if pick.get("live"):
        live = (f"🔴 <b>EN VIVO</b>" + (f" · {escape(pick['live_info'])}" if pick.get("live_info") else "")
                + f"\n⏱ Vence en {config.LIVE_CANDIDATE_MIN} min: las cuotas en vivo cambian rápido.\n")
    return (f"🆕 <b>Candidato #{pick['id']}</b> ({pick['kind']})\n{live}{tag}\n\n"
            f"{_legs_block(pick)}\n\n"
            f"📈 Cuota: <b>{odds(pick['price'])}</b> · Valor: <b>{sign}{pct(pick['edge'])}</b> · "
            f"Stake sugerido: {pick['stake']}/10\n\n"
            f"<i>{pick['analysis']}</i>\n\n"
            f"Verifica la cuota en tu app antes de elegir. Al tocar «Elegir» te llega la imagen y decides dónde publicarla.")


RESULT_LABEL = {"W": "✅ VERDE", "L": "❌ ROJA", "V": "↩️ NULA (devuelta)"}


def result_post(pick: dict) -> str:
    if pick.get("kind") == "builder":
        return f"{RESULT_LABEL[pick['result']]}\n{_legs_block(pick)}"
    names = " + ".join(f"{l['home']} vs {l['away']}" for l in pick["legs"])
    return f"{RESULT_LABEL[pick['result']]}\n{escape(names)} @ {odds(pick['price'])}"


def _scores_block(pick: dict, scores: list) -> str:
    rows = []
    for l, sc in zip(pick["legs"], scores):
        if sc:
            rows.append(f"⚽ {escape(l['home'])} <b>{sc[0]}-{sc[1]}</b> {escape(l['away'])}")
    return "\n".join(rows)


def owner_result_request(pick: dict, suggestion: str | None, scores: list | None = None) -> str:
    sc = _scores_block(pick, scores or [])
    sc = f"\n\nMarcador final (90'):\n{sc}" if sc else "\n\nNo encontré el marcador final."
    sug = f"\nSugerencia según el marcador: <b>{RESULT_LABEL[suggestion]}</b>" if suggestion else ""
    return (f"🏁 <b>Resultado del pick #{pick['id']}</b>\n\n{_legs_block(pick)}{sc}{sug}\n\n"
            f"Confirma el resultado:")


def owner_auto_result(pick: dict, scores: list) -> str:
    return (f"🤖 <b>Resultado automático · pick #{pick['id']}</b>\n\n{_legs_block(pick)}\n\n"
            f"Marcador final (90'):\n{_scores_block(pick, scores)}\n\n"
            f"Resultado: <b>{RESULT_LABEL[pick['result']]}</b>\n"
            f"Ya quedó publicado en los canales y en la web. Si algo no cuadra, toca Corregir.")


def result_correction(pick: dict) -> str:
    return result_post(pick) + "\n<i>(resultado corregido)</i>"


def pre_kickoff(pick: dict, minutes: int) -> str:
    when = "en unos minutos" if minutes < 5 else f"en {minutes} minutos"
    emoji = {"soccer": "⚽", "tennis": "🎾", "basketball": "🏀"}
    matches = "\n".join(f"{emoji.get(l.get('sport') or 'soccer', '🏟')} {escape(l['home'])} vs {escape(l['away'])}" for l in pick["legs"])
    return (f"⏰ <b>¡Nuestro pronóstico está por comenzar!</b>\n\n"
            f"{matches}\n"
            f"🎯 {escape(' + '.join(outcome_label(l) for l in pick['legs']))} @ <b>{odds(pick['price'])}</b>\n\n"
            f"Arranca {when}. Ojos en la cancha 👁\n"
            f"🔞 +18 · Apuesta con responsabilidad")


def caption_fits(text: str) -> bool:
    """Telegram permite 1024 caracteres visibles en el texto de una foto."""
    import html as _h
    import re as _re
    return len(_h.unescape(_re.sub(r"<[^>]+>", "", text))) <= 1000


# ---------------------------------------------------------------- Instagram (picks verdes)
_IG_OPENERS = [
    "✅ ¡VERDE! 🔥",
    "💚 ¡Otra verde para la cuenta!",
    "👁 Lo vimos antes del pitazo… y se cumplió. ✅",
    "✅ ¡Cobrada! 💚",
]
_IG_MIDDLES = [
    "Análisis, datos y paciencia: así se construye cada pick.",
    "Leer el partido antes de que empiece: ese es el trabajo.",
    "Cada pick se publica antes del partido y queda en el historial, gane o pierda.",
    "Seguimos sumando con números, no con corazonadas.",
]
_SPORT_TAG = {"soccer": "#Futbol", "tennis": "#Tenis", "basketball": "#Basquetbol"}


def _tag(text: str) -> str:
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = "".join(w[:1].upper() + w[1:] for w in re.split(r"[^A-Za-z0-9]+", t) if w)
    return f"#{t}" if len(t) >= 3 else ""


def instagram_caption(pick: dict, streak: int = 1) -> str:
    """Texto listo para pegar en Instagram cuando un pick sale verde (texto plano)."""
    k = int(pick.get("id") or 0)
    lines = [_IG_OPENERS[k % len(_IG_OPENERS)], ""]
    for l in pick["legs"]:
        sc = l.get("score")
        e = {"soccer": "⚽", "tennis": "🎾", "basketball": "🏀"}.get(l.get("sport") or "soccer", "🏟")
        lines.append(f"{e} {l['home']} {sc[0]}-{sc[1]} {l['away']}" if sc else f"{e} {l['home']} vs {l['away']}")
        sel = outcome_label(l)
        lines.append(f"🎯 {sel[:sel.index(' (')] if ' (' in sel else sel}")
    lines.append(f"📈 Cuota {odds(pick['price'])} · Stake {pick['stake']}/10")
    if streak >= 2:
        lines += ["", f"🔥 ¡{streak} verdes seguidos!"]
    lines += ["", _IG_MIDDLES[k % len(_IG_MIDDLES)], "",
              "📲 Pick gratis todos los días en nuestro canal de Telegram (link en la bio).",
              "🔞 +18 · Juega con responsabilidad. Apostar implica riesgo de pérdida.", ""]
    tags = ["#Stakevision", "#PronosticosDeportivos", "#Verde"]
    for l in pick["legs"]:
        for t in (_SPORT_TAG.get(l.get("sport") or "soccer", ""),
                  _tag((l.get("league") or "").split("·")[-1]), _tag(l["home"]), _tag(l["away"])):
            if t and t not in tags:
                tags.append(t)
    lines.append(" ".join(tags[:12]))
    return "\n".join(lines)


def instagram_pick_caption(pick: dict) -> str:
    """Texto para Instagram de un pick antes del partido (texto plano), con el mismo argumento que Telegram:
    resumen, 3 datos con emoji y probabilidad estimada."""
    import html as _h
    import re as _re
    from . import argument
    emoji = {"soccer": "⚽", "tennis": "🎾", "basketball": "🏀"}
    lines = ["👁 STAKEVISION · PICK GRATIS 🎁" + (" · 🔴 EN VIVO" if pick.get("live") else ""), ""]
    for l in pick["legs"]:
        lines.append(f"{emoji.get(l.get('sport') or 'soccer', '🏟')} {l['home']} vs {l['away']}")
        lines.append(f"🏆 {l['league']} · 🕒 {local_time(l['kickoff'])}")
        lines.append(f"🎯 {outcome_label(l)} @ {odds(l['price'])}")
    lines.append(("" if len(pick["legs"]) == 1 else f"📈 Cuota total {odds(pick['price'])} · ")
                 + f"💰 Stake {pick['stake']}/10")
    body = _h.unescape(_re.sub(r"<[^>]+>", "", argument.body(pick)))
    lines += ["", body, "", "📲 Pick gratis todos los días en nuestro canal de Telegram (link en la bio) "
              "· más pronósticos en el VIP 👑"]
    cr = pick.get("pick_photo_credit") if pick.get("pick_style") == "photo" else None
    if cr and cr.get("author"):
        lines += ["", f"📸 Foto: {cr['author']} / Wikimedia Commons ({cr['license']}), modificada. "
                  "Esta imagen se comparte bajo la misma licencia."]
    lines += ["", "🔞 +18 · Juega con responsabilidad. Apostar implica riesgo de pérdida.", "",
              "#Stakevision #PronosticosDeportivos #Futbol #ApuestasDeportivas"]
    return "\n".join(lines)


# ---------------------------------------------------------------- Bet Builder
NUM_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]


def builder_post(pick: dict, tier: str | None = "vip") -> str:
    """Texto del Bet Builder en el canal: partido, patas con su % de acierto, argumento y probabilidad."""
    b = pick["bb"]
    l0 = pick["legs"][0]
    icon = "🏀" if b["sport"] == "basketball" else "⚽"
    rows = [f"{NUM_EMOJI[i]} <b>{escape(x['label'])}</b>" for i, x in enumerate(b["legs"])]
    facts = []
    for x in b["legs"]:
        facts.append(f"• {escape(x['player'])} promedia {_n(x['avg'])} {x['word']} y superó la línea en "
                     f"{x['hits']} de sus últimos {x['n']} partidos " + ("✅" if x["hits"] == x["n"] else "🎯"))
    summary = ("🧠 Líneas que cada jugador cumple casi de memoria: buscamos lo que repiten partido tras partido, "
               "no la estadística de un día 📊")
    need = 1 / pick["price"]
    close = ("👑 Exclusivo VIP · 🔞 +18 · Apuesta con responsabilidad" if tier == "vip"
             else "Más pronósticos en nuestro VIP 👑\n🔞 +18 · Apuesta con responsabilidad")
    return (f"👁 <b>STAKEVISION · BET BUILDER 🧩{' · VIP 👑' if tier == 'vip' else ''}</b>\n\n"
            f"{icon} <b>{escape(l0['home'])} vs {escape(l0['away'])}</b>\n"
            f"🏆 {escape(l0['league'])} · 🕒 {local_time(l0['kickoff'])}\n\n"
            + "\n".join(rows) + "\n\n"
            f"📈 Cuota: <b>{odds(pick['price'])}</b> · 💰 Stake: <b>{pick['stake']}/10</b> "
            f"({_bank(pick['stake'])} del bankroll)\n\n"
            f"{summary}\n\n" + "\n\n".join(facts) + "\n\n"
            f"📈 <b>Probabilidad estimada: {pct(pick['prob'])}</b> · a cuota {odds(pick['price'])} alcanza con {pct(need)}"
            + (f" (valor +{pct(pick['edge'])})" if pick.get("edge", 0) > 0 else "") + "\n\n" + close)


def builder_owner(pick: dict) -> str:
    b = pick["bb"]
    l0 = pick["legs"][0]
    icon = "🏀 NBA" if b["sport"] == "basketball" else "⚽ Fútbol"
    rows = [f"{NUM_EMOJI[i]} <b>{escape(x['label'])}</b> · {x['hits']}/{x['n']} (prom. {_n(x['avg'])})"
            for i, x in enumerate(b["legs"])]
    return (f"🧩 <b>Bet Builder sugerido #{pick['id']}</b> · {icon}\n"
            f"{escape(l0['home'])} vs {escape(l0['away'])} · 🕒 {local_time(l0['kickoff'])}\n\n"
            + "\n".join(rows) + "\n\n"
            f"📈 Probabilidad estimada (combinada): <b>{pct(b['prob'])}</b> → cuota mínima <b>{odds(b['fair'])}</b>\n"
            f"🎯 Objetivo ~{odds(b['target'])}. Ármalo en tu app: si la cuota es mayor que {odds(b['fair'])}, "
            "según estos números conviene.\n\n"
            "Cuando lo tengas, toca «Cargar cuota» y escríbeme la cuota real (ej. 3.10). "
            "Las patas están pensadas para estar relacionadas lo menos posible, pero la casa igual puede ajustar el precio.")
