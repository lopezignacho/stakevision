"""Imágenes de contenido para Instagram (1080x1350): noticias y postpartidos de cualquier partido.

Sin escudos ni fotos de agencia: fondo con los colores del equipo, titular grande (Bebas Neue),
datos verificados en una tarjeta y la fuente al pie. Si hay una foto libre (Wikimedia Commons),
se puede poner detrás con su crédito.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

from . import postimage as P

H = 1350
WHITE = (255, 255, 255)


def _bebas(size: int):
    from PIL import ImageFont
    return ImageFont.truetype(f"{P.FONTS}/BebasNeue-Regular.ttf", size)


def _backdrop(c1, c2) -> Image.Image:
    """Diagonal con los dos colores del equipo, oscurecida, con textura y viñeta."""
    w = P.W
    grad = Image.linear_gradient("L").rotate(35, expand=True).resize((w, H))
    a = Image.new("RGB", (w, H), c1)
    b = Image.new("RGB", (w, H), c2)
    im = Image.composite(b, a, grad)
    dark = Image.new("RGB", (w, H), (8, 10, 14))
    im = Image.blend(im, dark, 0.55)
    noise = Image.effect_noise((w, H), 18).convert("RGB")
    im = Image.blend(im, noise, 0.05)
    vg = Image.radial_gradient("L").resize((w, H)).point(lambda v: int(v * 0.8))
    im = Image.composite(dark, im, vg)
    return im.convert("RGBA")


def _wrap(d, text, font, max_w) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if d.textlength(t, font=font) <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def _chip(d, x, y, text, fill, ink, size=30, pad=22):
    f = P._font("Bold", size)
    w = d.textlength(text, font=f) + pad * 2
    d.rounded_rectangle((x, y, x + w, y + size + 26), 999, fill=fill)
    d.text((x + pad, y + 13 + size / 2), text, font=f, fill=ink, anchor="lm")
    return w


def _footer(im, d, source: str):
    y = H - 92
    d.line((60, y - 24, P.W - 60, y - 24), fill=(255, 255, 255, 60), width=2)
    d.text((60, y + 10), source, font=P._font("Regular", 24), fill=(205, 210, 220), anchor="lm")
    ig = P._font("Medium", 30)
    tw = d.textlength("@" + P.INSTAGRAM, font=ig)
    d.text((P.W - 60 - tw, y + 10), "@" + P.INSTAGRAM, font=ig, fill=WHITE, anchor="lm")


def _photo_backdrop(photo: bytes, colors, focus=None) -> Image.Image:
    """Foto arriba a todo ancho que se funde hacia abajo con los colores del equipo (el texto queda legible)."""
    base = _backdrop(*colors)
    ph_h = 820
    ph = P._enhance(P._cover(photo, (P.W, ph_h), focus=focus)).convert("RGBA")
    mask = Image.linear_gradient("L").resize((P.W, ph_h)).point(lambda v: int(255 - max(0, v - 70) * 255 / 185))
    base.paste(ph, (0, 0), mask)
    shade = Image.new("RGBA", (P.W, H), (0, 0, 0, 0))   # sombra arriba para el logo
    top = Image.linear_gradient("L").resize((P.W, 260)).point(lambda v: int((255 - v) * 0.55))
    shade.paste(Image.new("RGBA", (P.W, 260), (0, 0, 0, 255)), (0, 0), top)
    base.alpha_composite(shade)
    return base


def render_news(n: dict) -> bytes:
    """n = {tag, tag_color, colors:[c1,c2], kicker, headline, sub, facts:[...], status, status_color, source,
    photo (bytes, opcional), photo_focus, credit}"""
    im = _photo_backdrop(n["photo"], n["colors"], n.get("photo_focus")) if n.get("photo") else _backdrop(*n["colors"])
    d = ImageDraw.Draw(im)
    P._put_logo(im, 300, "dark", 60, 54)
    _chip(d, P.W - 60 - 290, 70, n["tag"], n.get("tag_color", (255, 77, 64)), WHITE, 30)
    # kicker + titular (con foto, el texto empieza más abajo)
    y = 560 if n.get("photo") else 250
    d.text((60, y), n["kicker"], font=P._font("Bold", 30), fill=n.get("accent", (255, 196, 0)))
    y += 54
    hf = _bebas(132)
    for line in _wrap(d, n["headline"], hf, P.W - 120)[:3]:
        d.text((60, y), line, font=hf, fill=WHITE)
        y += 122
    if n.get("sub"):
        sf = P._font("Medium", 34)
        for line in _wrap(d, n["sub"], sf, P.W - 120)[:2]:
            d.text((60, y + 6), line, font=sf, fill=(225, 230, 238))
            y += 46
    # tarjeta de datos
    y += 34
    ff = P._font("Medium", 31)
    wrapped = [_wrap(d, f, ff, P.W - 200)[:2] for f in n["facts"]]
    box_h = 56 + sum(40 * len(w) + 30 for w in wrapped)
    panel = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle((48, y, P.W - 48, y + box_h), 28, fill=(10, 12, 18, 175))
    im.alpha_composite(panel)
    d = ImageDraw.Draw(im)
    yy = y + 36
    for lines in wrapped:
        d.ellipse((80, yy + 13, 94, yy + 27), fill=n.get("accent", (255, 196, 0)))
        for ln in lines:
            d.text((116, yy), ln, font=ff, fill=WHITE)
            yy += 40
        yy += 30
    if n.get("status"):
        _chip(d, 60, y + box_h + 30, n["status"], n.get("status_color", (255, 196, 0)), (20, 16, 4), 28)
    _footer(im, d, n["source"])
    return P._jpeg(im)


def render_postgame(g: dict) -> bytes:
    """g = {colors, kicker, home:{name, short, score, color}, away:{...}, winner:'home'|'away', when, notes:[...], source}"""
    im = _backdrop(*g["colors"])
    d = ImageDraw.Draw(im)
    P._put_logo(im, 300, "dark", 60, 54)
    _chip(d, P.W - 60 - 200, 70, "FINAL", (255, 255, 255), (12, 14, 20), 30)
    d.text((60, 250), g["kicker"], font=P._font("Bold", 30), fill=(255, 196, 0))
    # marcador
    y = 320
    for side in ("home", "away"):
        t = g[side]
        win = g["winner"] == side
        d.rounded_rectangle((60, y, 72, y + 150), 6, fill=t["color"])
        d.text((100, y + 4), t["short"].upper(), font=_bebas(120), fill=WHITE if win else (175, 182, 194))
        d.text((100, y + 120), t["name"], font=P._font("Medium", 28), fill=(205, 210, 220))
        sc = str(t["score"])
        sf = _bebas(170)
        d.text((P.W - 60 - d.textlength(sc, font=sf), y - 8), sc, font=sf, fill=WHITE if win else (175, 182, 194))
        y += 190
    d.text((60, y - 6), g["when"], font=P._font("Regular", 26), fill=(205, 210, 220))
    # claves del partido
    y += 50
    ff = P._font("Medium", 30)
    wrapped = [_wrap(d, x, ff, P.W - 200)[:2] for x in g["notes"]]
    box_h = 100 + sum(38 * len(w) + 28 for w in wrapped)
    panel = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle((48, y, P.W - 48, y + box_h), 28, fill=(10, 12, 18, 175))
    im.alpha_composite(panel)
    d = ImageDraw.Draw(im)
    d.text((80, y + 30), "LO QUE DEJÓ EL PARTIDO", font=P._font("Bold", 26), fill=(255, 196, 0))
    yy = y + 84
    for lines in wrapped:
        d.ellipse((80, yy + 12, 94, yy + 26), fill=(255, 196, 0))
        for ln in lines:
            d.text((116, yy), ln, font=ff, fill=WHITE)
            yy += 38
        yy += 28
    _footer(im, d, g["source"])
    return P._jpeg(im)
