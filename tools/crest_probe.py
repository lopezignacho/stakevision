"""Vista previa del postpartido nuevo («marcador grande») con un partido real: datos de ESPN, escudos oficiales,
foto del protagonista validada. No publica nada."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import commons, espn, layouts, matchphoto, recap  # noqa: E402
OUT = "data/probe/crest"
os.makedirs(OUT, exist_ok=True)
home, away, ko = os.environ.get("H_T", "Nublense"), os.environ.get("A_T", "Colo-Colo"), os.environ.get("KO", "2026-11-08T18:00:00Z")
rep = espn.match_report(home, away, ko)
print("reporte:", bool(rep), rep and (rep["home"]["score"], rep["away"]["score"], [(g["label"], g["player"], g["side"]) for g in rep["goals"]]))
pick = {"price": 1.93, "result": "W", "legs": [{"league": "Primera División de Chile", "kickoff": ko, "home": home, "away": away,
                                                "label": "Gana Colo-Colo", "sport": "soccer", "mtype": "1x2",
                                                "outcome": "2", "handicap": None}]}
who = recap.hero(rep)
photo = None
try:
    photo = matchphoto.for_scorer(who["full"], [rep[who["side"]]["name"]]) if who else None
except Exception as e:  # noqa: BLE001
    print("foto:", e)
print("figura:", who and who["full"], "foto:", bool(photo), commons.JERSEY_LOG[-2:])
for with_photo in (False, True):
    data = recap.build(pick, rep, photo if with_photo else None)
    open(f"{OUT}/scoreboard{'-foto' if with_photo else ''}.jpg", "wb").write(layouts.recap_scoreboard(data))
print("ok")
