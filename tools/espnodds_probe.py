import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import espn, nba, store  # noqa: E402
day = store.now_utc().strftime("%Y%m%d")
ev = espn._scoreboard(day, "soccer")
out = {"n": len(ev)}
for e in ev:
    c = (e.get("competitions") or [{}])[0]
    if c.get("odds") and (c["odds"][0] or {}).get("moneyline"):
        out["soccer_event_keys"] = list(e.keys()); out["soccer_comp_keys"] = list(c.keys())
        out["soccer_league"] = {k: e.get(k) for k in ("league", "season", "uid")}
        out["soccer_odds"] = c["odds"]; break
nb = nba._get("/scoreboard", dates=day).get("events") or []
if nb:
    out["nba_odds"] = (nb[0].get("competitions") or [{}])[0].get("odds")
# liga por liga: ¿la chilena y otras tienen cuotas?
for lg in ("chi.1", "eng.1", "esp.1", "arg.1", "bra.1", "ita.1"):
    evs = espn._league_board(day, lg)
    out[f"lg_{lg}"] = [(e.get("name"), bool(((e.get("competitions") or [{}])[0].get("odds") or [None])[0])) for e in evs][:5]
os.makedirs("data/probe", exist_ok=True)
json.dump(out, open("data/probe/espnodds.json", "w"), ensure_ascii=False, indent=1)
print("ok")
