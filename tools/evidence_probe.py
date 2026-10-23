"""Buscar una fuente de H2H que funcione: API-Football (respuesta cruda) y calendarios de ESPN por temporada."""
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import apifootball, config, espn  # noqa: E402

out = []
fx = apifootball.find_fixture("CD Junior FC", "Aguilas Doradas Rionegro", "2026-10-24")
hid, aid = fx["teams"]["home"]["id"], fx["teams"]["away"]["id"]
r = requests.get(f"{apifootball.BASE}/fixtures/headtohead", params={"h2h": f"{hid}-{aid}", "last": 10},
                 headers={"x-apisports-key": config.APIFOOTBALL_KEY}, timeout=30).json()
out.append("API-Football h2h errors: " + json.dumps(r.get("errors")) + f" results={r.get('results')}")
for season in (2024, 2023):
    r = requests.get(f"{apifootball.BASE}/fixtures/headtohead", params={"h2h": f"{hid}-{aid}", "season": season},
                     headers={"x-apisports-key": config.APIFOOTBALL_KEY}, timeout=30).json()
    out.append(f"API-Football h2h season {season}: errors={json.dumps(r.get('errors'))} results={r.get('results')}")
found = espn._find("CD Junior FC", "Aguilas Doradas Rionegro", "2026-10-24T01:10:00Z")
e, c, h, a = found
tid = h["team"]["id"]
out.append(f"ESPN ids: junior {tid} aguilas {a['team']['id']} uid {e.get('uid')}")
league_id = e.get("uid", "").split("~l:")[1].split("~")[0] if "~l:" in e.get("uid", "") else ""
sm = requests.get("https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary", params={"event": e["id"]}, timeout=25).json()
out.append("season name: " + str((sm.get("header") or {}).get("season")))
out.append("seasonseries: " + json.dumps(sm.get("seasonseries"))[:800])
urls = [
    f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{tid}/schedule",
    f"https://site.api.espn.com/apis/site/v2/sports/soccer/col.1/teams/{tid}/schedule?season=2025",
    f"https://site.api.espn.com/apis/site/v2/sports/soccer/col.1/teams/{tid}/schedule?season=2024",
    f"https://site.web.api.espn.com/apis/site/v2/sports/soccer/all/teams/{tid}/schedule?season=2025",
    f"https://sports.core.api.espn.com/v2/sports/soccer/leagues/{league_id}",
]
for u in urls:
    try:
        j = requests.get(u, timeout=25).json()
        evs = j.get("events") or []
        out.append(f"{u} -> keys {list(j.keys())[:8]} events {len(evs)} slug {j.get('slug') or (j.get('season') or {})}")
        if evs:
            out.append("   ej: " + json.dumps([(x.get('date'), x.get('name')) for x in evs[:3]]))
    except Exception as ex:  # noqa: BLE001
        out.append(f"{u} -> {ex}")
os.makedirs("data/probe", exist_ok=True)
open("data/probe/evidence.txt", "w").write("\n".join(out))
print("\n".join(out))
