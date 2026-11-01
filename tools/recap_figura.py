"""Postpartido estilo «Figura» de un pick NBA (ganador): figura del equipo elegido + marcador + chip del pick."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import espnstats, newswatch, reel  # noqa: E402
team = os.environ.get("MATCH_TEAM", "Philadelphia 76ers")
OUT = "data/probe/recap_figura"
os.makedirs(OUT, exist_ok=True)
player = espnstats.nba_top_player(team)
g = espnstats.nba_figura(player) if player else None
info = {"player": player}
if g:
    item = {"player": g["player"], "teams": [g["team"]], "sport": "basketball", "kicker": "NBA"}
    got = newswatch._photo_for(item)
    if got:
        cr = got[1] or {}
        g["photo"] = got[0]
        g["credit"] = (f"Foto: {cr.get('author')} (con permiso)" if cr.get("own") else
                       f"Foto: {cr.get('author')} / Wikimedia Commons ({cr.get('license')}), modificada")
    g["pick"] = {"result": "W", "title": "PICK GRATIS · VERDE", "text": os.environ.get("PICK_TEXT", "Gana 76ers · cuota 1.82")}
    from sv import newsimage
    img = newsimage.render_figura(g)
    open(f"{OUT}/recap.jpg", "wb").write(img)
    mp4, cov = reel.still(img)
    open(f"{OUT}/recap.mp4", "wb").write(mp4)
    info.update(stats=g["stats"], score=[g["home"]["score"], g["away"]["score"]], photo=bool(got), credit=g.get("credit"))
from sv import commons  # noqa: E402
info["jersey_checks"] = commons.JERSEY_LOG
json.dump(info, open(f"{OUT}/info.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(info, ensure_ascii=False, default=str)[:2000])
