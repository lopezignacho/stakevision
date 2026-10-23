"""Argumento de cada pick, dentro del texto del PICK, al estilo de los canales de pronósticos.

    ⚽ Resumen en una frase de por qué elegimos el pick 📊

    • Dato concreto 1 🎯
    • Dato concreto 2 ✅
    • Dato concreto 3 📉

    📈 Probabilidad estimada: 58,3% · a esta cuota alcanza con 54,1%

    Cierre (Gratis: invita al VIP y al historial · VIP: exclusivo)

Los datos salen del historial propio (fútbol) o de ESPN (NBA). Nunca se nombra la casa de apuestas.
"""
from __future__ import annotations

from . import config
from .formatting import _line, _n, _pts, _streak_phrase, escape, odds, outcome_label, pct


# ---------------------------------------------------------------- fútbol
def _rec(ms: list[dict]) -> tuple[int, int, int]:
    g = sum(m["gf"] > m["ga"] for m in ms)
    e = sum(m["gf"] == m["ga"] for m in ms)
    return g, e, len(ms) - g - e


def _pl(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _avg(ms, key) -> float:
    return sum(m[key] for m in ms) / len(ms) if ms else 0.0


def _soccer(l: dict) -> tuple[str, list[str]]:
    """(resumen, datos) para una selección de fútbol."""
    ctx = l.get("context") or {}
    H, A = (ctx.get("home") or [])[:6], (ctx.get("away") or [])[:6]
    hn, an = escape(l["home"]), escape(l["away"])
    t, o, line = l.get("mtype", ""), str(l.get("outcome", "")).strip().lower(), l.get("handicap")
    facts: list[str] = []
    summary = ""
    ok = ctx.get("v") == 2 and len(H) >= 3 and len(A) >= 3
    side = {"1": "home", "2": "away"}.get(o) if t in ("1x2", "drawnobet", "spreads", "moneyline") else None
    if ok and side:
        me, op = (H, A) if side == "home" else (A, H)
        mn, on = (hn, an) if side == "home" else (an, hn)
        g, e, p = _rec(me)
        og, oe, op_ = _rec(op)
        better = _pts(me) >= _pts(op)
        venue = "L" if side == "home" else "V"
        at = [m for m in (ctx.get("home") if side == "home" else ctx.get("away")) or [] if m.get("venue") == venue][:5]
        where = "en casa" if side == "home" else "de visita"
        strong = bool(at) and sum(m["gf"] > m["ga"] for m in at) / len(at) >= 0.6
        if better:
            summary = (f"{mn} llega mejor por su forma reciente" + (f" y su fuerza {where}" if strong else "")
                       + f"; {on} {'viene irregular' if og <= g else 'también llega bien, pero un escalón abajo'} 📊")
        else:
            summary = (f"{mn} no llega en su mejor momento, pero la cuota paga ese riesgo"
                       + (f" y {where} se hace fuerte" if strong else "") + f"; {on} tampoco es seguro 📊")
        st = _streak_phrase(me)
        facts.append(f"En sus últimos {len(me)}, {mn} suma {_pl(g, 'victoria', 'victorias')}, "
                     f"{_pl(e, 'empate', 'empates')} y {_pl(p, 'derrota', 'derrotas')}"
                     + (f" ({st})" if st else "") + (" ✅" if g >= p else " ⚠️"))
        if len(at) >= 3:
            w = sum(m["gf"] > m["ga"] for m in at)
            facts.append(f"{mn} ganó {w} de sus últimos {len(at)} partidos {where} " + ("🏟" if w * 2 >= len(at) else "⚠️"))
        ost = _streak_phrase(op)
        facts.append(f"{on}: {og}G {oe}E {op_}P en sus últimos {len(op)}" + (f", {ost}" if ost else "")
                     + (" 📉" if og * 2 < len(op) else " ⚠️"))
        facts.append(f"{mn} promedia {_n(_avg(me, 'gf'))} goles a favor y {_n(_avg(me, 'ga'))} en contra 🎯")
    elif ok and t == "totals" and line is not None:
        over = o.startswith(("más", "mas", "over"))
        lim = float(line)
        cnt = lambda ms: sum(((m["gf"] + m["ga"]) > lim) == over for m in ms)  # noqa: E731
        avg = (_avg(H, "gf") + _avg(H, "ga") + _avg(A, "gf") + _avg(A, "ga")) / 2
        txt = f"{'más' if over else 'menos'} de {_line(line)} goles"
        hits = cnt(H) + cnt(A)
        sup = hits * 2 >= len(H) + len(A)
        kind = "abierto y con goles" if over else "cerrado y de pocos goles"
        if sup:
            summary = f"Partido que pinta {kind}: el historial de los dos equipos lo respalda 📊"
        else:
            summary = (f"El historial reciente no acompaña del todo, pero el mercado ve un partido {kind} "
                       f"y la cuota paga ese escenario 📊")
        facts.append(f"Hubo {txt} en {cnt(H)} de los últimos {len(H)} partidos de {hn} "
                     + ("🎯" if cnt(H) * 2 >= len(H) else "⚠️"))
        facts.append(f"Y en {cnt(A)} de los últimos {len(A)} de {an} " + ("✅" if cnt(A) * 2 >= len(A) else "⚠️"))
        facts.append(f"Sus partidos promedian {_n(avg)} goles en total "
                     + (("🔥" if over else "🧊") if (avg > lim) == over else "⚠️"))
    elif ok and t == "bothteamsscore":
        yes = o.startswith(("s", "y"))
        cnt = lambda ms: sum((m["gf"] > 0 and m["ga"] > 0) == yes for m in ms)  # noqa: E731
        sup = (cnt(H) + cnt(A)) * 2 >= len(H) + len(A)
        summary = ((f"{'Dos equipos que marcan y reciben' if yes else 'Al menos uno de los dos suele quedarse en cero'}: "
                    "el historial reciente respalda el pick 📊") if sup else
                   "El historial no es concluyente, pero la cuota paga bien este escenario 📊")
        facts.append(f"{'Ambos marcaron' if yes else 'Al menos uno no marcó'} en {cnt(H)} de {len(H)} partidos de {hn} "
                     + ("🎯" if cnt(H) * 2 >= len(H) else "⚠️"))
        facts.append(f"Y en {cnt(A)} de {len(A)} de {an} " + ("✅" if cnt(A) * 2 >= len(A) else "⚠️"))
        facts.append(f"{hn} marcó en {sum(m['gf'] > 0 for m in H)} de {len(H)}; "
                     f"{an} en {sum(m['gf'] > 0 for m in A)} de {len(A)} ⚽")
    elif ok:
        summary = f"{hn} y {an} llegan con datos que respaldan el pick 📊"
        for nm, ms in ((hn, H), (an, A)):
            g, e, p = _rec(ms)
            facts.append(f"{nm}: {g}G {e}E {p}P en sus últimos {len(ms)}, {_n(_avg(ms, 'gf'))} goles a favor por partido ✅")
    return summary, facts


# ---------------------------------------------------------------- NBA
def _nba(l: dict) -> tuple[str, list[str]]:
    from . import nba
    ctx = l.get("nba_ctx")
    if not ctx:
        return "", []
    H, A = ctx["home"], ctx["away"]
    fh, fa = nba._form(H), nba._form(A)
    t, o, line = l.get("mtype", ""), str(l.get("outcome", "")).lower(), l.get("handicap")
    side = {"1": "home", "2": "away"}.get(o)
    if t == "teamtotals-team1":
        side = "home"
    if t == "teamtotals-team2":
        side = "away"
    facts = []
    if t == "totals" and line is not None and fh["n"] >= 5 and fa["n"] >= 5:
        over = o.startswith(("más", "mas", "over"))
        exp = (fh["pf"] + fa["pa"]) / 2 + (fa["pf"] + fh["pa"]) / 2
        summary = (f"Duelo que proyecta {'muchos' if exp > float(line) else 'pocos'} puntos: "
                   f"{'ataques' if over else 'defensas'} que pesan más que la línea de {float(line):g} 📊")
        facts.append(f"{H['name']} anota {fh['pf']:.1f} y recibe {fh['pa']:.1f} por partido 🏀")
        facts.append(f"{A['name']} anota {fa['pf']:.1f} y recibe {fa['pa']:.1f} 🎯")
        facts.append(f"Proyección simple: {exp:.1f} puntos (línea {float(line):g}) {'✅' if (exp > float(line)) == over else '⚠️'}")
    elif side:
        me, op = (H, A) if side == "home" else (A, H)
        fm, fo = (fh, fa) if side == "home" else (fa, fh)
        summary = (f"{me['name']} llega {'mejor' if fm['margin'] >= fo['margin'] else 'con la cuota a favor'}: "
                   f"diferencia media de {fm['margin']:+.1f} puntos contra {fo['margin']:+.1f} del rival 📊")
        facts.append(f"{me['name']}: {fm['w']}-{fm['n'] - fm['w']} en sus últimos {fm['n']}"
                     + (f" ({fm['streak']})" if fm["streak"] else "") + " ✅")
        if me.get("espn_prob"):
            facts.append(f"El pronóstico de ESPN le da {pct(me['espn_prob'])} de ganar 🎯")
        rd = op.get("rest_days")
        if rd is not None and rd < 1.6:
            facts.append(f"{op['name']} juega en back-to-back: menos piernas 📉")
        outs = [i["name"] for i in op.get("injuries") or [] if (i.get("status") or "").lower() in ("out", "doubtful")]
        if outs:
            facts.append(f"Bajas de {op['name']}: {', '.join(outs[:3])} 🚑")
    else:
        return "", []
    return summary, facts


# ---------------------------------------------------------------- texto final
def body(pick: dict) -> str:
    """Resumen + 3 datos + probabilidad (HTML de Telegram), para ir dentro del texto del pick."""
    legs = pick["legs"]
    blocks = []
    for l in legs:
        sport = l.get("sport") or "soccer"
        summary, facts = (_nba(l) if sport == "basketball" else _soccer(l))
        if len(legs) > 1:
            blocks.append(f"<b>{escape(outcome_label(l))}</b> · {escape(l['home'])} vs {escape(l['away'])}")
        if not summary:
            summary = (f"Elegimos {escape(outcome_label(l))} porque la cuota está "
                       + ("por encima de lo que vale" if l.get("edge", 0) >= config.MIN_EDGE else "en su precio justo")
                       + " según nuestro modelo 📊")
            facts = [f"Cuota justa estimada: {odds(l['fair_odds'])} · cuota disponible: {odds(l['price'])} 💎"]
            fp = 1 / l["fair_odds"] if l.get("fair_odds") else None
            o = str(l.get("outcome", "")).lower()
            if fp:
                facts.append(f"El mercado de referencia le da {pct(fp)} de probabilidad a este resultado 📊")
            if o == "1" and l.get("mtype") in ("1x2", "drawnobet", "moneyline", "spreads"):
                facts.append(f"{escape(l['home'])} juega de local 🏟")
        blocks.append(f"🧠 {summary}")
        blocks += [f"• {f}" for f in facts[:3]]
    edge = pick.get("edge", 0)
    blocks.append(f"📈 <b>Probabilidad estimada: {pct(pick['prob'])}</b> · a cuota {odds(pick['price'])} "
                  f"alcanza con {pct(1 / pick['price'])}" + (f" (valor +{pct(edge)})" if edge >= config.MIN_EDGE else ""))
    return "\n\n".join(blocks)
