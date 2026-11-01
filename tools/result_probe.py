"""Formato Resultado con foto del protagonista y escudos: Real Madrid 3-0 Racing (Bellingham)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import commons, newswatch  # noqa: E402
OUT = "data/probe/result"
os.makedirs(OUT, exist_ok=True)
item = newswatch._clean({"tag": "RESULTADO", "kicker": "REAL MADRID · ESPAÑA", "headline": "BELLINGHAM HACE HISTORIA",
                         "facts": ["Jude Bellingham es el primer inglés con 50 goles en el Real Madrid",
                                   "El equipo de José Mourinho venció 3-0 a Racing Santander"],
                         "sport": "soccer", "player": "Jude Bellingham", "teams": ["Real Madrid", "Madrid"],
                         "colors": [[240, 240, 240], [40, 40, 40]], "format": "result",
                         "match": {"home": {"name": "Real Madrid", "short": "Real Madrid", "score": 3, "color": [240, 240, 240]},
                                   "away": {"name": "Racing Santander", "short": "Racing", "score": 0, "color": [0, 130, 60]},
                                   "when": "Final"}})
img, cr, nd = newswatch._render(item)
open(f"{OUT}/result.jpg", "wb").write(img)
info = {"layout": item["layout"], "credit": cr, "logos": [bool((nd.get("result") or {}).get(s, {}).get("logo")) for s in ("home", "away")],
        "photo": bool((nd.get("result") or {}).get("photo")), "jersey": commons.JERSEY_LOG}
json.dump(info, open(f"{OUT}/info.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(info, ensure_ascii=False, default=str)[:2000])
