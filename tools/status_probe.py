"""Diagnóstico (no envía nada): cuota de OddsPapi, picks de los últimos días y cuotas de ESPN disponibles hoy."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import timedelta
from sv import oddspapi, store, espn, nba  # noqa: E402
out = {}
out["quota"] = oddspapi.quota_text()
try:
    oddspapi.upcoming_fixtures(store._iso(store.now_utc()) if hasattr(store, "_iso") else store.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
                               (store.now_utc() + timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    out["fixtures_call"] = "ok"
except Exception as e:
    out["fixtures_call"] = str(e)[:200]
st = store.load()
since = (store.now_utc() - timedelta(days=12)).isoformat()
out["picks"] = [{k: p.get(k) for k in ("id", "status", "kind", "price", "created_at", "published_at", "result", "free", "kickoff", "channel_msgs")} | {"label": p["legs"][0].get("label"), "score": p["legs"][0].get("score"), "live": p.get("live_score")}
                | {"match": f"{p['legs'][0].get('home')} vs {p['legs'][0].get('away')}"}
                for p in state_picks if (p.get("created_at") or "") >= since] if (state_picks := list(st["picks"].values())) else []
out["auto_free"] = st.get("auto_free")
out["keys"] = sorted(k for k in st.keys())
day = store.now_utc().strftime("%Y%m%d")
odds = []
for e in espn._scoreboard(day, "soccer")[:200]:
    c = (e.get("competitions") or [{}])[0]
    if c.get("odds"):
        o = c["odds"][0] or {}
        odds.append({"name": e.get("name"), "date": e.get("date"), "provider": (o.get("provider") or {}).get("name"),
                     "home": (o.get("homeTeamOdds") or {}).get("moneyLine"), "away": (o.get("awayTeamOdds") or {}).get("moneyLine"),
                     "draw": (o.get("drawOdds") or {}).get("moneyLine"), "ou": o.get("overUnder")})
out["espn_soccer_with_odds"] = len(odds)
out["espn_soccer_sample"] = odds[:15]
out["espn_soccer_raw"] = next((c for e in espn._scoreboard(day, "soccer") for c in [(e.get("competitions") or [{}])[0]] if c.get("odds")), {}).get("odds")
nb = []
for e in nba._get("/scoreboard", dates=day).get("events") or []:
    c = (e.get("competitions") or [{}])[0]
    o = (c.get("odds") or [{}])[0] or {}
    nb.append({"name": e.get("name"), "date": e.get("date"), "details": o.get("details"), "ou": o.get("overUnder"),
               "home_ml": (o.get("homeTeamOdds") or {}).get("moneyLine"), "away_ml": (o.get("awayTeamOdds") or {}).get("moneyLine")})
out["nba"] = nb
os.makedirs("data/probe", exist_ok=True)
json.dump(out, open("data/probe/status.json", "w"), ensure_ascii=False, indent=1, default=str)
print("ok")
try:
    from sv import main as M, apifootball
    p = st["picks"].get(os.environ.get("PID", "383"))
    l = p["legs"][0]
    out2 = {"apifootball": str(apifootball.final_score(l["home"], l["away"], l["kickoff"])),
            "espn_final": str(M._espn_final(l))}
    r = espn.live_report(l["home"], l["away"], l["kickoff"])
    out2["espn_live"] = {k: r.get(k) for k in ("state", "status_name", "clock")} | {"score": [r["home"]["score"], r["away"]["score"]]} if r else None
    out2["grade"] = str(M._grade(p))
except Exception as e:
    out2 = {"err": repr(e)}
json.dump(out2, open("data/probe/grade.json", "w"), ensure_ascii=False, indent=1, default=str)
print(out2)
