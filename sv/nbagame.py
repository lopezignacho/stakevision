"""NBA en juego y terminado (ESPN): marcador por cuarto, líderes y estadísticas, en el orden local/visita del pick.

Las estadísticas se cuentan desde la jugada a jugada (sirven igual al descanso que al final). Si la jugada a
jugada no viene, se usan los totales del boxscore.
"""
from __future__ import annotations

import re

from . import espn, nba

COUNT = ("pts", "reb", "ast", "fgm", "fga", "tpm", "tpa", "ftm", "fta", "tov")


def _blank() -> dict:
    return {k: 0 for k in COUNT}


def _names(summary: dict) -> dict:
    out = {}
    for t in (summary.get("boxscore") or {}).get("players") or []:
        for st in t.get("statistics") or []:
            for a in st.get("athletes") or []:
                ath = a.get("athlete") or {}
                if ath.get("id"):
                    out[str(ath["id"])] = {"name": ath.get("displayName") or "", "short": ath.get("shortName") or "",
                                           "team": str((t.get("team") or {}).get("id") or "")}
    return out


def count_plays(summary: dict, upto_period: int = 99) -> tuple[dict, dict]:
    """(por equipo {id: stats}, por jugador {id: stats}) hasta el período indicado (2 = medio tiempo)."""
    teams: dict[str, dict] = {}
    pl: dict[str, dict] = {}
    for p in summary.get("plays") or []:
        per = int(((p.get("period") or {}).get("number")) or 0)
        if per > upto_period:
            break
        tid = str((p.get("team") or {}).get("id") or "")
        if not tid:
            continue
        T = teams.setdefault(tid, _blank())
        typ = ((p.get("type") or {}).get("text") or "").lower()
        text = (p.get("text") or "").lower()
        parts = [str(((x.get("athlete") or {}).get("id")) or "") for x in p.get("participants") or []]
        who = parts[0] if parts else ""
        P = pl.setdefault(who, _blank()) if who else _blank()
        if p.get("shootingPlay"):
            made = bool(p.get("scoringPlay"))
            if "free throw" in typ or "free throw" in text:
                T["fta"] += 1
                P["fta"] += 1
                T["ftm"] += made
                P["ftm"] += made
            else:
                three = p.get("scoreValue") == 3 or "three point" in text or "3-pt" in text or "three pointer" in typ
                T["fga"] += 1
                P["fga"] += 1
                T["fgm"] += made
                P["fgm"] += made
                if three:
                    T["tpa"] += 1
                    P["tpa"] += 1
                    T["tpm"] += made
                    P["tpm"] += made
            if made:
                v = int(p.get("scoreValue") or 0)
                T["pts"] += v
                P["pts"] += v
                if len(parts) > 1 and parts[1] and "assist" in text:
                    pl.setdefault(parts[1], _blank())["ast"] += 1
                    T["ast"] += 1
        elif "rebound" in typ:
            T["reb"] += 1
            if who and "team" not in typ:
                P["reb"] += 1
        elif "turnover" in typ or "turnover" in text or "bad pass" in typ or "traveling" in typ:
            T["tov"] += 1
            P["tov"] += 1
    pl.pop("", None)
    return teams, pl


def _box_teams(summary: dict) -> dict:
    """Totales del boxscore por equipo (respaldo)."""
    out = {}
    for t in (summary.get("boxscore") or {}).get("teams") or []:
        tid = str((t.get("team") or {}).get("id") or "")
        s = {x.get("name"): x.get("displayValue") for x in t.get("statistics") or []}
        row = _blank()

        def pair(key):
            m = re.match(r"(\d+)-(\d+)", s.get(key) or "")
            return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        row["fgm"], row["fga"] = pair("fieldGoalsMade-fieldGoalsAttempted")
        row["tpm"], row["tpa"] = pair("threePointFieldGoalsMade-threePointFieldGoalsAttempted")
        row["ftm"], row["fta"] = pair("freeThrowsMade-freeThrowsAttempted")
        for k, name in (("reb", "totalRebounds"), ("ast", "assists"), ("tov", "turnovers")):
            try:
                row[k] = int(float(s.get(name) or 0))
            except ValueError:
                pass
        out[tid] = row
    return out


def _box_players(summary: dict) -> dict:
    out = {}
    for t in (summary.get("boxscore") or {}).get("players") or []:
        for st in t.get("statistics") or []:
            keys = [k.lower() for k in st.get("keys") or st.get("names") or []]
            for a in st.get("athletes") or []:
                vals = dict(zip(keys, a.get("stats") or []))
                pid = str((a.get("athlete") or {}).get("id") or "")

                def num(*ks):
                    for k in ks:
                        try:
                            return int(float(vals.get(k)))
                        except (TypeError, ValueError):
                            continue
                    return 0
                if pid:
                    out[pid] = dict(_blank(), pts=num("points", "pts"), reb=num("rebounds", "reb"),
                                    ast=num("assists", "ast"))
    return out


def report(home: str, away: str, kickoff_iso: str, half: bool = False) -> dict | None:
    """Estado del partido para el pick (local/visita en el orden del pick). half=True: solo los 2 primeros cuartos."""
    found = nba.find_event(home, away, kickoff_iso)
    if not found:
        return None
    e, inverted = found
    summary = nba._get("/summary", event=e.get("id"))
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    cs = comp.get("competitors") or ((e.get("competitions") or [{}])[0].get("competitors") or [])
    h = next((x for x in cs if x.get("homeAway") == "home"), {})
    a = next((x for x in cs if x.get("homeAway") == "away"), {})
    if inverted:
        h, a = a, h
    st = comp.get("status") or e.get("status") or {}
    period = int(st.get("period") or 0)
    names = _names(summary)
    upto = 2 if half else 99
    teams, players = count_plays(summary, upto)
    if not half:   # al final, los totales oficiales del boxscore mandan
        teams = _box_teams(summary) or teams
        for pid, row in _box_players(summary).items():
            players.setdefault(pid, _blank()).update({k: row[k] for k in ("pts", "reb", "ast")})

    def side(x, s):
        t = espn._side({"side": s}, x, {})
        t["lines"] = [int(float(ls.get("displayValue") or ls.get("value") or 0)) for ls in x.get("linescores") or []]
        tid = t["id"]
        t["box"] = teams.get(tid) or _blank()
        lead = sorted(((pid, r) for pid, r in players.items() if (names.get(pid) or {}).get("team") == tid),
                      key=lambda kv: (kv[1]["pts"], kv[1]["reb"] + kv[1]["ast"]), reverse=True)
        t["leaders"] = [dict(r, id=pid, name=names[pid]["name"], short=names[pid]["short"]) for pid, r in lead[:3]]
        return t
    H, A = side(h, "home"), side(a, "away")
    if half:   # al descanso: el marcador es la suma de los dos primeros cuartos
        H["score"], A["score"] = sum(H["lines"][:2]), sum(A["lines"][:2])
    return {"id": e.get("id"), "home": H, "away": A, "period": period,
            "state": (st.get("type") or {}).get("state") or "", "status_name": (st.get("type") or {}).get("name") or "",
            "clock": st.get("displayClock") or "", "completed": bool((st.get("type") or {}).get("completed")),
            "venue": ((comp.get("venue") or (e.get("competitions") or [{}])[0].get("venue") or {}).get("fullName") or "")}


def pct(m: int, a: int) -> float:
    return 100 * m / a if a else 0.0


def stat_rows(rep: dict) -> list[tuple[str, float, float, str]]:
    H, A = rep["home"]["box"], rep["away"]["box"]
    return [("% de campo", pct(H["fgm"], H["fga"]), pct(A["fgm"], A["fga"]), "%"),
            ("% de triples", pct(H["tpm"], H["tpa"]), pct(A["tpm"], A["tpa"]), "%"),
            ("Rebotes", H["reb"], A["reb"], ""), ("Asistencias", H["ast"], A["ast"], ""),
            ("Pérdidas", H["tov"], A["tov"], "")]


def line_of(p: dict) -> str:
    bits = [f"{p['pts']} PTS"]
    if p.get("reb", 0) >= 5:
        bits.append(f"{p['reb']} REB")
    if p.get("ast", 0) >= 5:
        bits.append(f"{p['ast']} AST")
    return " · ".join(bits)


def hero(rep: dict) -> tuple[dict, str] | None:
    """Figura: el máximo anotador del ganador (o del que va arriba). (jugador, lado)."""
    s = "home" if rep["home"]["score"] >= rep["away"]["score"] else "away"
    ld = rep[s]["leaders"]
    return (ld[0], s) if ld else None


def pick_status(leg: dict, rep: dict, final: bool, grade) -> tuple[str, str]:
    """(W/L/V/?, frase) de cómo va el pick NBA."""
    h, a = rep["home"]["score"], rep["away"]["score"]
    if final:
        res = grade(leg, h, a) or "?"
        head = {"W": "✅ VERDE", "L": "❌ ROJA", "V": "↩️ NULA"}.get(res, "Resultado por confirmar")
        return res, head
    t, o, line = leg.get("mtype", ""), str(leg.get("outcome", "")).lower(), leg.get("handicap")
    res = grade(leg, h, a) or "?"
    if t in ("totals", "teamtotals-team1", "teamtotals-team2") and line is not None:
        pts = h + a if t == "totals" else (h if t.endswith("1") else a)
        proj = pts * 2
        over = o.startswith(("más", "mas", "over"))
        good = (proj > float(line)) == over
        txt = f"Van {pts} puntos: al mismo ritmo terminarían cerca de {proj} (línea {float(line):g})."
        return ("W" if good else "L"), ("✅ Va bien encaminado · " if good else "⚠️ Por ahora no llega · ") + txt
    side = {"1": "home", "2": "away"}.get(o)
    if side:
        me, op = rep[side], rep["away" if side == "home" else "home"]
        diff = me["score"] - op["score"]
        if t == "spreads" and line is not None:
            adj = diff + (float(line) if side == "home" else -float(line))
            good = adj > 0
            txt = f"{me['short']} {'gana' if diff > 0 else 'pierde' if diff < 0 else 'empata'}" \
                  f"{f' por {abs(diff)}' if diff else ''}; con el hándicap iría {'arriba' if good else 'abajo'} por {abs(adj):g}."
            return ("W" if good else "L"), ("✅ " if good else "⚠️ ") + txt
        if diff > 0:
            return "W", f"✅ {me['short']} gana por {diff} al descanso."
        if diff < 0:
            return "L", f"⚠️ {me['short']} pierde por {-diff}: queda todo el 2º tiempo."
        return "?", "⏳ Empate al descanso: todo abierto."
    return res, "⏳ En juego"


# ---------------------------------------------------------------- titulares y textos
def headline(rep: dict, kind: str, half_rep: dict | None = None) -> str:
    H, A = rep["home"], rep["away"]
    d = H["score"] - A["score"]
    if kind == "half":
        if d == 0:
            return "TODO IGUAL"
        lead = H if d > 0 else A
        return f"{lead['short'].upper()} {'MANDA' if abs(d) >= 10 else 'ARRIBA'}"
    win = H if d > 0 else A
    lose = A if d > 0 else H
    name = win["short"].upper()
    if len(win.get("lines") or []) > 4:
        return f"{name} EN LA PRÓRROGA"
    if half_rep:
        hd = half_rep["home"]["score"] - half_rep["away"]["score"]
        if (d > 0 and hd <= -8) or (d < 0 and hd >= 8):
            return f"REMONTADA DE {name}"
    if abs(d) >= 20:
        return f"PALIZA DE {name}"
    if abs(d) <= 3:
        return f"{name} SUFRE Y GANA"
    return f"{name} SE LO LLEVA" if win["score"] - lose["score"] < 12 else f"{name} SIN DISCUSIÓN"


def _qline(rep: dict) -> str:
    H, A = rep["home"], rep["away"]
    n = max(len(H["lines"]), len(A["lines"]))
    lab = lambda i: f"{i + 1}C" if i < 4 else "PR"  # noqa: E731
    return " · ".join(f"{lab(i)} {H['lines'][i] if i < len(H['lines']) else 0}-{A['lines'][i] if i < len(A['lines']) else 0}"
                      for i in range(n))


def _leaders_txt(rep: dict) -> list[str]:
    out = []
    for s in ("home", "away"):
        ld = rep[s]["leaders"]
        if ld:
            out.append(f"{rep[s]['short']}: {ld[0]['name']} {line_of(ld[0])}")
    return out


def half_caption(p: dict, rep: dict, st: tuple[str, str]) -> str:
    from . import formatting
    esc = formatting.escape
    H, A = rep["home"], rep["away"]
    leg = p["legs"][0]
    lines = [f"⏸️ <b>ENTRETIEMPO NBA</b> · {esc(H['short'])} {H['score']}-{A['score']} {esc(A['short'])}",
             f"📋 {esc(_qline(rep))}", ""]
    lines += [f"🔥 {esc(x)}" for x in _leaders_txt(rep)]
    lines.append("")
    for label, hv, av, unit in stat_rows(rep):
        lines.append(f"📊 {label}: {hv:.0f}{unit} - {av:.0f}{unit}")
    lines += ["", f"🎯 Nuestro pick: <b>{esc(formatting.outcome_label(leg))}</b> @ {formatting.odds(p['price'])}",
              esc(st[1]), "", "Se vienen el 3º y el 4º cuarto 👀", "Exclusivo VIP 👑 · 🔞 +18 · Juega con responsabilidad."]
    return "\n".join(lines)


def final_caption(p: dict, rep: dict, head: str, credit: dict | None, ig: bool = False) -> str:
    from . import formatting
    esc = (lambda x: x) if ig else formatting.escape
    H, A = rep["home"], rep["away"]
    leg = p["legs"][0]
    res = p.get("result")
    fig = hero(rep)
    open_ = {"W": "✅ ¡VERDE EN LA NBA! 🏀💚", "L": "❌ Esta vez no se dio.", "V": "↩️ Pick nulo."}.get(res, "🏀 Final.")
    b = (lambda x: x) if ig else (lambda x: f"<b>{x}</b>")
    lines = [open_, "", f"{b(head)}", f"{esc(H['name'])} {H['score']} - {A['score']} {esc(A['name'])}",
             f"📋 {esc(_qline(rep))}"]
    if fig:
        lines.append(f"⭐ Figura: {esc(fig[0]['name'])} · {fig[0]['pts']} pts"
                     + (f", {fig[0]['reb']} reb" if fig[0]['reb'] >= 5 else "")
                     + (f", {fig[0]['ast']} ast" if fig[0]['ast'] >= 5 else ""))
    lines += ["", f"🎯 Nuestro pick: {b(esc(formatting.outcome_label(leg)))} @ {formatting.odds(p['price'])} "
              + {"W": "✅", "L": "❌", "V": "↩️"}.get(res, "")]
    if ig:
        lines += ["", "Los picks de NBA son exclusivos de nuestro VIP en Telegram 👑",
                  "📲 Pronóstico gratis de fútbol todos los días: t.me/stakevision"]
        if credit and credit.get("text"):
            lines += ["", f"📸 {credit['text']}"]
        lines += ["", "🔞 +18 · Juega con responsabilidad.", "",
                  f"#NBA #{re.sub(r'[^A-Za-z]', '', H['short'])} #{re.sub(r'[^A-Za-z]', '', A['short'])} "
                  "#Stakevision #Basketball"]
    else:
        lines += ["", "🔞 +18 · Juega con responsabilidad."]
    return "\n".join(lines)
