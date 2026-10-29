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
    c1, c2 = tuple(c1), tuple(c2)
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
    d.rounded_rectangle((x, y, x + w, y + size + 26), (size + 26) // 2, fill=fill)
    d.text((x + pad, y + 13 + size / 2), text, font=f, fill=ink, anchor="lm")
    return w


def _footer(im, d, source: str, credit: str | None = None):
    y = H - 92
    if credit:   # crédito de la foto (licencia libre): en su propia línea, sobre la firma
        cf = P._font("Regular", 20)
        txt = credit
        while d.textlength(txt, font=cf) > P.W - 120 and len(txt) > 20:
            txt = txt[:-2]
        d.text((60, y - 52), txt if txt == credit else txt.rstrip() + "…", font=cf, fill=(190, 196, 206), anchor="lm")
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
    photo = bool(n.get("photo"))
    tf = P._font("Bold", 30)
    tw = d.textlength(n["tag"], font=tf) + 44
    _chip(d, P.W - 60 - tw, 70, n["tag"], n.get("tag_color", (255, 77, 64)), WHITE, 30)
    if n.get("status") and photo:   # con foto, el estado va arriba, bajo la etiqueta
        sw = d.textlength(n["status"], font=P._font("Bold", 24)) + 40
        _chip(d, P.W - 60 - sw, 138, n["status"], n.get("status_color", (255, 196, 0)), (20, 16, 4), 24, 20)
    # kicker + titular (con foto, el texto va en la mitad de abajo)
    y = 600 if photo else 250
    d.text((60, y), n["kicker"], font=P._font("Bold", 28 if photo else 30), fill=n.get("accent", (255, 196, 0)))
    y += 50
    hs, step = (112, 104) if photo else (132, 122)
    hf = _bebas(hs)
    for line in _wrap(d, n["headline"], hf, P.W - 120)[:2 if photo else 3]:
        d.text((60, y), line, font=hf, fill=WHITE)
        y += step
    if n.get("sub"):
        sf = P._font("Medium", 30 if photo else 34)
        for line in _wrap(d, n["sub"], sf, P.W - 120)[:2]:
            d.text((60, y + 6), line, font=sf, fill=(225, 230, 238))
            y += 42
    # tarjeta de datos
    y += 28
    ff = P._font("Medium", 28 if photo else 31)
    lh = 36 if photo else 40
    facts = n["facts"][:2] if photo else n["facts"]
    wrapped = [_wrap(d, f, ff, P.W - 200)[:2] for f in facts]
    box_h = 50 + sum(lh * len(w) + 24 for w in wrapped)
    panel = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle((48, y, P.W - 48, y + box_h), 28, fill=(10, 12, 18, 185))
    im.alpha_composite(panel)
    d = ImageDraw.Draw(im)
    yy = y + 32
    for lines in wrapped:
        d.ellipse((80, yy + 12, 94, yy + 26), fill=n.get("accent", (255, 196, 0)))
        for ln in lines:
            d.text((116, yy), ln, font=ff, fill=WHITE)
            yy += lh
        yy += 24
    if n.get("status") and not photo:
        _chip(d, 60, y + box_h + 30, n["status"], n.get("status_color", (255, 196, 0)), (20, 16, 4), 28)
    _footer(im, d, n["source"], n.get("credit"))
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
        if t["name"].upper() != t["short"].upper():
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


# ---------------------------------------------------------------- plantillas visuales (foto protagonista, poco texto)
def _full_photo(photo: bytes, size, colors, dark_from: float = 0.42) -> Image.Image:
    """Foto a toda la pantalla, con el protagonista centrado y un degradado oscuro abajo (con el color del equipo)."""
    w, h = size
    ph = P._enhance(P._cover(photo, (w, h), side="center")).convert("RGBA")
    c = tuple(colors[0]) if colors else (10, 12, 18)
    tint = tuple(int(v * 0.35) for v in c)
    grad = Image.new("RGBA", (w, h), tint + (0,))
    mask = Image.linear_gradient("L").resize((w, h)).point(
        lambda v: 0 if v < 255 * dark_from else int(min(255, (v - 255 * dark_from) / (255 * (1 - dark_from)) * 300)))
    grad.putalpha(mask)
    ph.alpha_composite(grad)
    top = Image.linear_gradient("L").resize((w, 300)).point(lambda v: int((255 - v) * 0.6))
    shade = Image.new("RGBA", (w, 300), (0, 0, 0, 255))
    shade.putalpha(top)
    ph.alpha_composite(shade, (0, 0))
    return ph


def _fit_line(d, text: str, font_fn, size: int, max_w: int, min_size: int = 60):
    while size > min_size and d.textlength(text, font=font_fn(size)) > max_w:
        size -= 4
    return font_fn(size)


def render_hero(n: dict) -> bytes:
    """Héroe: foto grande del protagonista + la cifra del día gigante («44 PUNTOS») + su nombre. Casi sin texto.
    n = {photo, colors, tag, name, stat:{value,label}, line, credit, source}"""
    im = _full_photo(n["photo"], (P.W, H), n.get("colors"), 0.36)
    d = ImageDraw.Draw(im)
    P._put_logo(im, 260, "dark", 56, 48)
    tf = P._font("Bold", 28)
    _chip(d, P.W - 60 - (d.textlength(n.get("tag", "NOTICIA"), font=tf) + 44), 64, n.get("tag", "NOTICIA"),
          n.get("tag_color", (255, 77, 64)), WHITE, 28)
    accent = n.get("accent", (255, 196, 0))
    lf = P._font("Medium", 34)
    lines = _wrap(d, n["line"], lf, P.W - 110)[:2] if n.get("line") else []
    name = str(n.get("name") or n.get("headline") or "").upper()
    nf = _fit_line(d, name, _bebas, 130, P.W - 110)
    bottom = H - 180                                  # sobre el crédito y la firma
    y_line = bottom - 46 * len(lines)
    y_name = y_line - nf.size - 4
    for i, ln in enumerate(lines):
        d.text((56, y_line + 46 * i), ln, font=lf, fill=(232, 236, 242))
    d.text((52, y_name), name, font=nf, fill=WHITE)
    st = n.get("stat") or {}
    if st.get("value"):
        vf = _bebas(300)
        y_stat = y_name - 270
        d.text((52, y_stat), str(st["value"]), font=vf, fill=accent)
        vw = d.textlength(str(st["value"]), font=vf)
        d.text((52 + vw + 22, y_stat + 150), str(st.get("label", "")).upper(), font=_bebas(96), fill=WHITE)
    _footer(im, d, n.get("source", ""), n.get("credit"))
    return P._jpeg(im)


def render_impact(n: dict) -> bytes:
    """Impacto: foto grande + titular enorme abajo. Para noticias sin una cifra protagonista.
    n = {photo, colors, tag, kicker, headline, line, credit, source}"""
    im = _full_photo(n["photo"], (P.W, H), n.get("colors"), 0.38)
    d = ImageDraw.Draw(im)
    P._put_logo(im, 260, "dark", 56, 48)
    tf = P._font("Bold", 28)
    _chip(d, P.W - 60 - (d.textlength(n.get("tag", "NOTICIA"), font=tf) + 44), 64, n.get("tag", "NOTICIA"),
          n.get("tag_color", (255, 77, 64)), WHITE, 28)
    hf = _bebas(150)
    lines = _wrap(d, str(n.get("headline", "")).upper(), hf, P.W - 110)[:3]
    y = H - 210 - 132 * len(lines) - (50 if n.get("line") else 0)
    if n.get("kicker"):
        d.text((56, y - 52), n["kicker"], font=P._font("Bold", 28), fill=n.get("accent", (255, 196, 0)))
    for ln in lines:
        d.text((52, y), ln, font=hf, fill=WHITE)
        y += 132
    if n.get("line"):
        lf = P._font("Medium", 32)
        d.text((56, y + 4), _wrap(d, n["line"], lf, P.W - 110)[0], font=lf, fill=(232, 236, 242))
    _footer(im, d, n.get("source", ""), n.get("credit"))
    return P._jpeg(im)


# ---------------------------------------------------------------- Versus (partido atractivo, fútbol o NBA)
def _half(photo: bytes | None, size, color) -> Image.Image:
    """Mitad del versus: foto del referente (encuadrada en su cara) teñida con el color del equipo, o solo el color."""
    w, h = size
    col = tuple(color)
    if photo:
        im = P._enhance(P._cover(photo, (w, h), side="center")).convert("RGBA")
        tint = Image.new("RGBA", (w, h), col + (70,))
        im.alpha_composite(tint)
    else:
        g = Image.linear_gradient("L").resize((w, h))
        base = tuple(int(v * 0.75) for v in col) if sum(col) > 560 else col   # colores muy claros: un poco más oscuros
        im = Image.composite(Image.new("RGB", (w, h), tuple(int(v * 0.30) for v in col)),
                             Image.new("RGB", (w, h), base), g).convert("RGBA")
    return im


def versus_base(v: dict, size) -> Image.Image:
    """Fondo del versus: dos mitades en diagonal, una por equipo, con sombra abajo para el texto."""
    w, h = size
    hw = int(w * 0.60)   # cada foto ocupa su mitad (con un poco de cruce): la cara queda a la vista
    im = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    im.paste(_half(v["home"].get("photo"), (hw, h), v["home"].get("color") or (30, 60, 140)), (0, 0))
    right = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    right.paste(_half(v["away"].get("photo"), (hw, h), v["away"].get("color") or (160, 30, 40)), (w - hw, 0))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon([(int(w * 0.58), 0), (w, 0), (w, h), (int(w * 0.42), h)], fill=255)
    im.paste(right, (0, 0), mask)
    d = ImageDraw.Draw(im)
    d.line([(int(w * 0.58), 0), (int(w * 0.42), h)], fill=(255, 255, 255, 230), width=8)
    shade = Image.new("RGBA", (w, h), (6, 8, 12, 0))
    shade.putalpha(Image.linear_gradient("L").resize((w, h)).point(lambda x: 0 if x < 140 else int((x - 140) * 2.0)))
    im.alpha_composite(shade)
    top = Image.new("RGBA", (w, 300), (0, 0, 0, 255))
    top.putalpha(Image.linear_gradient("L").resize((w, 300)).point(lambda x: int((255 - x) * 0.55)))
    im.alpha_composite(top, (0, 0))
    return im


def _vs_badge(size: int = 200) -> Image.Image:
    b = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(b)
    d.ellipse((0, 0, size - 1, size - 1), fill=(10, 12, 18, 235), outline=(255, 196, 0), width=8)
    d.text((size / 2, size / 2 + 6), "VS", font=_bebas(int(size * 0.55)), fill=(255, 196, 0), anchor="mm")
    return b


def render_versus(v: dict) -> bytes:
    """v = {home:{name, short, player, color, photo}, away:{...}, kicker, when, line, tag, credit, source}"""
    im = versus_base(v, (P.W, H))
    d = ImageDraw.Draw(im)
    P._put_logo(im, 260, "dark", 56, 48)
    tag = v.get("tag", "PARTIDO")
    tf = P._font("Bold", 28)
    _chip(d, P.W - 60 - (d.textlength(tag, font=tf) + 44), 64, tag, (255, 77, 64), WHITE, 28)
    b = _vs_badge(180)
    im.alpha_composite(b, ((P.W - b.width) // 2, H - 700))
    d = ImageDraw.Draw(im)
    y = H - 500
    for side, x, anchor in (("home", 56, "la"), ("away", P.W - 56, "ra")):
        t = v[side]
        nm = str(t.get("short") or t.get("name") or "").upper()
        nf = _fit_line(d, nm, _bebas, 120, P.W // 2 - 80)
        d.text((x, y), nm, font=nf, fill=WHITE, anchor=anchor)
        if t.get("player"):
            d.text((x, y + nf.size + 4), str(t["player"]), font=P._font("Medium", 28), fill=(225, 230, 238), anchor=anchor)
    yb = y + 168
    if v.get("kicker"):
        d.text((P.W / 2, yb), v["kicker"], font=P._font("Bold", 30), fill=(255, 196, 0), anchor="mt")
    if v.get("when"):
        d.text((P.W / 2, yb + 44), v["when"], font=P._font("Medium", 30), fill=WHITE, anchor="mt")
    _footer(im, d, v.get("source", ""), v.get("credit"))
    return P._jpeg(im)
