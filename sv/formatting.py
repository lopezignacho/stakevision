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


def analysis(pick: dict) -> str:
    """Texto breve y honesto basado en los datos que realmente tenemos."""
    parts = []
    for l in pick["legs"]:
        line = (f"{escape(outcome_label(l))} en {escape(l['home'])} vs {escape(l['away'])}: "
                f"cuota justa estimada {odds(l['fair_odds'])}, cuota disponible {odds(l['price'])}"
                + (f" (+{pct(l['edge'])} de valor)." if l['edge'] >= 0 else " (en línea con la cuota justa)."))
        ctx = l.get("context")
        if ctx:
            bits = []
            for side, team in (("home", l["home"]), ("away", l["away"])):
                c = ctx.get(side)
                if c and c.get("form"):
                    bits.append(f"{escape(team)} últimos {len(c['form'])}: {c['form']} "
                                f"({c['gf']} a favor / {c['ga']} en contra por partido)")
            if bits:
                line += " " + "; ".join(bits) + "."
        parts.append(line)
    parts.append(f"Probabilidad estimada: {pct(pick['prob'])}. "
                 f"Para no perder a esta cuota se necesita {pct(1 / pick['price'])}.")
    return "\n".join(parts)


def _legs_block(pick: dict) -> str:
    rows = []
    for l in pick["legs"]:
        rows.append(f"⚽ <b>{escape(l['home'])} vs {escape(l['away'])}</b>\n"
                    f"🏆 {escape(l['league'])} · 🕒 {local_time(l['kickoff'])}\n"
                    f"🎯 <b>{escape(outcome_label(l))}</b> @ {odds(l['price'])}")
    return "\n\n".join(rows)


def _bank(stake: int) -> str:
    return f"{stake * 0.5:g}%".replace(".", ",")


def channel_post(pick: dict) -> str:
    title = "COMBINADA DOBLE" if pick["kind"] == "doble" else "PICK DEL DÍA"
    return (f"👁 <b>STAKEVISION · {title}</b>\n\n"
            f"{_legs_block(pick)}\n\n"
            f"📈 Cuota total: <b>{odds(pick['price'])}</b>\n"
            f"💰 Stake: <b>{pick['stake']}/10</b> ({_bank(pick['stake'])} del bankroll)\n\n"
            f"🧠 <i>{pick['analysis']}</i>\n\n"
            f"🔞 +18 · Apuesta con responsabilidad")


def owner_candidate(pick: dict) -> str:
    tag = ("🟢 <b>Con valor</b>" if pick.get("tier", "valor") == "valor"
           else "⚖️ <b>Cuota justa</b> (sin ventaja medida: decide según tu lectura del partido)")
    sign = "+" if pick["edge"] >= 0 else ""
    return (f"🆕 <b>Candidato #{pick['id']}</b> ({pick['kind']})\n{tag}\n\n"
            f"{_legs_block(pick)}\n\n"
            f"📈 Cuota: <b>{odds(pick['price'])}</b> · Valor: <b>{sign}{pct(pick['edge'])}</b> · "
            f"Stake sugerido: {pick['stake']}/10\n\n"
            f"<i>{pick['analysis']}</i>\n\n"
            f"Verifica la cuota en tu app antes de aprobar. Tu elección se aplica en unos minutos.")


RESULT_LABEL = {"W": "✅ VERDE", "L": "❌ ROJA", "V": "↩️ NULA (devuelta)"}


def result_post(pick: dict) -> str:
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
