"""Diagnóstico: fotos de Commons de un jugador y por qué pasan o no los filtros."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import commons  # noqa: E402
OUT = "data/probe/hero"
os.makedirs(OUT, exist_ok=True)
NAME, TEAMS = "Stephen Curry", ["Golden State Warriors", "Warriors"]
rows = []
for q in (None, f'"{NAME}" Warriors filetype:bitmap'):
    for c in commons.candidates(NAME, limit=40, query=q):
        rows.append({"title": c["title"], "year": c["year"], "lic": c["license"], "author": c["author"][:30],
                     "sport_ok": commons.sport_ok(c, "basketball"), "desc": c["desc"][:120], "cats": c["cats"][:160]})
pc = commons.player_candidates(NAME, TEAMS, 0, "basketball", 8)
json.dump({"raw": rows, "passed": [{"title": c["title"], "team_hit": c["team_hit"], "year": c["year"]} for c in pc]},
          open(f"{OUT}/diag.json", "w"), ensure_ascii=False, indent=1)
print(len(rows), "candidatos;", len(pc), "pasan")
