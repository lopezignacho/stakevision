"""Planteles actuales (NBA y fútbol) y datos de tabla/alineación que entrega ESPN."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import espn, nba  # noqa: E402

out = []
r = nba._get("/teams/2/roster")
ath = r.get("athletes") or []
names = [a.get("displayName") for a in ath] if ath and isinstance(ath[0], dict) and "displayName" in ath[0] else \
    [x.get("displayName") for g in ath for x in (g.get("items") or [])]
out.append(f"Celtics roster ({len(names)}): {names}")
out.append("Jaylen Brown en Celtics: " + str("Jaylen Brown" in names))
# fútbol: resumen de un partido de mañana: standings, leaders, rosters
S = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary"
day = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y%m%d")
evs = [e for e in espn._scoreboard(day, "soccer") if "premier" in json.dumps(e.get("season") or {}).lower()
       or "laliga" in json.dumps(e.get("season") or {}).lower()][:1] or espn._scoreboard(day, "soccer")[:1]
for e in evs:
    sm = requests.get(S, params={"event": e["id"]}, timeout=25).json()
    out.append(f"== {e['name']}")
    st = sm.get("standings") or {}
    out.append("standings: " + json.dumps(st)[:1200])
    out.append("leaders: " + json.dumps(sm.get("leaders"))[:900])
    ro = sm.get("rosters") or []
    out.append(f"rosters pre-partido: {[(r.get('homeAway'), len(r.get('roster') or [])) for r in ro]}")
    tid = e["competitions"][0]["competitors"][0]["team"]["id"]
    rr = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{tid}/roster", timeout=25).json()
    out.append(f"roster fútbol keys {list(rr.keys())[:6]} n={len(rr.get('athletes') or [])}")
    ath = rr.get("athletes") or []
    if ath:
        out.append("ej: " + json.dumps({k: ath[0].get(k) for k in ("id", "displayName", "position")})[:300]
                   + " stats? " + json.dumps(ath[0].get("statistics"))[:300])
os.makedirs("data/probe", exist_ok=True)
open("data/probe/roster.txt", "w").write("\n".join(out))
print("\n".join(out))
