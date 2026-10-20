"""Genera el material fijo del perfil de Instagram (se corre a mano, en local):

    python tools/ig_profile.py

Salida en docs/ig/perfil/ (la web la sirve para que Instagram la pueda descargar).
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import config  # noqa: E402
from sv.postimage import (INK, LOGO, MUTED, SOFT, W, _background, _check_badge, _font,  # noqa: E402
                          _icon, POST)

OUT = os.path.join(config.ROOT, "docs", "ig", "perfil")
EYES = os.path.join(config.ROOT, "docs", "assets", "eyes-transparent.png")
NEON = (150, 255, 110)
GREEN = (46, 150, 46)
WHITE = (240, 240, 242)
GREY = (170, 172, 178)


def glow(im, box, color=(90, 255, 60, 55), blur=90):
    g = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse(box, fill=color)
    im.alpha_composite(g.filter(ImageFilter.GaussianBlur(blur)))


def wrap(d, text, font, max_w):
    lines = []
    for para in text.split("\n"):
        words, cur = para.split(" "), ""
        for w in words:
            t = (cur + " " + w).strip()
            if d.textlength(t, font=font) <= max_w:
                cur = t
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def text_block(im, xy, text, weight, size, fill, max_w, gap=1.25, center=False):
    d = ImageDraw.Draw(im)
    f = _font(weight, size)
    x, y = xy
    for ln in wrap(d, text, f, max_w):
        lx = x + (max_w - d.textlength(ln, font=f)) / 2 if center else x
        d.text((lx, y), ln, font=f, fill=fill)
        y += size * gap
    return y


def neon_text(im, xy, text, size, center_w=None):
    f = _font("Bold", size)
    d = ImageDraw.Draw(im)
    x, y = xy
    if center_w:
        x = x + (center_w - d.textlength(text, font=f)) / 2
    g = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(g).text((x, y), text, font=f, fill=(110, 255, 80, 255))
    im.alpha_composite(g.filter(ImageFilter.GaussianBlur(size / 8)))
    ImageDraw.Draw(im).text((x, y), text, font=f, fill=NEON)


def frame(h=1350, page=None, total=None, logo_w=230):
    im = _background(h).convert("RGBA")
    glow(im, (W / 2 - 300, -120, W / 2 + 300, 260), (90, 255, 60, 40), 80)
    logo = Image.open(LOGO).convert("RGBA")
    logo = logo.resize((logo_w, round(logo.height * logo_w / logo.width)), Image.LANCZOS)
    im.alpha_composite(logo, ((W - logo_w) // 2, 48))
    d = ImageDraw.Draw(im)
    if page and total:   # puntos de carrusel + "desliza"
        r, gap = 7, 26
        x0 = (W - (total - 1) * gap) / 2
        for k in range(total):
            c = NEON if k + 1 == page else (90, 92, 98)
            d.ellipse((x0 + k * gap - r, h - 64 - r, x0 + k * gap + r, h - 64 + r), fill=c)
        if page < total:
            f = _font("Medium", 26)
            t = "Desliza"
            tx = W - 110 - d.textlength(t, font=f)
            d.text((tx, h - 82), t, font=f, fill=GREY)
            ax = W - 96
            d.line((ax, h - 66, ax + 26, h - 66), fill=GREY, width=3)
            d.line((ax + 16, h - 75, ax + 26, h - 66), fill=GREY, width=3)
            d.line((ax + 16, h - 57, ax + 26, h - 66), fill=GREY, width=3)
    return im, logo.height + 48


def card(im, box, radius=30):
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + 12, x1, y1 + 12), radius, fill=(0, 0, 0, 140))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(20)))
    ImageDraw.Draw(im).rounded_rectangle(box, radius, fill=(255, 255, 255))


def num_badge(im, xy, n, size=58):
    d = ImageDraw.Draw(im)
    x, y = xy
    d.ellipse((x, y, x + size, y + size), fill=(58, 190, 58))
    f = _font("Bold", int(size * 0.5))
    t = str(n)
    d.text((x + (size - d.textlength(t, font=f)) / 2, y + size * 0.18), t, font=f, fill="white")


def save(im, name):
    os.makedirs(OUT, exist_ok=True)
    im.convert("RGB").save(os.path.join(OUT, name), "JPEG", quality=93, optimize=True)


# ------------------------------------------------------------------ foto de perfil
def profile_photo():
    s = 1080
    im = Image.new("RGBA", (s, s), (16, 17, 19, 255))
    bg = _background(s).convert("RGBA").resize((s, s))
    im.alpha_composite(bg)
    glow(im, (140, 260, 940, 820), (90, 255, 60, 70), 110)
    eyes = Image.open(EYES).convert("RGBA")
    ew = 860
    eyes = eyes.resize((ew, round(eyes.height * ew / eyes.width)), Image.LANCZOS)
    im.alpha_composite(eyes, ((s - ew) // 2, (s - eyes.height) // 2 - 10))
    im.convert("RGB").save(os.path.join(OUT, "foto-perfil.jpg"), "JPEG", quality=95)


# ------------------------------------------------------------------ carrusel 1: bienvenida
def welcome():
    T = 5
    # 1 portada
    im, top = frame(page=1, total=T, logo_w=300)
    glow(im, (W / 2 - 460, 380, W / 2 + 460, 900), (90, 255, 60, 50), 110)
    text_block(im, (90, 420), "BIENVENIDO A", "Medium", 38, GREY, W - 180, center=True)
    neon_text(im, (90, 480), "Vemos el partido", 104, W - 180)
    neon_text(im, (90, 600), "antes del pitazo.", 104, W - 180)
    text_block(im, (140, 780), "Pronósticos deportivos con datos, no con corazonadas.",
               "Regular", 44, WHITE, W - 280, center=True)
    d = ImageDraw.Draw(im)
    chips = ["⚽ Fútbol", "Ligas top", "Historial público"]
    chips = ["Fútbol", "Ligas de América y Europa", "Historial público"]
    f = _font("Medium", 30)
    widths = [d.textlength(c, font=f) + 56 for c in chips]
    x = (W - (sum(widths) + 20 * (len(chips) - 1))) / 2
    for c, w in zip(chips, widths):
        d.rounded_rectangle((x, 1010, x + w, 1072), 31, outline=(110, 230, 80), width=2)
        d.text((x + 28, 1022), c, font=f, fill=NEON)
        x += w + 20
    save(im, "bienvenida-1.jpg")

    # 2 cómo elegimos
    im, top = frame(page=2, total=T)
    text_block(im, (90, top + 50), "CÓMO FUNCIONA", "Medium", 30, (110, 230, 80), W - 180)
    text_block(im, (90, top + 95), "Así elegimos cada pick", "Bold", 64, WHITE, W - 180)
    steps = [("Analizamos", "Cientos de partidos de las ligas más importantes de América y Europa, todos los días."),
             ("Calculamos", "La cuota justa de cada mercado: lo que debería pagar según la probabilidad real."),
             ("Publicamos", "Solo cuando la cuota disponible paga más de lo justo. Si no hay valor, no hay pick.")]
    y = top + 250
    for k, (t, body) in enumerate(steps, 1):
        card(im, (90, y, W - 90, y + 230), 28)
        num_badge(im, (130, y + 40), k)
        text_block(im, (215, y + 38), t, "Bold", 44, INK, W - 360)
        text_block(im, (215, y + 100), body, "Regular", 32, SOFT, W - 360, gap=1.3)
        y += 262
    save(im, "bienvenida-2.jpg")

    # 3 qué recibes
    im, top = frame(page=3, total=T)
    text_block(im, (90, top + 50), "QUÉ RECIBES", "Medium", 30, (110, 230, 80), W - 180)
    text_block(im, (90, top + 95), "Dos canales en Telegram", "Bold", 64, WHITE, W - 180)
    y = top + 260
    plans = [("GRATIS", "1 pick diario", ["Análisis completo de cada pick", "Cuota, stake y probabilidad", "Resultado publicado siempre"]),
             ("VIP", "2 a 4 picks diarios", ["Los mejores valores del día", "Aviso 30 minutos antes del partido", "Resultados y seguimiento"])]
    for name, sub, items in plans:
        card(im, (90, y, W - 90, y + 360), 28)
        d = ImageDraw.Draw(im)
        fb = _font("Bold", 28)
        pill_w = d.textlength(name, font=fb) + 44
        d.rounded_rectangle((130, y + 40, 130 + pill_w, y + 90), 25, fill=(58, 190, 58) if name == "VIP" else (29, 36, 51))
        d.text((152, y + 48), name, font=fb, fill="white")
        text_block(im, (130 + pill_w + 24, y + 38), sub, "Bold", 44, INK, W - 400)
        yy = y + 130
        for it in items:
            im.alpha_composite(_check_badge(36), (134, int(yy + 4)))
            text_block(im, (188, yy), it, "Regular", 34, SOFT, W - 330)
            yy += 64
        y += 395
    save(im, "bienvenida-3.jpg")

    # 4 historial
    im, top = frame(page=4, total=T)
    text_block(im, (90, top + 50), "TRANSPARENCIA", "Medium", 30, (110, 230, 80), W - 180)
    text_block(im, (90, top + 95), "Verdes y rojas. Todas.", "Bold", 64, WHITE, W - 180)
    text_block(im, (90, top + 190), "Cada pick se publica antes del partido y queda en el historial público de la web, gane o pierda. Nada se edita ni se borra.",
               "Regular", 34, GREY, W - 180, gap=1.35)
    y = top + 400
    card(im, (90, y, W - 90, y + 420), 28)
    d = ImageDraw.Draw(im)
    fh, fr, fm = _font("Medium", 24), _font("Regular", 30), _font("Bold", 30)
    cols = [130, 300, 690, 830]
    for c, t in zip(cols, ["FECHA", "PARTIDO", "CUOTA", "RESULTADO"]):
        d.text((c, y + 36), t, font=fh, fill=MUTED)
    rows = [("19/10", "Parma 0-3 Torino", "1.82", "W"), ("19/10", "Newell's vs C. Córdoba", "1.87", "W"),
            ("—", "Próximo pick", "—", None)]
    yy = y + 100
    for date, match, odd, res in rows:
        d.line((120, yy - 16, W - 120, yy - 16), fill=(232, 234, 238), width=2)
        d.text((cols[0], yy + 20), date, font=fr, fill=SOFT)
        d.text((cols[1], yy + 20), match, font=fr, fill=INK)
        d.text((cols[2], yy + 20), odd, font=fm, fill=INK)
        if res:
            im.alpha_composite(_check_badge(34), (cols[3], int(yy + 22)))
            ImageDraw.Draw(im).text((cols[3] + 46, yy + 20), "Verde", font=fm, fill=GREEN)
        else:
            d.text((cols[3], yy + 20), "Hoy", font=fm, fill=MUTED)
        d = ImageDraw.Draw(im)
        yy += 100
    text_block(im, (90, y + 470), "Revísalo tú mismo en la web (link en la bio).", "Medium", 34, NEON, W - 180, center=True)
    save(im, "bienvenida-4.jpg")

    # 5 llamado a la acción
    im, top = frame(page=5, total=T, logo_w=300)
    glow(im, (W / 2 - 420, 420, W / 2 + 420, 980), (90, 255, 60, 55), 110)
    neon_text(im, (90, 430), "Únete gratis", 110, W - 180)
    text_block(im, (140, 590), "Recibe el pick gratis de cada día en nuestro canal de Telegram.",
               "Regular", 44, WHITE, W - 280, center=True)
    d = ImageDraw.Draw(im)
    btn = "t.me/stakevision"
    fb = _font("Bold", 48)
    bw = d.textlength(btn, font=fb) + 120
    x = (W - bw) / 2
    d.rounded_rectangle((x, 800, x + bw, 910), 55, fill=(124, 220, 90))
    d.text((x + 60, 822), btn, font=fb, fill=(10, 14, 10))
    text_block(im, (90, 960), "Link en la bio", "Medium", 36, GREY, W - 180, center=True)
    text_block(im, (90, 1180), "+18 · Juega con responsabilidad. Apostar implica riesgo de pérdida.",
               "Regular", 26, (130, 132, 138), W - 180, center=True)
    save(im, "bienvenida-5.jpg")


# ------------------------------------------------------------------ carrusel 2: stake
def stake():
    T = 3
    im, top = frame(page=1, total=T, logo_w=300)
    glow(im, (W / 2 - 420, 420, W / 2 + 420, 980), (90, 255, 60, 50), 110)
    text_block(im, (90, 470), "GUÍA RÁPIDA", "Medium", 38, GREY, W - 180, center=True)
    neon_text(im, (90, 530), "¿Qué es", 120, W - 180)
    neon_text(im, (90, 670), "el stake?", 120, W - 180)
    text_block(im, (140, 870), "Cuánto apostar en cada pick, explicado en 30 segundos.", "Regular", 42, WHITE, W - 280, center=True)
    save(im, "stake-1.jpg")

    im, top = frame(page=2, total=T)
    text_block(im, (90, top + 50), "STAKE = CONFIANZA", "Medium", 30, (110, 230, 80), W - 180)
    text_block(im, (90, top + 95), "Una escala del 1 al 10", "Bold", 64, WHITE, W - 180)
    text_block(im, (90, top + 190), "Cada punto equivale al 0,5% de tu bankroll (el dinero que separas solo para apostar).",
               "Regular", 34, GREY, W - 180, gap=1.35)
    y = top + 380
    examples = [(3, "Cuota justa"), (5, "Valor claro"), (8, "Máxima confianza")]
    for st, label in examples:
        card(im, (90, y, W - 90, y + 200), 28)
        d = ImageDraw.Draw(im)
        d.text((130, y + 30), f"{st}/10", font=_font("Bold", 52), fill=INK)
        d.text((300, y + 46), label, font=_font("Medium", 30), fill=SOFT)
        pct = f"{st * 0.5:g}%".replace(".", ",") + " del bankroll"
        fp = _font("Bold", 30)
        d.text((W - 130 - d.textlength(pct, font=fp), y + 46), pct, font=fp, fill=GREEN)
        segw, gap = 66, 10
        for k in range(10):
            x = 130 + k * (segw + gap)
            d.rounded_rectangle((x, y + 125, x + segw, y + 145), 8, fill=(58, 190, 58) if k < st else (226, 228, 232))
        y += 228
    save(im, "stake-2.jpg")

    im, top = frame(page=3, total=T)
    text_block(im, (90, top + 50), "NUESTRA REGLA", "Medium", 30, (110, 230, 80), W - 180)
    text_block(im, (90, top + 95), "Nunca 9 ni 10", "Bold", 72, WHITE, W - 180)
    text_block(im, (90, top + 200), "Ninguna apuesta es segura. Por eso nuestros stakes van del 3 al 8, y las combinadas llevan un punto menos.",
               "Regular", 36, GREY, W - 180, gap=1.35)
    y = top + 430
    card(im, (90, y, W - 90, y + 380), 28)
    tips = ["Define tu bankroll y no lo superes", "Respeta el stake de cada pick", "Nunca persigas una pérdida"]
    yy = y + 50
    for t in tips:
        im.alpha_composite(_check_badge(44), (134, int(yy + 4)))
        text_block(im, (196, yy), t, "Medium", 38, INK, W - 340)
        yy += 105
    save(im, "stake-3.jpg")


# ------------------------------------------------------------------ juego responsable
def responsible():
    im, top = frame(logo_w=300)
    glow(im, (W / 2 - 300, 330, W / 2 + 300, 700), (255, 255, 255, 25), 90)
    d = ImageDraw.Draw(im)
    f = _font("Bold", 120)
    t = "+18"
    d.ellipse((W / 2 - 120, 330, W / 2 + 120, 570), outline=(235, 235, 238), width=8)
    d.text((W / 2 - d.textlength(t, font=f) / 2, 372), t, font=f, fill=(235, 235, 238))
    text_block(im, (90, 620), "Juega con responsabilidad", "Bold", 64, WHITE, W - 180, center=True)
    y = 730
    card(im, (90, y, W - 90, y + 430), 28)
    tips = ["Apuesta solo lo que puedas perder", "Pon límites de tiempo y dinero", "Si deja de ser entretenido, para",
            "Pedir ayuda es parte del juego"]
    yy = y + 45
    for tip in tips:
        im.alpha_composite(_check_badge(42), (134, int(yy + 4)))
        text_block(im, (194, yy), tip, "Medium", 36, INK, W - 340)
        yy += 92
    text_block(im, (90, 1210), "Ayuda en Chile: Salud Responde 600 360 7777", "Medium", 32, GREY, W - 180, center=True)
    save(im, "responsable.jpg")


# ------------------------------------------------------------------ historias para destacados
def stories():
    items = [("empieza", "Empieza aquí", "Cómo funciona Stakevision", "soccer"),
             ("verdes", "Verdes", "Nuestros picks acertados", None),
             ("stake", "Stake", "Cuánto apostar en cada pick", None),
             ("plus18", "+18", "Juega con responsabilidad", None)]
    for key, title, sub, sport in items:
        im = _background(1920).convert("RGBA")
        glow(im, (W / 2 - 380, 560, W / 2 + 380, 1320), (90, 255, 60, 60), 120)
        # icono centrado (lo que se ve como portada del destacado)
        cx, cy, r = W // 2, 860, 230
        ImageDraw.Draw(im).ellipse((cx - r, cy - r, cx + r, cy + r), fill=(22, 24, 26), outline=(124, 230, 90), width=6)
        if key == "verdes":
            im.alpha_composite(_check_badge(250), (cx - 125, cy - 125))
        elif key == "plus18":
            f = _font("Bold", 150)
            d = ImageDraw.Draw(im)
            d.text((cx - d.textlength("+18", font=f) / 2, cy - 105), "+18", font=f, fill=NEON)
        elif key == "stake":
            d = ImageDraw.Draw(im)
            for k, hgt in enumerate((70, 120, 170, 220)):
                x = cx - 150 + k * 80
                d.rounded_rectangle((x, cy + 110 - hgt, x + 55, cy + 110), 12, fill=NEON if k < 3 else (70, 74, 80))
        else:
            im.alpha_composite(_icon(sport, 250, NEON), (cx - 125, cy - 125))
        logo = Image.open(LOGO).convert("RGBA")
        lw = 300
        logo = logo.resize((lw, round(logo.height * lw / logo.width)), Image.LANCZOS)
        im.alpha_composite(logo, ((W - lw) // 2, 150))
        neon_text(im, (90, 1180), title, 110, W - 180)
        text_block(im, (90, 1330), sub, "Regular", 44, WHITE, W - 180, center=True)
        text_block(im, (90, 1720), "@stakevision · +18", "Medium", 32, GREY, W - 180, center=True)
        save(im, f"historia-{key}.jpg")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    profile_photo()
    welcome()
    stake()
    responsible()
    stories()
    print("Listo:", sorted(os.listdir(OUT)))
