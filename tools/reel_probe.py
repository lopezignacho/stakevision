"""Prueba de Reels en el entorno del bot: noticia (foto de Commons) y postpartido."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import commons, reel  # noqa: E402
OUT = "data/probe/reel"
os.makedirs(OUT, exist_ok=True)
t = time.time()
item = json.load(open("data/news_ready.json", encoding="utf-8"))[0]
got = commons.file_photo(item["photo_file"])
n = {k: item[k] for k in ("tag", "kicker", "headline", "sub", "facts", "status")}
n.update(colors=item["colors"], source="Fuentes: " + item["sources"])
if got:
    n.update(photo=got[0], credit=f"Foto: {got[1]['author']} / Wikimedia Commons ({got[1]['license']}), modificada")
mp4, cov = reel.news(n)
open(f"{OUT}/noticia.mp4", "wb").write(mp4)
open(f"{OUT}/noticia.jpg", "wb").write(cov)
print("noticia", len(mp4) // 1024, "KB", round(time.time() - t), "s", "foto" if got else "sin foto")
