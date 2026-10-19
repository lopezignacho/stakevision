"""Textos de Telegram y análisis."""
from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from . import config

TZ = ZoneInfo(config.TIMEZONE)


def local_time(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)
    return dt.strftime("%d/%m %H:%M")


def pct(x: float) -> str:
    return f"{x * 100:.1f}%".replace(".", ",")


def odds(x: float) -> str:
    return f"{x:.2f}"


def outcome_label(l: dict) -> str:
    o = str(l["outcome"]).strip()
    if o == "1":
        return f"Gana {l['home']}"
    if o == "2":
        return f"Gana {l['away']}"
    if o.upper() == "X":
        return "Empate"
    if o in ("1X", "X2", "12"):
        return {"1X": f"{l['home']} o empate", "X2": f"{l['away']} o empate",
                "12": "No hay empate"}[o]
    return o


def analysis(pick: dict) -> str:
    """Texto breve y honesto basado en los datos que realmente tenemos."""
    parts = []
    for l in pick["legs"]:
        line = (f"{escape(outcome_label(l))} ({escape(l['market'])}) en {escape(l['home'])} vs {escape(l['away'])}: "
                f"cuota justa estimada {odds(l['fair_odds'])}, cuota disponible {odds(l['price'])} "
                f"(+{pct(l['edge'])} de valor).")
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
                    f"🎯 {escape(l['market'])}: <b>{escape(outcome_label(l))}</b> @ {odds(l['price'])}")
    return "\n\n".join(rows)


def channel_post(pick: dict) -> str:
    title = "COMBINADA DOBLE" if pick["kind"] == "doble" else "PICK DEL DÍA"
    return (f"👁 <b>STAKEVISION · {title}</b>\n\n"
            f"{_legs_block(pick)}\n\n"
            f"📈 Cuota total: <b>{odds(pick['price'])}</b>\n"
            f"💰 Stake: <b>{pick['stake']}/10</b>\n\n"
            f"🧠 <i>{pick['analysis']}</i>\n\n"
            f"🔞 +18 · Apuesta con responsabilidad")


def owner_candidate(pick: dict) -> str:
    return (f"🆕 <b>Candidato #{pick['id']}</b> ({pick['kind']})\n\n"
            f"{_legs_block(pick)}\n\n"
            f"📈 Cuota: <b>{odds(pick['price'])}</b> · Valor: <b>+{pct(pick['edge'])}</b> · "
            f"Stake sugerido: {pick['stake']}/10\n\n"
            f"<i>{pick['analysis']}</i>\n\n"
            f"Verifica la cuota en tu app antes de aprobar.")


RESULT_LABEL = {"W": "✅ VERDE", "L": "❌ ROJA", "V": "↩️ NULA (devuelta)"}


def result_post(pick: dict) -> str:
    names = " + ".join(f"{l['home']} vs {l['away']}" for l in pick["legs"])
    return f"{RESULT_LABEL[pick['result']]}\n{escape(names)} @ {odds(pick['price'])}"


def owner_result_request(pick: dict, suggestion: str | None) -> str:
    sug = f"\nSugerencia según el marcador: <b>{RESULT_LABEL[suggestion]}</b>" if suggestion else ""
    return (f"🏁 <b>Resultado del pick #{pick['id']}</b>\n\n{_legs_block(pick)}{sug}\n\n"
            f"Confirma el resultado:")
