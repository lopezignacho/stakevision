"""Prueba de plantillas visuales con una foto real (Commons) del protagonista."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import commons, newsimage, reel  # noqa: E402
OUT = "data/probe/hero"
os.makedirs(OUT, exist_ok=True)
got = (commons.player_photo("Stephen Curry", ["Golden State Warriors", "Warriors"], sport="basketball")
       or commons.player_photo("Stephen Curry", ["Golden State Warriors", "Warriors"], need_team=False, sport="basketball"))
info = {"photo": bool(got), "credit": got[1] if got else None}
if got:
    cr = f"Foto: {got[1]['author']} / Wikimedia Commons ({got[1]['license']}), modificada"
    n = dict(photo=got[0], colors=[(29, 66, 138), (255, 199, 44)], tag="NBA", source="Fuente: ESPN", credit=cr,
             name="Stephen Curry", stat={"value": "44", "label": "puntos"}, line="Brilló en el triunfo de los Warriors.",
             kicker="GOLDEN STATE WARRIORS · NBA", headline="Curry vuelve a encender San Francisco")
    open(f"{OUT}/hero.jpg", "wb").write(newsimage.render_hero(n))
    open(f"{OUT}/impact.jpg", "wb").write(newsimage.render_impact(n))
    mp4, cov = reel.hero(n)
    open(f"{OUT}/hero.mp4", "wb").write(mp4)
json.dump(info, open(f"{OUT}/info.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(info, ensure_ascii=False, default=str))
