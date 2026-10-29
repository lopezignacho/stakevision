"""Prueba real del formato «Figura» (ESPN + foto validada por camiseta con Gemini)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import commons, newswatch, reel  # noqa: E402
OUT = "data/probe/figura"
os.makedirs(OUT, exist_ok=True)
item = newswatch._clean({"headline": "CURRY BRILLA CON 44", "facts": ["44 puntos"], "sport": "basketball",
                         "player": "Stephen Curry", "teams": ["Golden State Warriors", "Warriors"], "format": "figura",
                         "kicker": "NBA", "match": {"home": {"name": "Minnesota Timberwolves", "short": "Timberwolves", "score": 114},
                                                    "away": {"name": "Golden State Warriors", "short": "Warriors", "score": 119}}})
img, cr, nd = newswatch._render(item)
open(f"{OUT}/figura.jpg", "wb").write(img)
mp4, cov = reel.still(img)
open(f"{OUT}/figura.mp4", "wb").write(mp4)
info = {"layout": item["layout"], "credit": cr, "jersey_checks": commons.JERSEY_LOG,
        "stats": (nd.get("figura") or {}).get("stats"), "score": [(nd.get("figura") or {}).get(s, {}).get("score") for s in ("home", "away")]}
json.dump(info, open(f"{OUT}/info.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(info, ensure_ascii=False, default=str)[:3000])
