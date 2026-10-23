"""Demo con datos reales: pick VIP (cuota real si hay), entretiempo y final NBA (último cruce real de los equipos)."""
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import config, formatting, main, nba, nbagame, oddspapi  # noqa: E402
from sv.value import Pick, selections_for_fixture  # noqa: E402

OUT = "data/probe/demo"
os.makedirs(OUT, exist_ok=True)
log = []
A_, B_ = "Nuggets", "Thunder"
now = datetime.now(timezone.utc)

# 1) partido de hoy en ESPN
ev = None
for k in range(0, 3):
    day = (now + timedelta(days=k)).astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d")
    for e in nba._get("/scoreboard", dates=day).get("events") or []:
        names = [x["team"]["displayName"] for x in e["competitions"][0]["competitors"]]
        if any(A_ in n for n in names) and any(B_ in n for n in names):
            ev = e
            break
    if ev:
        break
if not ev:
    log.append("No encontré Nuggets vs Thunder en los próximos 3 días en ESPN")
    open(f"{OUT}/demo.txt", "w").write("\n".join(log))
    raise SystemExit(0)
comp = ev["competitions"][0]["competitors"]
home = next(x for x in comp if x["homeAway"] == "home")["team"]["displayName"]
away = next(x for x in comp if x["homeAway"] == "away")["team"]["displayName"]
ko = ev["date"].replace("Z", ":00Z") if len(ev["date"]) == 17 else ev["date"]
log.append(f"Partido: {away} @ {home} · {ko} · {ev['status']['type']['description']}")

# 2) cuota real (OddsPapi) -> opción A
pick = None
try:
    fx = [f for f in oddspapi.upcoming_fixtures(main._iso(now - timedelta(hours=1)), main._iso(now + timedelta(hours=48)),
                                                sport_id=config.NBA_SPORT_ID)
          if f.get("tournamentId") == config.NBA_TOURNAMENT]
    markets = oddspapi.markets(sport_id=config.NBA_SPORT_ID)
    names = lambda f: [f.get("participant1Name") or "", f.get("participant2Name") or ""]  # noqa: E731
    by = {f["fixtureId"]: f for f in fx
          if any(nba._same_team(home, n) for n in names(f)) and any(nba._same_team(away, n) for n in names(f))}
    log.append(f"Fixtures NBA OddsPapi: {len(fx)}; candidatos: {len(by)}")
    for row in oddspapi.odds_by_tournaments([config.NBA_TOURNAMENT]):
        f = by.get(row.get("fixtureId"))
        if f and len(row.get("bookmakerOdds") or {}) >= 2:
            opt = nba.options_for_game(selections_for_fixture(f, row, markets, "basketball"))
            if opt:
                d = Pick("simple", [opt[0]], tier=opt[2]).to_dict()
                d["legs"][0]["label"] = formatting.outcome_label(d["legs"][0])
                pick = d
                break
except Exception:
    log.append(traceback.format_exc())
if not pick:
    log.append("Sin cuota real disponible: uso un pick de ejemplo (Más de 228.5 @ 1.87)")
    pick = {"price": 1.87, "prob": 0.53, "edge": 0.0, "stake": 3, "kind": "simple", "tier": "justa",
            "legs": [{"home": home, "away": away, "sport": "basketball", "mtype": "totals", "outcome": "Más de",
                      "handicap": 228.5, "kickoff": ko, "league": "USA · NBA", "fair_odds": 1.87, "price": 1.87,
                      "edge": 0.0, "market": "Más/Menos (incl. tiempo extra)"}]}
pick.update(id="demo", status="published", sport="basketball")
for l in pick["legs"]:
    l["sport"] = "basketball"
log.append(f"Pick: {formatting.outcome_label(pick['legs'][0])} @ {pick['price']} ({pick['legs'][0]['home']} vs {pick['legs'][0]['away']})")

# 3) imagen del pick (VIP)
try:
    pick["pick_layout"] = "revista"
    main._make_pick_photo(pick)
    with open(main._pick_photo_file(pick), "rb") as f, open(f"{OUT}/1-pick-vip.jpg", "wb") as g:
        g.write(f.read())
    log.append(f"Foto pick: {(pick.get('pick_photo_credit') or {}).get('player')} · "
               f"{(pick.get('pick_photo_credit') or {}).get('page')}")
except Exception:
    log.append(traceback.format_exc())

# 4) último cruce real terminado (para entretiempo y final)
last = None
for season in (2027, 2026, 2025):
    data = nba._get("/teams/25/schedule", season=season)
    for e in data.get("events") or []:
        c = e["competitions"][0]
        if not ((c.get("status") or {}).get("type") or {}).get("completed"):
            continue
        if any("Nuggets" in (x.get("team") or {}).get("displayName", "") for x in c["competitors"]):
            if not last or e["date"] > last["date"]:
                last = e
    if last:
        break
if not last:
    log.append("No encontré un cruce reciente terminado")
else:
    lc = last["competitions"][0]["competitors"]
    lh = next(x for x in lc if x["homeAway"] == "home")["team"]["displayName"]
    la = next(x for x in lc if x["homeAway"] == "away")["team"]["displayName"]
    log.append(f"Último cruce real: {la} @ {lh} · {last['date']} (id {last['id']})")
    nba.find_event = lambda h, a, k, _e=last: ({"id": _e["id"], "competitions": _e["competitions"]},
                                              not nba._same_team(h, lh))
    p2 = dict(pick, id="demo")
    try:
        half = nbagame.report(p2["legs"][0]["home"], p2["legs"][0]["away"], p2["legs"][0]["kickoff"], half=True)
        img, data = main._nba_board({}, p2, half, "half")
        open(f"{OUT}/2-entretiempo.jpg", "wb").write(img)
        log.append("== Texto entretiempo (VIP)\n" + nbagame.half_caption(p2, half, data["status"]))
        fin = nbagame.report(p2["legs"][0]["home"], p2["legs"][0]["away"], p2["legs"][0]["kickoff"])
        p2["result"] = main.grade_leg(p2["legs"][0], fin["home"]["score"], fin["away"]["score"])
        p2["nba_half"] = {"home": half["home"]["score"], "away": half["away"]["score"]}
        hr = {"home": {"score": half["home"]["score"]}, "away": {"score": half["away"]["score"]}}
        img, data = main._nba_board({}, p2, fin, "final", half_rep=hr)
        open(f"{OUT}/3-final.jpg", "wb").write(img)
        log.append("== Texto final (VIP)\n" + nbagame.final_caption(p2, fin, data["headline"], data["photo_credit"]))
        log.append("== Texto final (Instagram)\n" + nbagame.final_caption(p2, fin, data["headline"], data["photo_credit"], ig=True))
    except Exception:
        log.append(traceback.format_exc())
open(f"{OUT}/demo.txt", "w").write("\n".join(log))
print("\n".join(log))
