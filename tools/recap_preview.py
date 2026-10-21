"""Vista previa del post partido con datos reales (ESPN + foto libre de Commons), sin tocar el bot.

    python tools/recap_preview.py "Vasco da Gama" "Boca Juniors" 2026-10-21T00:30:00Z "Sudamericana"
Guarda media/preview/recap.jpg.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import commons, espn, postimage, recap  # noqa: E402

home, away, kickoff = sys.argv[1:4]
league = sys.argv[4] if len(sys.argv) > 4 else ""
rep = espn.match_report(home, away, kickoff)
if not rep:
    sys.exit("ESPN no tiene ese partido como terminado")
who = recap.hero(rep)
photo = commons.photo(who["full"]) if who else None
print("Protagonista:", who and who["full"], "| foto:", photo[1]["text"] if photo else "sin foto libre")
pick = {"price": 1.85, "result": "W", "legs": [{"league": league, "kickoff": kickoff, "home": home, "away": away,
                                                "label": "Más de 2.5 goles", "sport": "soccer"}]}
data = recap.build(pick, rep, photo)
data["pick"] = None
data["dato"] = "vista previa con datos reales de ESPN"
print("Titular:", data["headline"], "| Eyebrow:", data["eyebrow"], "| Sub:", data["subline"])
os.makedirs("media/preview", exist_ok=True)
with open("media/preview/recap.jpg", "wb") as f:
    f.write(postimage.render_recap(data))
