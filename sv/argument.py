"""El «por qué» de cada pick, en palabras simples y con datos reales del partido.

    🎯 Pick: Gana Universidad de Chile @ 1.70

    🧠 Por qué:
    • La U ganó 4 de sus últimos 5 partidos de local.
    • Everton ganó solo 1 de sus últimos 5.
    • En el cara a cara, la U ganó 3 de los últimos 5.

    📈 Le damos un 58% de probabilidad.
    💰 Stake 4/10: apuesta el 2% de tu bankroll (tu fondo para apostar). Si tienes $100.000, son $2.000.

Solo se escriben hechos que respaldan el pick y que salen de los datos (ESPN para forma, localía,
cara a cara y tabla; ESPN para la NBA). Nada de jerga (cuota justa, mercado de referencia, valor):
eso queda en el mensaje que le llega al dueño para aprobar.
"""
from __future__ import annotations

from .formatting import _line, escape, public_label, team


def prob_text(p: float) -> str:
    return f"{round(p * 100)}%"


def money(n: float) -> str:
    return "$" + f"{int(round(n)):,}".replace(",", ".")


def stake_line(stake: int) -> str:
    return f"💰 <b>Stake {stake}/10</b>"


SHORT = {"Universidad de Chile": "la U", "Universidad Católica": "la UC", "Universidad de Concepción": "la UdeC",
         "Unión Española": "Unión Española", "Colo-Colo": "Colo-Colo"}
GENERIC = {"universidad", "club", "real", "deportivo", "deportes", "atlético", "atletico", "unión", "union", "sporting",
           "inter", "athletic", "racing", "independiente", "san", "santa", "rayo", "red", "borussia", "bayer",
           "manchester", "west", "aston", "nottingham", "crystal", "sheffield", "newcastle", "paris", "olympique",
           "new", "los", "las", "el", "la", "cd", "cf", "fc", "ac", "sc", "ca", "audax", "o'higgins"}


def short(name: str) -> str:
    """Nombre corto para no repetir el nombre completo en cada línea («Everton Viña del Mar» → «Everton»).
    El nombre completo ya va en el título del partido."""
    n = team(name)
    if n in SHORT:
        return SHORT[n]
    w = n.split()
    if len(w) >= 3 and w[0].lower() not in GENERIC and w[1].lower() not in ("de", "del"):
        return w[0]
    return n


def _cap(t: str) -> str:
    return t[:1].upper() + t[1:] if t else t


# ---------------------------------------------------------------- fútbol
def _games(l: dict) -> tuple[list, list, list]:
    """(local, visita, cara a cara): partidos como (goles propios, del rival, ¿de local?), del más nuevo al más viejo.
    El cara a cara va desde el lado del local del pick."""
    raw = (l.get("evidence") or {}).get("raw") or {}
    H, A, h2h = raw.get("home") or [], raw.get("away") or [], raw.get("h2h") or []
    ctx = l.get("context") or {}
    if len(H) < 3 and ctx.get("v") == 2 and isinstance(ctx.get("home"), list):
        H = [(m["gf"], m["ga"], m.get("venue") == "L") for m in ctx["home"]]
    if len(A) < 3 and ctx.get("v") == 2 and isinstance(ctx.get("away"), list):
        A = [(m["gf"], m["ga"], m.get("venue") == "L") for m in ctx["away"]]
    fix = lambda ms: [(int(m[0]), int(m[1]), (m[2] if len(m) > 2 else None)) for m in ms]  # noqa: E731
    return fix(H), fix(A), [(int(a), int(b)) for a, b in h2h]


def _n(k: int, one: str, many: str) -> str:
    return f"{k} {one if k == 1 else many}"


def _soccer(l: dict) -> list[str]:
    H, A, h2h = _games(l)
    hn, an = escape(short(l["home"])), escape(short(l["away"]))
    t, o, line = l.get("mtype", ""), str(l.get("outcome", "")).strip().lower(), l.get("handicap")
    ev = l.get("evidence") or {}
    table = ev.get("table") or {}
    facts: list[tuple[int, str]] = []   # (prioridad, texto): menor = va primero

    side = {"1": "home", "2": "away"}.get(o) if t in ("1x2", "drawnobet", "spreads") else None
    if side:
        hh = 0.0
        if t == "spreads" and line is not None:
            hh = float(line) if o == "1" else -float(line)
        me, op = (H, A) if side == "home" else (A, H)
        mn, on = (hn, an) if side == "home" else (an, hn)
        at_home = side == "home"
        where = "de local" if at_home else "de visita"
        mine_h2h = h2h if side == "home" else [(b, a) for a, b in h2h]
        if hh > 0:   # gana o empata: lo que cuenta es no perder
            ok = lambda g: g[0] >= g[1]  # noqa: E731
            say = lambda k, n, tail: (f"{mn} no perdió en sus últimos {n} {tail}." if k == n  # noqa: E731
                                      else f"{mn} no perdió en {k} de sus últimos {n} {tail}.")
            say_h2h = lambda k, n: f"En el cara a cara, {mn} no perdió en {k} de los últimos {n}."  # noqa: E731
        elif hh <= -1.5:
            need = int(-hh) + 1 if hh % 1 else int(-hh)
            ok = lambda g: g[0] - g[1] >= need  # noqa: E731
            say = lambda k, n, tail: f"{mn} ganó por {need} goles o más en {k} de sus últimos {n} {tail}."  # noqa: E731
            say_h2h = lambda k, n: f"En el cara a cara, {mn} ganó por {need} o más en {k} de los últimos {n}."  # noqa: E731
        else:
            ok = lambda g: g[0] > g[1]  # noqa: E731
            say = lambda k, n, tail: (f"{mn} ganó sus últimos {n} {tail}." if k == n  # noqa: E731
                                      else f"{mn} ganó {k} de sus últimos {n} {tail}.")
            say_h2h = lambda k, n: f"En el cara a cara, {mn} ganó {k} de los últimos {n}."  # noqa: E731
        venue = [g for g in me if g[2] is (True if at_home else False)][:5]
        if len(venue) >= 3:
            k = sum(map(ok, venue))
            if k * 2 > len(venue):
                facts.append((1, say(k, len(venue), f"partidos {where}")))
        last = me[:5]
        if len(last) >= 4 and not any(pr == 1 for pr, _f in facts):   # la forma de local/visita ya lo dice
            k = sum(map(ok, last))
            if k * 2 > len(last):
                facts.append((4, say(k, len(last), "partidos")))
        olast = op[:5]
        if len(olast) >= 4:
            w = sum(g[0] > g[1] for g in olast)
            lost = sum(g[0] < g[1] for g in olast)
            if w <= 1:
                facts.append((2, f"{on} ganó {'solo 1' if w == 1 else 'ninguno'} de sus últimos {len(olast)} partidos."))
            elif lost * 2 > len(olast):
                facts.append((2, f"{on} perdió {lost} de sus últimos {len(olast)} partidos."))
        if len(mine_h2h) >= 3:
            k = sum(map(ok, mine_h2h))
            if k * 2 > len(mine_h2h):
                facts.append((0, say_h2h(k, len(mine_h2h))))
        tm, to = table.get(side), table.get("away" if side == "home" else "home")
        if tm and to and tm.get("rank") and to.get("rank") and tm["rank"] < to["rank"]:
            facts.append((3, f"En la tabla, {mn} va {tm['rank']}º y {on}, {to['rank']}º."))
    elif t in ("totals", "teamtotals-team1", "teamtotals-team2") and line is not None:
        over = o.startswith(("más", "mas", "over"))
        lim = float(line)
        word = f"{'más' if over else 'menos'} de {_line(line)} goles"
        if t == "totals":
            hit = lambda g: ((g[0] + g[1]) > lim) == over and (g[0] + g[1]) != lim  # noqa: E731
            for pr, nm, ms in ((1, hn, H[:5]), (2, an, A[:5])):
                if len(ms) >= 4:
                    k = sum(map(hit, ms))
                    if k * 2 > len(ms):
                        facts.append((pr, f"Hubo {word} en {k} de los últimos {len(ms)} partidos de {nm}."))
            if len(h2h) >= 3:
                k = sum(map(hit, h2h))
                if k * 2 > len(h2h):
                    facts.append((0, f"En los últimos {len(h2h)} cruces entre ellos, hubo {word} en {k}."))
            both = H[:5] + A[:5]
            if len(both) >= 8:
                avg = sum(g[0] + g[1] for g in both) / len(both)
                if (avg > lim) == over:
                    facts.append((3, f"Sus últimos partidos promedian {avg:.1f} goles.".replace(".", ",", 1)))
        else:
            mine = t.endswith("1")
            nm, ms = (hn, H[:5]) if mine else (an, A[:5])
            hit = lambda g: (g[0] > lim) == over and g[0] != lim  # noqa: E731
            if len(ms) >= 4:
                k = sum(map(hit, ms))
                if k * 2 > len(ms):
                    facts.append((1, f"{nm} marcó {word} en {k} de sus últimos {len(ms)} partidos."))
            rival = A[:5] if mine else H[:5]
            if len(rival) >= 4:
                k = sum(((g[1] > lim) == over and g[1] != lim) for g in rival)
                if k * 2 > len(rival):
                    facts.append((2, f"{an if mine else hn} recibió {word} en {k} de sus últimos {len(rival)}."))
            hh2 = h2h if mine else [(b, a) for a, b in h2h]
            if len(hh2) >= 3:
                k = sum(map(hit, hh2))
                if k * 2 > len(hh2):
                    facts.append((0, f"En los últimos {len(hh2)} cruces, {nm} marcó {word} en {k}."))
    elif t == "bothteamsscore":
        yes = o.startswith(("s", "y"))
        hit = lambda g: (g[0] > 0 and g[1] > 0) == yes  # noqa: E731
        what = "marcaron los dos equipos" if yes else "al menos uno se quedó sin marcar"
        for pr, nm, ms in ((1, hn, H[:5]), (2, an, A[:5])):
            if len(ms) >= 4:
                k = sum(map(hit, ms))
                if k * 2 > len(ms):
                    facts.append((pr, f"En {k} de los últimos {len(ms)} partidos de {nm}, {what}."))
        if len(h2h) >= 3:
            k = sum(map(hit, h2h))
            if k * 2 > len(h2h):
                facts.append((0, f"En los últimos {len(h2h)} cruces entre ellos, {what} en {k}."))
    facts.sort(key=lambda x: x[0])
    return [_cap(f) for _p, f in facts]


# ---------------------------------------------------------------- NBA
def _nick(t: dict) -> str:
    """NBA: el apodo basta («Boston Celtics» → «Celtics»; «Portland Trail Blazers» → «Trail Blazers»)."""
    n = t.get("name") or ""
    return " ".join(n.split()[-2:]) if n.endswith("Trail Blazers") else n.split()[-1] if n else n


def _nba(l: dict) -> list[str]:
    """Hechos que respaldan el pick NBA: cuántas veces se habría cumplido, localía, bajas que pesan, descanso."""
    from . import nbadata
    ctx = l.get("nba_ctx")
    if not ctx:
        return []
    t, o, line = l.get("mtype", ""), str(l.get("outcome", "")).lower(), l.get("handicap")
    fns = nbadata.hit_fns(l)
    side = nbadata._side(l) or "home"
    me, op = (ctx["home"], ctx["away"]) if side == "home" else (ctx["away"], ctx["home"])
    mn, on = _nick(me), _nick(op)
    gm, go = (me.get("games") or [])[:10], (op.get("games") or [])[:10]
    facts: list[tuple[int, str]] = []
    if fns and len(gm) >= 5 and len(go) >= 5:
        km, ko = sum(map(fns[0], gm)), sum(map(fns[1], go))
        if t == "spreads" and line is not None:
            hh = nbadata._line_for_team(l)
            k = nbadata.need_txt(hh)
            if hh > 0:   # puede perder por menos de k
                m_txt = f"{mn} no perdió por {k} o más en {km} de sus últimos {len(gm)} partidos."
                o_txt = f"{on} ganó por {k} o más solo en {len(go) - ko} de sus últimos {len(go)}."
            else:
                m_txt = f"{mn} ganó por {k} o más en {km} de sus últimos {len(gm)} partidos."
                o_txt = f"{on} perdió por {k} o más en {ko} de sus últimos {len(go)}."
        elif t == "moneyline":
            m_txt = f"{mn} ganó {km} de sus últimos {len(gm)} partidos."
            o_txt = f"{on} perdió {ko} de sus últimos {len(go)}."
        elif t == "totals":
            word = f"{'más' if o.startswith(('más', 'mas', 'over')) else 'menos'} de {float(line):g} puntos"
            m_txt = f"Hubo {word} en {km} de los últimos {len(gm)} partidos de {mn}."
            o_txt = f"Y en {ko} de los últimos {len(go)} de {on}."
        else:
            word = f"{'más' if o.startswith(('más', 'mas', 'over')) else 'menos'} de {float(line):g} puntos"
            m_txt = f"{mn} anotó {word} en {km} de sus últimos {len(gm)} partidos."
            o_txt = f"{on} recibió {word} en {ko} de sus últimos {len(go)}."
        if km * 2 > len(gm):
            facts.append((0, m_txt))
        if ko * 2 > len(go):
            facts.append((1, o_txt))
        venue = [g for g in gm if g.get("home") is (side == "home")]
        if t != "totals" and len(venue) >= 3:
            kv = sum(map(fns[0], venue))
            if kv * 2 > len(venue) and kv != km:
                where = "de local" if side == "home" else "de visita"
                facts.append((3, f"{where.capitalize()}, se cumplió en {kv} de sus últimos {len(venue)}."))
    outs = op.get("key_out") or []
    if outs and t != "totals":
        names = ", ".join(f"{x['name']} ({x['pts']:g} pts por partido)".replace(".", ",") for x in outs[:2])
        facts.append((2, f"{on} no tendrá a {names}."))
    rd = op.get("rest_days")
    if rd is not None and rd < 1.6 and t != "totals":
        facts.append((4, f"{on} jugó anoche: llega con menos descanso."))
    if t == "moneyline" and me.get("espn_prob") and me["espn_prob"] >= 0.5:
        facts.append((5, f"El pronóstico de ESPN le da {prob_text(me['espn_prob'])} de ganar."))
    facts.sort(key=lambda x: x[0])
    return [f for _p, f in facts]


def _market_fallback(pick: dict, l: dict) -> list[str]:
    """Sin datos del partido: se explica con lo que dicen las casas, en simple."""
    out = []
    fp = 1 / l["fair_odds"] if l.get("fair_odds") else pick.get("prob")
    if fp and fp >= 0.5:
        out.append(f"Para las casas de apuestas es el resultado más probable ({prob_text(fp)}).")
    o = str(l.get("outcome", "")).lower()
    if o == "1" and l.get("mtype") in ("1x2", "drawnobet", "spreads", "moneyline"):
        out.append(f"{escape(team(l['home']))} juega de local.")
    return out


def facts(pick: dict, l: dict) -> list[str]:
    sport = l.get("sport") or "soccer"
    fs = _nba(l) if sport == "basketball" else _soccer(l)
    if len(fs) < 2:
        fs += [f for f in _market_fallback(pick, l) if f not in fs]
    return fs[:3]


def shown_prob(pick: dict) -> float:
    """Probabilidad que se publica: mercado + datos (la misma que usa el bot para elegir)."""
    if len(pick["legs"]) == 1 and pick["legs"][0].get("sport") == "basketball":
        from . import nbadata
        return nbadata.blend(pick["prob"], pick["legs"][0].get("nba_ev"))
    if len(pick["legs"]) == 1 and (pick["legs"][0].get("sport") or "soccer") == "soccer":
        from . import evidence
        return evidence.blend(pick["prob"], pick["legs"][0].get("evidence"))
    return pick["prob"]


def body(pick: dict) -> str:
    """«Por qué» + probabilidad + stake (HTML de Telegram), para ir bajo el pick."""
    legs = pick["legs"]
    out = []
    for l in legs:
        fs = facts(pick, l)
        head = "🧠 <b>Por qué:</b>" if len(legs) == 1 else f"🧠 <b>Por qué {escape(public_label(l))}:</b>"
        if fs:
            out.append(head + "\n" + "\n".join(f"• {f}" for f in fs))
    out.append(f"📈 Le damos un {prob_text(shown_prob(pick))} de probabilidad.\n" + stake_line(pick["stake"]))
    return "\n\n".join(out)
