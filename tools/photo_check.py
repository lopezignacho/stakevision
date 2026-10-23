"""Revisión con datos reales: referentes (Wikidata), fotos (Commons), siglas NBA y previa VIP."""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import config, espn, matchphoto, nba, players  # noqa: E402

OUT = "data/probe/photos"
os.makedirs(OUT, exist_ok=True)
log = []
for team, sport in [("Los Angeles Lakers", "basketball"), ("LA Clippers", "basketball"), ("Colo-Colo", "soccer"),
                    ("Universidad de Chile", "soccer"), ("Boca Juniors", "soccer"), ("Real Madrid", "soccer")]:
    try:
        qid = players.team_qid(team, sport)
        sq = players.squad(team, sport)
        log.append(f"== {team} ({sport}) qid={qid} referentes={[p['name'] for p in sq[:6]]}")
        got = matchphoto.referent([team], sport)
        if got:
            slug = team.lower().replace(" ", "-")
            with open(f"{OUT}/{slug}.jpg", "wb") as f:
                f.write(got[0])
            log.append(f"   foto: {got[1].get('player')} | club en título: {got[1].get('team_hit')} | {got[1]['text']}"
                       f" | {got[1].get('page')}")
        else:
            log.append("   foto: ninguna")
    except Exception:
        log.append(traceback.format_exc())

# Partido real de hoy: Lakers vs Clippers
from datetime import datetime, timezone  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402
sb = nba._get("/scoreboard", dates=datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d"))
ev = None
for e in sb.get("events") or []:
    names = [x["team"]["displayName"] for x in e["competitions"][0]["competitors"]]
    if any("Lakers" in n for n in names) and any("Clippers" in n for n in names):
        ev = e
ko = None
if ev:
    ko = ev["date"].replace("Z", ":00Z") if len(ev["date"]) == 17 else ev["date"]
    log.append(f"== Evento ESPN {ev['id']} {ev['date']}")
    pv = espn.preview("Los Angeles Lakers", "LA Clippers", ko, "basketball")
    log.append(f"   preview: {pv and {s: (pv[s]['abbr'], pv[s]['color'], pv[s]['name']) for s in ('home', 'away')}}")
    pick = {"id": "probe37", "price": 1.85, "prob": 0.546, "edge": 0.01, "stake": 3, "kind": "simple", "tier": "justa",
            "legs": [{"home": "Los Angeles Lakers", "away": "LA Clippers", "sport": "basketball", "mtype": "totals",
                      "outcome": "Más de", "handicap": 226.5, "kickoff": ko, "league": "NBA", "fair_odds": 1.83,
                      "price": 1.85, "edge": 0.01, "market": "Totals"}]}
    try:
        log.append("== PREVIA VIP (texto real)\n" + (nba.pregame(pick, 25) or "sin contexto"))
    except Exception:
        log.append(traceback.format_exc())
    try:
        config.ROOT = os.path.abspath("data/probe/root")
        from sv import main
        main._make_pick_photo(pick)
        with open(main._pick_photo_file(pick), "rb") as f, open(f"{OUT}/pick-37-nuevo.jpg", "wb") as g:
            g.write(f.read())
        log.append(f"   imagen del pick: crédito {pick.get('pick_photo_credit')}")
    except Exception:
        log.append(traceback.format_exc())
else:
    log.append("No encontré Lakers vs Clippers hoy en ESPN")
with open(f"{OUT}/check.txt", "w") as f:
    f.write("\n".join(log))
print("\n".join(log))
