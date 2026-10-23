"""Explora qué datos por jugador da ESPN (NBA y fútbol) para armar Bet Builders."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = "data/probe/props"
os.makedirs(OUT, exist_ok=True)
log = []
S = "https://site.api.espn.com/apis/site/v2/sports"


def get(url, **p):
    try:
        r = requests.get(url, params=p, timeout=25)
        return r.json() if r.ok else {"_status": r.status_code}
    except Exception as e:  # noqa: BLE001
        return {"_err": str(e)}


def keys(x, depth=0, maxd=3):
    if depth > maxd:
        return "…"
    if isinstance(x, dict):
        return {k: keys(v, depth + 1, maxd) for k, v in list(x.items())[:25]}
    if isinstance(x, list):
        return [keys(x[0], depth + 1, maxd)] if x else []
    return type(x).__name__ if not isinstance(x, (str, int, float)) else (str(x)[:40])


# NBA: un partido terminado reciente y su boxscore por jugador
day = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")
sb = get(f"{S}/basketball/nba/scoreboard", dates=day)
ev = next((e for e in sb.get("events") or [] if e["status"]["type"]["completed"]), None)
if ev:
    sm = get(f"{S}/basketball/nba/summary", event=ev["id"])
    bp = (sm.get("boxscore") or {}).get("players") or []
    if bp:
        st = bp[0]["statistics"][0]
        log.append("NBA keys: " + json.dumps(st.get("keys")))
        log.append("NBA names: " + json.dumps(st.get("names")))
        log.append("NBA ejemplo: " + json.dumps(st["athletes"][0]["athlete"].get("displayName")) + " "
                   + json.dumps(st["athletes"][0].get("stats")))
    log.append("NBA injuries sample: " + json.dumps(keys(sm.get("injuries"), 0, 4))[:600])
# NBA: game log por jugador
gl = get("https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/4278073/gamelog")
log.append("NBA gamelog top keys: " + json.dumps(list(gl.keys())[:15]))
log.append("NBA gamelog names: " + json.dumps(gl.get("names") or gl.get("labels"))[:400])

# Fútbol
sbs = get(f"{S}/soccer/all/scoreboard", dates=day)
evs = sbs.get("events") or []
log.append(f"Fútbol eventos ayer: {len(evs)}")
if evs:
    e = next((x for x in evs if x["status"]["type"]["completed"]), evs[0])
    log.append("Fútbol event keys: " + json.dumps(list(e.keys())))
    log.append("Fútbol uid: " + e.get("uid", ""))
    log.append("Fútbol season: " + json.dumps(e.get("season")))
    c = e["competitions"][0]
    log.append("Fútbol comp keys: " + json.dumps(list(c.keys())))
    log.append("Fútbol leagues top: " + json.dumps([(l.get("id"), l.get("slug"), l.get("abbreviation")) for l in sbs.get("leagues") or []][:10]))
    for slug in [l.get("slug") for l in sbs.get("leagues") or []][:40]:
        sm = get(f"{S}/soccer/{slug}/summary", event=e["id"])
        if sm.get("rosters") or sm.get("boxscore"):
            log.append(f"Fútbol summary OK con slug {slug}")
            ro = sm.get("rosters") or []
            log.append("rosters: " + json.dumps(keys(ro, 0, 5))[:1500])
            if ro and ro[0].get("roster"):
                pl = ro[0]["roster"][0]
                log.append("jugador stats: " + json.dumps([(s.get("name"), s.get("displayValue")) for s in pl.get("stats") or []]))
            tid = c["competitors"][0]["team"]["id"]
            sch = get(f"{S}/soccer/{slug}/teams/{tid}/schedule")
            log.append(f"schedule {slug}/{tid}: eventos {len(sch.get('events') or [])}")
            break
    sm2 = get(f"{S}/soccer/all/summary", event=e["id"])
    log.append("soccer/all/summary: " + json.dumps(list(sm2.keys())[:12]))
    lf = sm2.get("lastFiveGames") or []
    log.append("lastFiveGames: " + json.dumps(keys(lf, 0, 4))[:1200])
    ro = sm2.get("rosters") or []
    log.append("rosters keys: " + json.dumps(keys(ro, 0, 3))[:800])
    if ro and ro[0].get("roster"):
        for pl in ro[0]["roster"][:2]:
            log.append("jugador: " + json.dumps((pl.get("athlete") or {}).get("displayName")) + " starter=" + str(pl.get("starter"))
                       + " stats=" + json.dumps([(x.get("name"), x.get("displayValue")) for x in pl.get("stats") or []]))
    bx = (sm2.get("boxscore") or {}).get("teams") or []
    if bx:
        log.append("team stats: " + json.dumps([(x.get("name"), x.get("displayValue")) for x in bx[0].get("statistics") or []]))
    # partido próximo: ¿trae lastFiveGames y rosters antes de jugarse?
    day2 = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y%m%d")
    up = next((x for x in get(f"{S}/soccer/all/scoreboard", dates=day2).get("events") or []), None)
    if up:
        sm3 = get(f"{S}/soccer/all/summary", event=up["id"])
        lf3 = sm3.get("lastFiveGames") or []
        log.append(f"Próximo {up['name']}: lastFiveGames equipos={len(lf3)} eventos={[len(t.get('events') or []) for t in lf3]}")
        if lf3 and lf3[0].get("events"):
            log.append("evento lastFive ej: " + json.dumps(keys(lf3[0]["events"][0], 0, 2))[:600])
open(f"{OUT}/probe.txt", "w").write("\n".join(log))
print("\n".join(log))
