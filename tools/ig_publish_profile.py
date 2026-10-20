"""Publica en Instagram el material fijo del perfil (se lanza una vez desde GitHub Actions)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import config, instagram, store  # noqa: E402

BASE = f"{config.PUBLIC_SITE}/ig/perfil"
TAGS = "#Stakevision #PronosticosDeportivos #Futbol #ApuestasDeportivas #Chile"
RESP = "🔞 +18 · Juega con responsabilidad. Apostar implica riesgo de pérdida."

POSTS = [  # en este orden, para que la bienvenida quede como la más reciente
    ("responsable", ["responsable.jpg"],
     "🔞 Juega con responsabilidad\n\nApostar debe ser entretenimiento, nunca una forma de recuperar dinero.\n\n"
     "✅ Apuesta solo lo que puedas perder\n✅ Pon límites de tiempo y dinero\n✅ Si deja de ser entretenido, para\n"
     "✅ Pedir ayuda es parte del juego\n\nAyuda en Chile: Salud Responde 600 360 7777.\n\n" + TAGS + " #JuegoResponsable"),
    ("stake", ["stake-1.jpg", "stake-2.jpg", "stake-3.jpg"],
     "📊 ¿Qué es el stake?\n\nEs la confianza que le damos a cada pick, del 1 al 10. Cada punto equivale al 0,5% de tu bankroll "
     "(el dinero que separas solo para apostar).\n\nNunca usamos 9 ni 10: ninguna apuesta es segura.\n\n"
     "Desliza para ver la guía completa 👉\n\n" + RESP + "\n\n" + TAGS),
    ("bienvenida", [f"bienvenida-{k}.jpg" for k in range(1, 6)],
     "👁 Bienvenido a Stakevision\n\nVemos el partido antes del pitazo: analizamos cientos de partidos de las ligas más "
     "importantes de América y Europa, calculamos la cuota justa de cada mercado y solo publicamos cuando hay valor.\n\n"
     "🎁 1 pick gratis cada día en nuestro canal de Telegram\n👑 VIP: 2 a 4 picks diarios\n"
     "📊 Historial público en la web: verdes y rojas, nada se borra\n\n📲 Link en la bio.\n" + RESP + "\n\n" + TAGS),
]
STORIES = ["historia-empieza.jpg", "historia-verdes.jpg", "historia-stake.jpg", "historia-plus18.jpg"]


def main():
    state = store.load()
    what = (sys.argv[1] if len(sys.argv) > 1 else "todo")
    if what in ("todo", "posts"):
        for name, files, caption in POSTS:
            urls = [f"{BASE}/{f}" for f in files]
            link = (instagram.publish_single(state, urls[0], caption) if len(urls) == 1
                    else instagram.publish_carousel(state, urls, caption))
            print(f"Publicado {name}: {link}")
    if what in ("todo", "historias"):
        for f in STORIES:
            print(f"Historia {f}: {instagram.publish_story(state, f'{BASE}/{f}')}")


if __name__ == "__main__":
    main()
