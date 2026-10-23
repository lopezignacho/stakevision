"""Contraste real del pick #54 (Junior vs Águilas) con H2H y forma reciente."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import apifootball, evidence  # noqa: E402

out = []
leg = {"home": "CD Junior FC", "away": "Aguilas Doradas Rionegro", "kickoff": "2026-10-24T01:10:00Z", "sport": "soccer",
       "mtype": "teamtotals-team1", "outcome": "Menos", "handicap": 1.5}
fx = apifootball.find_fixture(leg["home"], leg["away"], leg["kickoff"][:10])
out.append(f"fixture API-Football: {bool(fx)} {fx and (fx['teams']['home']['name'], fx['teams']['away']['name'])}")
leg["context"] = apifootball.context(leg["home"], leg["away"], leg["kickoff"])
out.append(f"contexto historial: {bool(leg['context'])} {leg['context'] and (len(leg['context']['home']), len(leg['context']['away']))}")
try:
    out.append(f"h2h: {evidence._h2h(leg['home'], leg['away'], leg['kickoff'])}")
except Exception as e:  # noqa: BLE001
    out.append(f"h2h error: {e}")
out.append(f"espn form: {evidence._espn_form(leg['home'], leg['away'], leg['kickoff'])}")
ev = evidence.check(leg)
out.append(f"evidencia: {json.dumps(ev)}")
out.append(evidence.line(ev))
os.makedirs("data/probe", exist_ok=True)
open("data/probe/evidence.txt", "w").write("\n".join(out))
print("\n".join(out))
