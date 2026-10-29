"""NBA de hoy: cuotas de ESPN (DraftKings), predictor, forma, ausencias clave y hit rates de cada línea."""
import json, os, sys
from datetime import timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import nba, nbadata, store  # noqa: E402
now = store.now_utc()
day = (now - timedelta(hours=6)).strftime("%Y%m%d")
out = []
for e in nba._get("/scoreboard", dates=day).get("events") or []:
    comp = e["competitions"][0]
    cs = {c["homeAway"]: c for c in comp["competitors"]}
    g = {"game": e["name"], "date": e["date"], "state": comp["status"]["type"].get("state"),
         "odds": [{k: o.get(k) for k in ("details", "overUnder", "spread", "provider")} | {
             "home_ml": (o.get("homeTeamOdds") or {}).get("moneyLine"), "away_ml": (o.get("awayTeamOdds") or {}).get("moneyLine")}
                  for o in comp.get("odds") or []]}
    try:
        ctx = nba.context(cs["home"]["team"]["displayName"], cs["away"]["team"]["displayName"], e["date"])
        if ctx:
            g["ctx"] = {s: {k: ctx[s].get(k) for k in ("name", "record", "home_rec", "road_rec", "form", "streak", "injuries")
                            if k in ctx[s]} for s in ("home", "away") if s in ctx}
            g["predictor"] = ctx.get("predictor")
            nbadata.key_absences(ctx, e["date"])
            g["key_out"] = ctx.get("key_out")
            od = (comp.get("odds") or [{}])[0]
            sp = od.get("spread")
            ou = od.get("overUnder")
            checks = {}
            for lbl, l in (("home_ml", {"mtype": "moneyline", "outcome": "1"}), ("away_ml", {"mtype": "moneyline", "outcome": "2"}),
                           ("home_spread", {"mtype": "spreads", "outcome": "1", "handicap": sp}),
                           ("away_spread", {"mtype": "spreads", "outcome": "2", "handicap": -sp if sp is not None else None}),
                           ("over", {"mtype": "totals", "outcome": "Más", "handicap": ou}),
                           ("under", {"mtype": "totals", "outcome": "Menos", "handicap": ou})):
                try:
                    ev = nbadata.check(dict(l, home=cs["home"]["team"]["displayName"], away=cs["away"]["team"]["displayName"],
                                            sport="basketball"), ctx)
                    checks[lbl] = ev and {k: ev.get(k) for k in ("hits", "n", "rate", "txt") if k in ev}
                except Exception as x:  # noqa: BLE001
                    checks[lbl] = str(x)[:100]
            g["hit_rates"] = checks
    except Exception as x:  # noqa: BLE001
        g["error"] = str(x)[:200]
    out.append(g)
os.makedirs("data/probe", exist_ok=True)
json.dump(out, open("data/probe/nba_today.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(out, ensure_ascii=False, default=str)[:3000])
