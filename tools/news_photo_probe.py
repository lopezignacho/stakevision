"""Busca fotos libres (Wikimedia Commons) de un jugador para una noticia y arma la imagen con cada una."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import commons, newsimage  # noqa: E402

OUT = "data/probe/newsphoto"
os.makedirs(OUT, exist_ok=True)
NAME, TEAMS = "Jalen Williams", ["Oklahoma City Thunder", "Thunder"]
pool = {}
for q in (None, f'"{NAME}" Thunder filetype:bitmap', f'"{NAME}" injury filetype:bitmap', f'"{NAME}" basketball filetype:bitmap'):
    for c in commons.candidates(NAME, limit=40, query=q):
        pool.setdefault(c["title"], c)
rows = sorted(pool.values(), key=lambda c: (c["year"], c["first"]), reverse=True)
info = []
news = json.load(open("tools/news_demo.json", encoding="utf-8"))
for i, c in enumerate(rows[:6]):
    got = commons._download(c)
    if not got:
        continue
    img, cr = got
    open(f"{OUT}/cand{i}.jpg", "wb").write(img)
    n = dict(news, photo=img, source="Fuentes: " + news["source_short"],
             credit=f"Foto de referencia: {c['author']} / Wikimedia Commons ({c['license']}), modificada")
    open(f"{OUT}/news{i}.jpg", "wb").write(newsimage.render_news(n))
    info.append({k: c[k] for k in ("title", "author", "license", "year", "page", "desc")})
json.dump(info, open(f"{OUT}/list.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(info, ensure_ascii=False, indent=1))
