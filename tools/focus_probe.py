"""Prueba de encuadre: las fotos que mandaste, armadas en «Impacto» con el foco en el protagonista (Gemini)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import newsimage, postimage  # noqa: E402
OUT = "data/probe/focus"
os.makedirs(OUT, exist_ok=True)
info = {}
src = "data/news_photos"
for fn in sorted(os.listdir(src))[-4:]:
    ph = open(os.path.join(src, fn), "rb").read()
    n = {"photo": ph, "colors": [(30, 40, 60), (80, 90, 110)], "tag": "NOTICIA", "kicker": "PRUEBA · ENCUADRE",
         "headline": "EL PROTAGONISTA AL CENTRO", "source": "Fuentes: ESPN", "credit": "Foto: prueba"}
    open(f"{OUT}/{fn}", "wb").write(newsimage.render_impact(n))
    info[fn] = {"subject": postimage._subject(ph)}
json.dump(info, open(f"{OUT}/info.json", "w"), indent=1, default=str)
print(info)
