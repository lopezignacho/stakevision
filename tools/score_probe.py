"""Marcador de ESPN de un partido de fútbol (liga y equipo por variables de entorno)."""
import json, os, requests
lg, team, day = os.environ.get("LEAGUE", "bra.1"), os.environ.get("MATCH_TEAM", "Flamengo"), os.environ.get("DAY", "")
r = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard", params={"dates": day} if day else {}, timeout=25).json()
out = []
for e in r.get("events") or []:
    if team.lower() in e["name"].lower():
        c = e["competitions"][0]
        out.append({"name": e["name"], "status": c["status"]["type"].get("detail"),
                    "score": {x["team"]["displayName"]: x.get("score") for x in c["competitors"]},
                    "goals": [(d.get("clock", {}).get("displayValue"), (d.get("athletesInvolved") or [{}])[0].get("displayName"))
                              for d in c.get("details") or [] if d.get("scoringPlay")]})
os.makedirs("data/probe", exist_ok=True)
json.dump(out, open("data/probe/score.json", "w"), ensure_ascii=False, indent=1)
print(out)
