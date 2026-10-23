"""Demo real de Bet Builder: un partido NBA y uno de fútbol por jugarse."""
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import builder, espn, formatting, nba, postimage  # noqa: E402

OUT = "data/probe/builder"
os.makedirs(OUT, exist_ok=True)
log = []
now = datetime.now(timezone.utc)
BIG = ("Premier", "LaLiga", "Serie A", "Bundesliga", "Ligue 1", "Primera", "Liga Profesional", "Champions")


def upcoming(sport):
    for k in (0, 1, 2):
        day = (now + timedelta(days=k)).astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d")
        evs = nba._get("/scoreboard", dates=day).get("events") if sport == "basketball" else espn._scoreboard(day, "soccer")
        for e in evs or []:
            c = e["competitions"][0]
            if c["status"]["type"]["state"] != "pre":
                continue
            h = next(x for x in c["competitors"] if x["homeAway"] == "home")["team"]["displayName"]
            a = next(x for x in c["competitors"] if x["homeAway"] == "away")["team"]["displayName"]
            ko = e["date"].replace("Z", ":00Z") if len(e["date"]) == 17 else e["date"]
            yield h, a, ko, e


for sport in ("basketball", "soccer"):
    tried = 0
    for h, a, ko, e in upcoming(sport):
        if sport == "soccer" and tried > 12:
            break
        tried += 1
        try:
            b = builder.suggest(h, a, ko, sport)
        except Exception:
            log.append(traceback.format_exc())
            b = None
        log.append(f"{sport}: {a} @ {h} ({ko}) -> {'OK' if b else 'sin 3 líneas'}"
                   + (f" · candidatas {b['n_candidates']}" if b else ""))
        if not b:
            continue
        league = "USA · NBA" if sport == "basketball" else builder.league_name((e.get("season") or {}).get("slug") or "")
        legs = [{"home": h, "away": a, "kickoff": ko, "league": league, "sport": sport, "label": x["label"],
                 "price": None} for x in b["legs"]]
        p = {"id": "demo", "kind": "builder", "legs": legs, "bb": b, "price": 3.10, "prob": b["prob"],
             "edge": round(b["prob"] * 3.10 - 1, 4), "stake": 2}
        log.append("== DUEÑO\n" + formatting.builder_owner(p))
        log.append("== CANAL VIP\n" + formatting.builder_post(p))
        open(f"{OUT}/{sport}.jpg", "wb").write(postimage.render_builder(p, "vip"))
        break
open(f"{OUT}/demo.txt", "w").write("\n".join(log))
print("\n".join(log))
