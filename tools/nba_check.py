"""Revisión con datos reales de ESPN (sin cuotas): contexto, argumentos y resumen del día."""
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import nba  # noqa: E402

out = []
sb = nba._get("/scoreboard", dates=datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d"))
for e in (sb.get("events") or [])[:2]:
    c = e["competitions"][0]["competitors"]
    h = next(x for x in c if x["homeAway"] == "home")["team"]["displayName"]
    a = next(x for x in c if x["homeAway"] == "away")["team"]["displayName"]
    ctx = nba.context(h, a, e["date"].replace("Z", ":00Z") if len(e["date"]) == 17 else e["date"])
    out.append(f"== {h} vs {a} | ctx: {bool(ctx)}")
    if ctx:
        for side in ("home", "away"):
            t = ctx[side]
            out.append(f"  {side}: {t['name']} rec {t['record']} casa {t['home_rec']} fuera {t['road_rec']} "
                       f"juegos {len(t['games'])} descanso {t['rest_days']} prob {t['espn_prob']} "
                       f"bajas {[i['name'] + ('*' if i['key'] else '') for i in t['injuries']][:5]}")
        leg = {"mtype": "moneyline", "outcome": "1", "home": h, "away": a, "price": 1.8, "fair_odds": 1.75, "edge": 0.03}
        out.append(nba.arguments_text(leg, ctx))
        leg2 = {"mtype": "totals", "outcome": "Más", "handicap": 228.5, "home": h, "away": a, "price": 1.9,
                "fair_odds": 1.9, "edge": 0.0}
        out.append(nba.arguments_text(leg2, ctx))
out.append(nba.digest())
os.makedirs("data/probe", exist_ok=True)
open("data/probe/nba_check.txt", "w").write("\n".join(out))
print("\n".join(out))
