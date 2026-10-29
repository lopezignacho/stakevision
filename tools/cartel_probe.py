"""Prueba de los formatos «cartel» (versus) y «figura» con datos reales de ESPN y fotos libres de Commons."""
import json, os, sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import commons, nba, newsimage  # noqa: E402
OUT = "data/probe/cartel"
os.makedirs(OUT, exist_ok=True)
info = {}


def hexcol(x, d=(40, 50, 70)):
    try:
        return tuple(int(x[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:  # noqa: BLE001
        return d


def rec(c):
    return next((r.get("summary") for r in c.get("records") or [] if r.get("type") == "total"), "")


def photo(name, team):
    got = (commons.player_photo(name, [team["displayName"], team["name"]], need_team=True, sport="basketball")
           or commons.player_photo(name, [team["displayName"], team["name"]], need_team=True, sport="basketball", years=10))
    return got


# 1) figura: Curry en el último partido de Golden State
today = datetime.now(timezone.utc)
done = None
for back in range(0, 4):
    day = (today - timedelta(days=back)).strftime("%Y%m%d")
    for e in nba._get("/scoreboard", dates=day).get("events") or []:
        comp = e["competitions"][0]
        if comp["status"]["type"].get("completed") and any(c["team"]["abbreviation"] == "GS" or c["team"]["abbreviation"] == "GSW"
                                                           for c in comp["competitors"]):
            done = e
            break
    if done:
        break
if done:
    comp = done["competitions"][0]
    cs = {c["homeAway"]: c for c in comp["competitors"]}
    sm = nba._get("/summary", event=done["id"])
    best = None
    for t in (sm.get("boxscore") or {}).get("players") or []:
        for st in t.get("statistics") or []:
            keys = st.get("keys") or []
            for a in st.get("athletes") or []:
                v = dict(zip(keys, a.get("stats") or []))
                if "Curry" in (a.get("athlete") or {}).get("displayName", "") and v:
                    best = (a["athlete"]["displayName"], v, t["team"])
    if best:
        name, v, tm = best
        tpm = str(v.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted", "0-0")).split("-")[0]
        side = "home" if cs["home"]["team"]["id"] == tm["id"] else "away"
        got = photo(name, cs[side]["team"])
        hs, as_ = int(cs["home"]["score"]), int(cs["away"]["score"])
        g = {"player": name, "stats": [(v.get("points"), "PTS"), (v.get("rebounds"), "REB"), (v.get("assists"), "AST"),
                                       (tpm, "T3")], "color": hexcol(cs[side]["team"].get("color")),
             "home": {"abbr": cs["home"]["team"]["abbreviation"], "color": hexcol(cs["home"]["team"].get("color")),
                      "score": hs, "record": rec(cs["home"])},
             "away": {"abbr": cs["away"]["team"]["abbreviation"], "color": hexcol(cs["away"]["team"].get("color")),
                      "score": as_, "record": rec(cs["away"])},
             "winner": "home" if hs > as_ else "away", "competition": "NBA"}
        if got:
            g["photo"] = got[0]
            g["credit"] = f"Foto: {got[1]['author']} / Wikimedia Commons ({got[1]['license']}), modificada"
        open(f"{OUT}/figura.jpg", "wb").write(newsimage.render_figura(g))
        info["figura"] = {k: g[k] for k in ("player", "stats", "winner")} | {"score": f"{hs}-{as_}", "photo": bool(got),
                                                                             "game": done["name"]}

# 2) cartel: el partido más atractivo de hoy (el primero con fotos de las dos figuras)
for back in (0, 1):
    day = (today - timedelta(hours=6) + timedelta(days=back)).strftime("%Y%m%d")
    for e in nba._get("/scoreboard", dates=day).get("events") or []:
        comp = e["competitions"][0]
        if comp["status"]["type"].get("state") != "pre":
            continue
        cs = {c["homeAway"]: c for c in comp["competitors"]}
        v = {"competition": "NBA · Temporada regular",
             "kickoff": datetime.fromisoformat(e["date"].replace("Z", "+00:00"))}
        authors = []
        for side in ("home", "away"):
            c = cs[side]
            lead = next((l["leaders"][0]["athlete"]["displayName"] for l in c.get("leaders") or []
                         if l.get("name") in ("points", "pointsPerGame") and l.get("leaders")), "")
            got = photo(lead, c["team"]) if lead else None
            v[side] = {"name": c["team"]["displayName"], "short": c["team"]["name"],
                       "abbr": c["team"]["abbreviation"], "color": hexcol(c["team"].get("color")),
                       "record": rec(c), "player": lead}
            if got:
                v[side]["photo"] = got[0]
                authors.append(got[1]["author"])
        if len(authors) == 2:
            v["credit"] = f"Fotos: {', '.join(authors)} / Wikimedia Commons, modificadas"
            open(f"{OUT}/cartel.jpg", "wb").write(newsimage.render_cartel(v))
            info["cartel"] = {"game": e["name"], "players": [v["home"]["player"], v["away"]["player"]]}
            break
    if "cartel" in info:
        break
json.dump(info, open(f"{OUT}/info.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(info, ensure_ascii=False, default=str))
