"""Contraste real del pick #54 (Junior vs Águilas) con forma reciente y cara a cara de ESPN."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import evidence  # noqa: E402

leg = {"home": "CD Junior FC", "away": "Aguilas Doradas Rionegro", "kickoff": "2026-10-24T01:10:00Z", "sport": "soccer",
       "mtype": "teamtotals-team1", "outcome": "Menos", "handicap": 1.5}
fh, fa, h2h = evidence._espn(leg["home"], leg["away"], leg["kickoff"])
out = [f"forma Junior ({len(fh)}): {fh}", f"forma Águilas ({len(fa)}): {fa}", f"cara a cara ({len(h2h)}): {h2h}"]
for mt, o, ln in (("teamtotals-team1", "Menos", 1.5), ("totals", "Menos", 1.5), ("totals", "Más", 1.5),
                  ("totals", "Menos", 2.5), ("totals", "Menos", 3.5), ("bothteamsscore", "Sí", None), ("1x2", "1", None)):
    ev = evidence.check(dict(leg, mtype=mt, outcome=o, handicap=ln))
    out.append(f"{mt} {o} {ln}: {evidence.line(ev)}  (rate {ev and ev['rate']})")
os.makedirs("data/probe", exist_ok=True)
open("data/probe/evidence.txt", "w").write("\n".join(out))
print("\n".join(out))
