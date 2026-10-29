"""Análisis de un partido para un pick manual: cuotas Betano vs Pinnacle (justas) de todos los mercados
de goles, y evidencia de ESPN (forma, cara a cara, tabla). Uso: MATCH_TEAM=Atalanta python tools/match_probe.py"""
import json, os, sys
from datetime import timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import config, evidence, oddspapi, store  # noqa: E402
from sv.value import selections_for_fixture  # noqa: E402

team = os.environ.get("MATCH_TEAM", "Atalanta")
now = store.now_utc()
iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
out = {"team": team}
fxs = oddspapi.upcoming_fixtures(iso(now - timedelta(hours=2)), iso(now + timedelta(hours=30)))
fx = next((f for f in fxs if team.lower() in (f.get("participant1Name") or "").lower()
           or team.lower() in (f.get("participant2Name") or "").lower()), None)
out["fixture"] = fx and {k: fx.get(k) for k in ("fixtureId", "participant1Name", "participant2Name", "startTime", "tournamentId")}
if fx:
    rows = oddspapi.odds_by_tournaments([fx["tournamentId"]])
    row = next((r for r in rows if r.get("fixtureId") == fx["fixtureId"]), None)
    sels = selections_for_fixture(fx, row, oddspapi.markets()) if row else []
    out["selections"] = [{"mtype": s.mtype, "market": s.market, "outcome": s.outcome, "line": s.handicap,
                          "betano": s.price, "pinnacle": s.ref_price, "fair_prob": round(s.fair_prob, 4),
                          "edge": round(s.fair_prob * s.price - 1, 4)}
                         for s in sels if "total" in s.mtype or s.mtype in ("1x2", "bothteamsscore")]
    leg = {"home": fx["participant1Name"], "away": fx["participant2Name"], "kickoff": fx["startTime"], "sport": "soccer"}
    side = "1" if team.lower() in fx["participant1Name"].lower() else "2"
    ev = {}
    for mt, o, ln in ((f"teamtotals-team{side}", "Más", 1.5), (f"teamtotals-team{side}", "Más", 2.0),
                      (f"teamtotals-team{side}", "Más", 2.5), ("totals", "Más", 2.5), ("totals", "Más", 3.5)):
        try:
            e = evidence.check(dict(leg, mtype=mt, outcome=o, handicap=ln))
            ev[f"{mt} {o} {ln}"] = {"line": evidence.line(e), "rate": e and e.get("rate"), "raw": e and e.get("raw")}
        except Exception as x:  # noqa: BLE001
            ev[f"{mt} {o} {ln}"] = str(x)
    out["evidence"] = ev
os.makedirs("data/probe", exist_ok=True)
json.dump(out, open("data/probe/match.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(out, ensure_ascii=False, default=str)[:4000])
