"""Qué «por qué» saldría (con datos de ESPN) para un pick NBA de ganador."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import argument, main, nba  # noqa: E402
home, away, team = os.environ.get("HOME_T", "Charlotte Hornets"), os.environ.get("AWAY_T", "Philadelphia 76ers"), "2"
day = nba._get("/scoreboard").get("events") or []
ko = next((e["date"] for e in day if "Hornets" in e["name"] and "76ers" in e["name"]), "2026-10-31T22:00Z")
ko = ko.replace("Z", ":00Z") if len(ko) == 17 else ko
p = {"kind": "simple", "price": 1.82, "prob": 0.549, "stake": 4,
     "legs": [{"home": home, "away": away, "kickoff": ko, "mtype": "moneyline", "outcome": team, "handicap": None,
               "sport": "basketball", "price": 1.82, "fair_odds": 1.82}]}
main._nba_ctx_pick(p)
ctx = p["legs"][0].get("nba_ctx") or {}
out = {"kickoff": ko, "facts": argument.facts(p, p["legs"][0]), "body": argument.body(p),
       "ev": p["legs"][0].get("nba_ev"), "key_out": ctx.get("key_out"),
       "records": {s: {k: (ctx.get(s) or {}).get(k) for k in ("name", "record", "home_rec", "road_rec")} for s in ("home", "away")},
       "games": {s: [(g.get("date"), g.get("opp"), g.get("pts"), g.get("opp_pts"), g.get("win")) for g in ((ctx.get(s) or {}).get("games") or [])[:10]] for s in ("home", "away")},
       "injuries": {s: (ctx.get(s) or {}).get("injuries") for s in ("home", "away")}}
os.makedirs("data/probe", exist_ok=True)
json.dump(out, open("data/probe/why.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(out, ensure_ascii=False, default=str)[:3000])
