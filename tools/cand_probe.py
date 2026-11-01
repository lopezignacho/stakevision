"""Por qué no hay foto: candidatos de Commons para un jugador y en qué filtro caen."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import commons  # noqa: E402
name, teams = os.environ.get("P", "Jude Bellingham"), ["Real Madrid", "Madrid"]
raw = commons.candidates(name, limit=40)
raw += commons.candidates(name, limit=40, query=f'"{name}" Madrid filetype:bitmap')
out = {"raw": [{k: c.get(k) for k in ("title", "year", "license", "author")} for c in raw[:40]],
       "kept_3y": [{k: c.get(k) for k in ("title", "year", "team_hit", "title_hit", "national")} for c in commons.player_candidates(name, teams, sport="soccer")],
       "kept_10y": [{k: c.get(k) for k in ("title", "year", "team_hit", "title_hit", "national")} for c in commons.player_candidates(name, teams, sport="soccer", years=10)]}
os.makedirs("data/probe", exist_ok=True)
json.dump(out, open("data/probe/cand.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:3000])
