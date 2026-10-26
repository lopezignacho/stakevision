"""Prueba en seco: qué foto usaría el postpartido de un partido (no envía nada)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import commons, espn, layouts, matchphoto, recap  # noqa: E402
OUT = "data/probe/recapphoto"
os.makedirs(OUT, exist_ok=True)
HOME, AWAY, KO = "Universidad de Chile", "CD Everton Vina del Mar", "2026-10-26T21:00:00Z"
rep = espn.match_report(HOME, AWAY, KO)
info = {"found": bool(rep)}
if rep:
    who = recap.hero(rep)
    t = rep.get(who.get("side")) or {} if who else {}
    names = [x for x in (t.get("name"), t.get("short")) if x]
    info.update(hero=who and who["full"], team=names, score=f"{rep['home']['score']}-{rep['away']['score']}")
    photo = matchphoto.for_scorer(who["full"], names, "soccer") if who else None
    info["via"] = "jugador" if photo else None
    if not photo:
        photo = commons.team_photo(t.get("name") or "", "soccer")
        info["via"] = "club" if photo else "sin foto (colores del equipo)"
    if photo:
        info["credit"] = photo[1]
        open(f"{OUT}/foto.jpg", "wb").write(photo[0])
    p = {"id": "117", "result": "W", "price": 1.70, "kind": "simple",
         "legs": [{"home": HOME, "away": AWAY, "kickoff": KO, "league": "Chile · Primera División", "sport": "soccer",
                   "mtype": "spreads", "outcome": "1", "handicap": -0.5, "label": "Gana Universidad de Chile"}]}
    data = recap.build(p, rep, photo, None)
    data["credit"] = photo[1]["text"] if photo and photo[1] else None
    open(f"{OUT}/postpartido.jpg", "wb").write(layouts.render_recap(data, "classic" if "classic" in getattr(layouts, "LAYOUTS", {}) else layouts.next_layout({}, "recap"), "dark"))
json.dump(info, open(f"{OUT}/info.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(info, ensure_ascii=False, default=str))
