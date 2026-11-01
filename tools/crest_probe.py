"""Postpartido y pick con escudos OFICIALES: los 3 diseños de postpartido de un partido real."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import espn, layouts, recap  # noqa: E402
OUT = "data/probe/crest"
os.makedirs(OUT, exist_ok=True)
home, away, ko = "Istanbul Basaksehir", "Samsunspor", "2026-11-01T13:00:00Z"
rep = espn.match_report(home, away, ko)
print("reporte:", bool(rep), rep and (rep["home"].get("logo_url"), rep["away"].get("logo_url")))
pick = {"price": 1.85, "result": "W", "legs": [{"league": "Turquía · Süper Lig", "kickoff": ko, "home": home, "away": away,
                                                "label": "Gana Başakşehir", "sport": "soccer"}]}
data = recap.build(pick, rep, None)
for lay in layouts.RECAP_LAYOUTS:
    open(f"{OUT}/recap-{lay}.jpg", "wb").write(layouts.render_recap(data, lay))
print("ok")
