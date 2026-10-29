"""Prueba de plantillas «versus» y «resultado» con fotos reales (Commons), fútbol y NBA."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import newswatch, reel  # noqa: E402
OUT = "data/probe/hero"
os.makedirs(OUT, exist_ok=True)


def team(name, short, player, color, score=None):
    return {"name": name, "short": short, "player": player, "color": color, "score": score}


CASES = {
    "nba_versus": {"tag": "PARTIDAZO", "kicker": "NBA · TEMPORADA REGULAR", "sport": "basketball", "format": "versus",
                   "match": {"home": team("Golden State Warriors", "Warriors", "Stephen Curry", [29, 66, 138]),
                             "away": team("Oklahoma City Thunder", "Thunder", "Shai Gilgeous-Alexander", [0, 122, 193]),
                             "when": "Hoy · 22:00 (Chile)"}},
    "futbol_versus": {"tag": "EL CLÁSICO", "kicker": "LALIGA · ESPAÑA", "sport": "soccer", "format": "versus",
                      "match": {"home": team("Real Madrid", "Real Madrid", "Kylian Mbappé", [240, 240, 240]),
                                "away": team("FC Barcelona", "Barcelona", "Lamine Yamal", [165, 0, 68]),
                                "when": "Domingo · 11:15 (Chile)"}},
    "futbol_resultado": {"tag": "RESULTADO", "kicker": "PREMIER LEAGUE · INGLATERRA", "sport": "soccer", "format": "result",
                         "colors": [[200, 16, 46], [20, 30, 60]], "facts": ["Salah marcó y dio una asistencia",
                                                                            "El Liverpool sigue líder"],
                         "match": {"home": team("Liverpool", "Liverpool", "Mohamed Salah", [200, 16, 46], 3),
                                   "away": team("Chelsea", "Chelsea", "", [3, 70, 148], 1), "when": "Final"}},
}
info = {}
for key, c in CASES.items():
    base = {"headline": "PRUEBA", "sub": "", "facts": ["x"], "caption": "x", "colors": [[30, 40, 60], [80, 90, 110]]}
    base.update(c)
    it = newswatch._clean(base)
    img, cr, n = newswatch._render(it)
    open(f"{OUT}/{key}.jpg", "wb").write(img)
    lay = it["layout"]
    mp4, cov = reel.versus(n["versus"]) if lay == "versus" else reel.postgame(n["result"])
    open(f"{OUT}/{key}.mp4", "wb").write(mp4)
    info[key] = {"layout": lay, "options": it["_layouts"], "credit": cr,
                 "photos": {s: bool((n.get("versus") or {}).get(s, {}).get("photo")) for s in ("home", "away")}}
json.dump(info, open(f"{OUT}/info.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(info, ensure_ascii=False, default=str))
