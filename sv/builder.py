"""Bet Builder: 3 líneas «fáciles» de un mismo partido, que los jugadores (o equipos) cumplen casi siempre.

Idea (la del dueño): líneas bajas que se repiten partido tras partido. Para cada jugador importante se mira
su historial reciente y se busca la línea más alta que cumplió en al menos el 80 % de sus partidos
(y en 4 de los últimos 5). Se combinan 3 de jugadores distintos.

- NBA: últimos 10 partidos de cada equipo (ESPN): puntos, rebotes, asistencias, triples. Solo jugadores con
  minutos de titular y sin lesión reportada para el partido.
- Fútbol: últimos 5 partidos de cada equipo (ESPN, sin amistosos): remates, remates al arco, faltas
  cometidas y recibidas (titulares habituales), y córners de cada equipo.

La probabilidad de cada pata se suaviza ((aciertos+1)/(partidos+2)) para no creer en el 100 %, y la
combinada multiplica las tres (sin contar que pueden estar relacionadas). La cuota real del Bet Builder la
pone la casa: el bot da la cuota mínima para que, según estos números, convenga.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import requests

from . import espn, nba

ESPN = "https://site.api.espn.com/apis/site/v2/sports"
NBA_LINES = {"pts": ([10, 12, 15, 18, 20, 22, 25, 28, 30], "puntos"),
             "reb": ([3, 4, 5, 6, 7, 8, 10, 12], "rebotes"),
             "ast": ([2, 3, 4, 5, 6, 7, 8, 10], "asistencias"),
             "tpm": ([1, 2, 3, 4, 5], "triples")}
SOCCER_LINES = {"totalShots": ([1, 2, 3, 4], "remates"),
                "shotsOnTarget": ([1, 2], "remates al arco"),
                "foulsCommitted": ([1, 2, 3], "faltas cometidas"),
                "foulsSuffered": ([1, 2, 3], "faltas recibidas")}
OUT_STATUS = ("out", "doubtful", "questionable", "suspension")


def _get(url: str, **params) -> dict:
    try:
        r = requests.get(url, params=params, timeout=25)
        return r.json() if r.ok else {}
    except Exception:  # noqa: BLE001
        return {}


def _n(v) -> int:
    try:
        return int(float(str(v).split("-")[0]))
    except (TypeError, ValueError):
        return 0


def _best_line(vals: list[int], lines: list[int], min_rate: float = 0.8, recent: int = 5) -> tuple | None:
    """(línea, aciertos, partidos) más alta que cumplió en ≥ min_rate y en casi todos los recientes."""
    n = len(vals)
    best = None
    for ln in lines:
        hits = sum(v >= ln for v in vals)
        rec = vals[:recent]
        rec_hits = sum(v >= ln for v in rec)
        if hits / n >= min_rate and rec_hits >= len(rec) - 1:
            best = (ln, hits, n)
    return best


def _p(hits: int, n: int) -> float:
    """Probabilidad prudente: el historial se mezcla con un 60 % de base (como si hubiera 4 partidos más).
    Así un 6 de 6 queda en ~84 % y no en 100 %, y las muestras cortas pesan menos."""
    return (hits + 2.4) / (n + 4)


MIN_LINE = {"pts": 10, "reb": 4, "ast": 3, "tpm": 1}   # NBA: por debajo de esto la línea no suma nada


# ---------------------------------------------------------------- NBA
def _nba_logs(team_id: str, before: datetime, n: int = 10) -> list[dict]:
    """Por partido (más reciente primero): {athlete_id: {name, min, pts, reb, ast, tpm}}."""
    now = datetime.now(timezone.utc)
    season = now.year + 1 if now.month >= 9 else now.year
    ids = []
    for s in (season, season - 1):
        evs = []
        for e in nba._get(f"/teams/{team_id}/schedule", season=s).get("events") or []:
            c = (e.get("competitions") or [{}])[0]
            if ((c.get("status") or {}).get("type") or {}).get("completed"):
                d = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
                if d < before:
                    evs.append((d, e["id"]))
        ids += [i for _d, i in sorted(evs, reverse=True)]
        if len(ids) >= n:
            break
    games = []
    for eid in ids[:n]:
        sm = nba._get("/summary", event=eid)
        rows = {}
        for t in (sm.get("boxscore") or {}).get("players") or []:
            if str((t.get("team") or {}).get("id")) != str(team_id):
                continue
            for st in t.get("statistics") or []:
                keys = st.get("keys") or []
                for a in st.get("athletes") or []:
                    v = dict(zip(keys, a.get("stats") or []))
                    ath = a.get("athlete") or {}
                    if not v or a.get("didNotPlay"):
                        continue
                    rows[str(ath.get("id"))] = {
                        "name": ath.get("displayName") or "", "min": _n(v.get("minutes")),
                        "pts": _n(v.get("points")), "reb": _n(v.get("rebounds")), "ast": _n(v.get("assists")),
                        "tpm": _n(v.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))}
        games.append(rows)
    return games


def nba_legs(home: str, away: str, kickoff_iso: str) -> tuple[list[dict], dict]:
    found = nba.find_event(home, away, kickoff_iso)
    if not found:
        return [], {}
    e, inverted = found
    comp = e["competitions"][0]["competitors"]
    teams = {x["homeAway"]: x["team"] for x in comp}
    if inverted:
        teams["home"], teams["away"] = teams["away"], teams["home"]
    sm = nba._get("/summary", event=e.get("id"))
    out_players = set()
    for t in sm.get("injuries") or []:
        for i in t.get("injuries") or []:
            if (i.get("status") or "").lower() in OUT_STATUS:
                out_players.add(str(((i.get("athlete") or {}).get("id")) or ""))
    ko = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00"))
    legs = []
    for side, team in teams.items():
        games = _nba_logs(str(team["id"]), ko)
        if len(games) < 6:
            continue
        pids = {pid for g in games for pid in g}
        for pid in pids:
            if pid in out_players:
                continue
            played = [g[pid] for g in games if pid in g and g[pid]["min"] > 0]
            if len(played) < 6 or sum(x["min"] for x in played) / len(played) < 24:
                continue
            mins = sum(x["min"] for x in played) / len(played)
            for stat, (lines, word) in NBA_LINES.items():
                best = _best_line([x[stat] for x in played], [x for x in lines if x >= MIN_LINE[stat]])
                if not best:
                    continue
                ln, hits, n = best
                avg = sum(x[stat] for x in played) / n
                legs.append({"player": played[0]["name"], "pid": pid, "team": team.get("displayName"),
                             "side": side, "stat": stat, "line": ln, "word": word, "hits": hits, "n": n,
                             "avg": round(avg, 1), "p": _p(hits, n), "min": round(mins, 1),
                             "label": f"{played[0]['name']}: {ln}+ {word}"})
    return legs, {"home": teams.get("home", {}).get("displayName"), "away": teams.get("away", {}).get("displayName"),
                  "event": e.get("id")}


# ---------------------------------------------------------------- fútbol
def _soccer_event(home: str, away: str, kickoff_iso: str):
    found = espn._find(home, away, kickoff_iso)
    return found


def soccer_legs(home: str, away: str, kickoff_iso: str) -> tuple[list[dict], dict]:
    found = _soccer_event(home, away, kickoff_iso)
    if not found:
        return [], {}
    e, _c, h, a = found
    sm = _get(f"{ESPN}/soccer/all/summary", event=e["id"])
    teams = {"home": h["team"], "away": a["team"]}
    legs = []
    for lf in sm.get("lastFiveGames") or []:
        tid = str((lf.get("team") or {}).get("id"))
        side = "home" if tid == str(teams["home"].get("id")) else "away" if tid == str(teams["away"].get("id")) else None
        if not side:
            continue
        evs = [x for x in lf.get("events") or [] if "friendly" not in (x.get("leagueName") or "").lower()]
        per_player: dict[str, list] = {}
        names: dict[str, str] = {}
        corners = []
        for ev in evs[:5]:
            s2 = _get(f"{ESPN}/soccer/all/summary", event=ev["id"])
            for ro in s2.get("rosters") or []:
                if str((ro.get("team") or {}).get("id")) != tid:
                    continue
                for pl in ro.get("roster") or []:
                    if not pl.get("starter"):
                        continue
                    ath = pl.get("athlete") or {}
                    pid = str(ath.get("id"))
                    names[pid] = ath.get("displayName") or ""
                    per_player.setdefault(pid, []).append(
                        {x.get("name"): _n(x.get("displayValue")) for x in pl.get("stats") or []})
            for tb in (s2.get("boxscore") or {}).get("teams") or []:
                if str((tb.get("team") or {}).get("id")) == tid:
                    st = {x.get("name"): x.get("displayValue") for x in tb.get("statistics") or []}
                    if st.get("wonCorners") is not None:
                        corners.append(_n(st["wonCorners"]))
        n_games = len(evs[:5])
        for pid, rows in per_player.items():
            if n_games < 4 or len(rows) < 4:
                continue   # titular habitual: al menos 4 de los últimos 5
            for stat, (lines, word) in SOCCER_LINES.items():
                vals = [r.get(stat, 0) for r in rows]
                best = _best_line(vals, lines, min_rate=0.8, recent=len(vals))
                if not best:
                    continue
                ln, hits, n = best
                legs.append({"player": names[pid], "pid": pid, "team": teams[side].get("displayName"), "side": side,
                             "stat": stat, "line": ln, "word": word, "hits": hits, "n": n,
                             "avg": round(sum(vals) / n, 1), "p": _p(hits, n),
                             "label": f"{names[pid]}: {ln}+ {word}"})
        if len(corners) >= 4:
            best = _best_line(corners, [2, 3, 4, 5, 6, 7], min_rate=0.8, recent=len(corners))
            if best:
                ln, hits, n = best
                nm = teams[side].get("displayName")
                legs.append({"player": nm, "pid": f"team-{tid}", "team": nm, "side": side, "stat": "corners",
                             "line": ln, "word": "córners", "hits": hits, "n": n,
                             "avg": round(sum(corners) / n, 1), "p": _p(hits, n), "label": f"{nm}: {ln}+ córners"})
    return legs, {"home": teams["home"].get("displayName"), "away": teams["away"].get("displayName"), "event": e["id"]}


# ---------------------------------------------------------------- elegir las 3 patas
def choose(legs: list[dict], k: int = 3, target: float = 3.0) -> dict | None:
    """3 patas de jugadores distintos (máx. 2 del mismo equipo, máx. 2 del mismo tipo de dato),
    las más seguras primero. Devuelve {legs, prob, fair, target} o None."""
    # Una línea que el jugador «regala» (muy por debajo de su promedio) no suma cuota: se prefieren
    # líneas cercanas a lo que hace siempre pero que igual cumple casi siempre.
    def score(l):
        tight = min(1.0, l["line"] / max(l["avg"], 0.1))       # línea cerca de lo que hace = paga más
        star = min(1.0, l.get("min", 34) / 34)                   # NBA: figuras con muchos minutos primero
        return l["p"] * (0.75 + 0.25 * tight) * (0.6 + 0.4 * star)
    pool = sorted(legs, key=score, reverse=True)
    pick, used, per_team, per_stat = [], set(), {}, {}
    for l in pool:
        if l["pid"] in used or per_team.get(l["side"], 0) >= 2 or per_stat.get(l["stat"], 0) >= 2:
            continue
        pick.append(l)
        used.add(l["pid"])
        per_team[l["side"]] = per_team.get(l["side"], 0) + 1
        per_stat[l["stat"]] = per_stat.get(l["stat"], 0) + 1
        if len(pick) == k:
            break
    if len(pick) < k:
        return None
    prob = 1.0
    for l in pick:
        prob *= l["p"]
    return {"legs": pick, "prob": round(prob, 4), "fair": round(1 / prob, 2), "target": target}


def suggest(home: str, away: str, kickoff_iso: str, sport: str) -> dict | None:
    legs, meta = (nba_legs if sport == "basketball" else soccer_legs)(home, away, kickoff_iso)
    b = choose(legs)
    if not b:
        return None
    b.update(meta, sport=sport, kickoff=kickoff_iso, n_candidates=len(legs))
    return b


def grade(b_leg: dict, box: dict) -> str | None:
    """'W'/'L' de una pata con el boxscore final {pid: {stat: valor}}; None si el jugador no jugó."""
    row = box.get(b_leg["pid"])
    if row is None:
        return None
    return "W" if row.get(b_leg["stat"], 0) >= b_leg["line"] else "L"


def final_box(b: dict) -> dict | None:
    """{pid: {stat: valor}} del partido terminado (o None si no terminó)."""
    if b["sport"] == "basketball":
        sm = nba._get("/summary", event=b["event"])
    else:
        sm = _get(f"{ESPN}/soccer/all/summary", event=b["event"])
    st = (((sm.get("header") or {}).get("competitions") or [{}])[0].get("status") or {}).get("type") or {}
    if not st.get("completed"):
        return None
    box: dict[str, dict] = {}
    if b["sport"] == "basketball":
        for t in (sm.get("boxscore") or {}).get("players") or []:
            for s in t.get("statistics") or []:
                keys = s.get("keys") or []
                for a in s.get("athletes") or []:
                    v = dict(zip(keys, a.get("stats") or []))
                    if v and not a.get("didNotPlay") and _n(v.get("minutes")) > 0:
                        box[str((a.get("athlete") or {}).get("id"))] = {
                            "pts": _n(v.get("points")), "reb": _n(v.get("rebounds")), "ast": _n(v.get("assists")),
                            "tpm": _n(v.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))}
    else:
        for ro in sm.get("rosters") or []:
            for pl in ro.get("roster") or []:
                stats = {x.get("name"): _n(x.get("displayValue")) for x in pl.get("stats") or []}
                if stats.get("appearances", 0) or pl.get("starter") or pl.get("subbedIn"):
                    box[str((pl.get("athlete") or {}).get("id"))] = stats
        for tb in (sm.get("boxscore") or {}).get("teams") or []:
            st2 = {x.get("name"): x.get("displayValue") for x in tb.get("statistics") or []}
            box[f"team-{(tb.get('team') or {}).get('id')}"] = {"corners": _n(st2.get("wonCorners"))}
    return box


_NUM = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*$")


def parse_odds(text: str) -> float | None:
    m = _NUM.match(text or "")
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return v if 1.2 <= v <= 50 else None


def league_name(slug: str) -> str:
    """«2026-27-english-premier-league» → «English Premier League»."""
    s = re.sub(r"^\d{4}(-\d{2,4})?-", "", slug or "")
    return s.replace("-", " ").title() if s else "Fútbol"
