"""Sondeo de fuentes para NBA (no publica nada). Imprime IDs y estructura, nunca claves."""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import config, oddspapi  # noqa: E402

out = {}
try:
    sports = oddspapi._get("/sports")
    out["sports"] = [s for s in sports if any(w in str(s).lower() for w in ("basket", "soccer"))][:10]
except Exception as e:  # noqa: BLE001
    out["sports_error"] = str(e)
bid = next((s.get("sportId") for s in out.get("sports", []) if "basket" in str(s).lower()), 11)
out["basket_id"] = bid
time.sleep(2.2)
tours = oddspapi._get("/tournaments", sportId=bid)
nba = [t for t in tours if "nba" in (t.get("tournamentName") or "").lower() and "usa" in (t.get("categoryName") or "").lower()]
out["nba_tournaments"] = [{k: t.get(k) for k in ("tournamentId", "tournamentName", "categoryName", "upcomingFixtures")}
                          for t in nba]
time.sleep(2.2)
mk = oddspapi._get("/markets", language="es")
bm = [m for m in mk if m.get("sportId") == bid]
types = {}
for m in bm:
    key = (m.get("marketType"), m.get("period"))
    types.setdefault(str(key), []).append(m.get("marketId"))
out["basket_market_types_n"] = len(types)
os.makedirs("data", exist_ok=True)
with open("data/markets_basketball.json", "w", encoding="utf-8") as f:
    json.dump({str(m["marketId"]): {"name": m.get("marketName"), "type": m.get("marketType"), "period": m.get("period"),
                                    "handicap": m.get("handicap"), "playerProp": m.get("playerProp", False),
                                    "length": m.get("marketLength"),
                                    "outcomes": {str(o["outcomeId"]): o.get("outcomeName") for o in m.get("outcomes", [])}}
               for m in bm}, f, ensure_ascii=False, indent=1)
now = datetime.now(timezone.utc)
iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
time.sleep(2.2)
fx = oddspapi._get("/fixtures", sportId=bid, **{"from": iso(now), "to": iso(now + timedelta(hours=40))},
                   statusId=0, hasOdds="true", bookmakers=config.BOOK)
nba_ids = {t["tournamentId"] for t in nba}
fxn = [f for f in fx if f.get("tournamentId") in nba_ids]
out["nba_fixtures"] = [{k: f.get(k) for k in ("fixtureId", "participant1Name", "participant2Name", "startTime")} for f in fxn[:5]]
if nba_ids:
    time.sleep(2.2)
    od = oddspapi.odds_by_tournaments(sorted(nba_ids)[:5])
    if od:
        row = od[0]
        summ = {}
        for book, bo in row["bookmakerOdds"].items():
            summ[book] = sorted(list((bo.get("markets") or {}).keys()))[:40]
        out["sample_odds_markets"] = summ
        bmeta = {str(m["marketId"]): m for m in bm}
        out["sample_market_meta"] = {mid: {"type": bmeta.get(mid, {}).get("marketType"),
                                           "period": bmeta.get(mid, {}).get("period"),
                                           "h": bmeta.get(mid, {}).get("handicap"),
                                           "name": bmeta.get(mid, {}).get("marketName")}
                                     for mid in summ.get("pinnacle", [])[:30]}
# ESPN
E = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
for name, url in (("injuries", f"{E}/injuries"), ("news", f"{E}/news?limit=5"), ("transactions", f"{E}/transactions?limit=5"),
                  ("scoreboard", f"{E}/scoreboard")):
    try:
        j = requests.get(url, timeout=20).json()
        out[f"espn_{name}_keys"] = list(j.keys())[:12]
        if name == "injuries":
            inj = j.get("injuries") or []
            out["espn_injuries_sample"] = json.dumps(inj[:1])[:1500]
        if name == "transactions":
            out["espn_tx_sample"] = json.dumps(j)[:1200]
        if name == "news":
            out["espn_news_sample"] = [(a.get("headline"), a.get("published")) for a in (j.get("articles") or [])[:3]]
        if name == "scoreboard":
            ev = (j.get("events") or [{}])[0]
            c = (ev.get("competitions") or [{}])[0]
            out["espn_sb_sample"] = {"name": ev.get("name"), "date": ev.get("date"),
                                     "comp_keys": list(c.keys()),
                                     "competitor_keys": list(((c.get("competitors") or [{}])[0]).keys()),
                                     "stats": [(s.get("name"), s.get("displayValue")) for s in ((c.get("competitors") or [{}])[0].get("statistics") or [])][:12],
                                     "records": ((c.get("competitors") or [{}])[0].get("records")),
                                     "odds": json.dumps(c.get("odds"))[:600]}
    except Exception as e:  # noqa: BLE001
        out[f"espn_{name}_error"] = str(e)
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
