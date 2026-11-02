"""Vista previa (sin enviar nada) de una noticia en revisión, con el diseño actual."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import commons, newswatch, store  # noqa: E402
q = os.environ.get("Q", "westbrook").lower().split()
st = store.load()
OUT = "data/probe/newsrender"
os.makedirs(OUT, exist_ok=True)
for nid, it in reversed(list((st.get("news_items") or {}).items())):
    blob = " ".join(str(it.get(k) or "") for k in ("headline", "orig", "line", "player", "name")).lower()
    if all(w in blob for w in q):
        img, cr, nd = newswatch._render(dict(it))
        open(f"{OUT}/preview.jpg", "wb").write(img)
        json.dump({k: it.get(k) for k in ("headline", "line", "sub", "kicker", "layout", "player")} | {"credit": cr, "jersey": commons.JERSEY_LOG},
                  open(f"{OUT}/info.json", "w"), ensure_ascii=False, indent=1)
        print("ok", nid)
        break
else:
    print("no encontrada")
