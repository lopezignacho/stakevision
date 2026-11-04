"""Mayor ventaja de un equipo en cada partido de la temporada (ESPN: largestLead)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import nba  # noqa: E402
abbr = os.environ.get("TEAM", "phi")
sch = nba._get(f"/teams/{abbr}/schedule")
rows = []
for e in sch.get("events") or []:
    c = e["competitions"][0]
    if not c["status"]["type"].get("completed"):
        continue
    sm = nba._get("/summary", event=e["id"])
    lead = {}
    for t in (sm.get("boxscore") or {}).get("teams") or []:
        st = {s.get("name"): s.get("displayValue") for s in t.get("statistics") or []}
        lead[t["team"]["abbreviation"]] = st.get("largestLead")
    sc = {x["team"]["abbreviation"]: x.get("score", {}).get("displayValue") if isinstance(x.get("score"), dict) else x.get("score")
          for x in c["competitors"]}
    rows.append({"date": e["date"][:10], "name": e.get("shortName"), "score": sc, "largestLead": lead})
os.makedirs("data/probe", exist_ok=True)
json.dump(rows, open("data/probe/lead.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(rows, ensure_ascii=False)[:3000])
