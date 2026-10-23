"""¿Qué trae ESPN de cara a cara (H2H) en un partido de fútbol por jugarse?"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import espn  # noqa: E402

out = []
S = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary"
for k in (0, 1):
    day = (datetime.now(timezone.utc) + timedelta(days=k)).strftime("%Y%m%d")
    for e in espn._scoreboard(day, "soccer")[:60]:
        if "Junior" in e.get("name", "") or "Aguilas" in e.get("name", "") or "Águilas" in e.get("name", ""):
            out.append("JUNIOR: " + e["name"] + " " + e["id"])
    evs = [e for e in espn._scoreboard(day, "soccer") if e["status"]["type"]["state"] == "pre"][:3]
    for e in evs:
        sm = requests.get(S, params={"event": e["id"]}, timeout=25).json()
        out.append(f"== {e['name']} keys: {sorted(sm.keys())}")
        for key in sm:
            if "head" in key.lower() or "h2h" in key.lower() or "versus" in key.lower():
                out.append(f"   {key}: {json.dumps(sm[key])[:1500]}")
        lf = sm.get("lastFiveGames") or []
        if lf:
            out.append("   lastFive[0] events: " + json.dumps([(x.get('gameDate'), x.get('score'), x.get('atVs'), x.get('gameResult')) for x in lf[0].get('events') or []]))
    if evs:
        break
os.makedirs("data/probe", exist_ok=True)
open("data/probe/h2h.txt", "w").write("\n".join(out))
print("\n".join(out))
