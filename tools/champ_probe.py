"""Vista previa (sin enviar nada) del postpartido de un pick con titular/dato/versión campeón."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import layouts, recap, store, commons, matchphoto  # noqa: E402
pid = os.environ.get("PID", "296")
st = store.load()
p = st["picks"][pid]
r = p.get("recap") or {}
rep = r["report"]
r.update({"champion": os.environ.get("CHAMP"), "custom_dato": os.environ.get("DATO")})
who = recap.hero(rep)
t = rep.get(who.get("side")) or {}
photo = matchphoto.for_scorer(who["full"], [x for x in (t.get("name"), t.get("short")) if x], "soccer")
data = recap.build(p, rep, photo, os.environ.get("TITLE"), os.environ.get("DATO"), os.environ.get("CHAMP"))
os.makedirs("data/probe/champ", exist_ok=True)
open("data/probe/champ/preview.jpg", "wb").write(layouts.render_recap(data, "scoreboard", "dark"))
open("data/probe/champ/caption.txt", "w").write(recap.telegram_caption(p, rep, data["headline"]) + "\n\n-----\n\n"
                                                + recap.instagram_caption(p, rep, data["headline"], photo[1] if photo else None))
print("ok", data["headline"], data["dato"], bool(photo))
