"""Imagen de cada pick para los canales (estilo de los posteos de Stakevision).

Fondo oscuro con textura, logo con los ojos, tarjeta blanca con las selecciones
(como un cupón de apuesta), ícono del deporte y la cuenta de Instagram al pie.
Solo usa Pillow: corre en GitHub Actions sin instalar nada más.
"""
from __future__ import annotations

import io
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from . import config, formatting

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "assets", "fonts")
POST = os.path.join(HERE, "assets", "post")
LOGO = os.path.join(config.ROOT, "docs", "assets", "logo-full-dark.png")

W = 1080
INK, SOFT, MUTED, LINE = (17, 19, 24), (52, 56, 64), (128, 134, 145), (230, 232, 236)
GREEN = (46, 150, 46)
SPORT_COLOR = {"soccer": (29, 36, 51), "tennis": (150, 178, 0), "basketball": (224, 122, 31)}
INSTAGRAM = "stakevision"


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(os.path.join(FONTS, f"Poppins-{weight}.ttf"), size)


def _icon(sport: str, size: int, color=(255, 255, 255)) -> Image.Image:
    path = os.path.join(POST, f"icon-{sport}.png")
    if not os.path.exists(path):
        path = os.path.join(POST, "icon-soccer.png")
    a = Image.open(path).convert("RGBA").getchannel("A").resize((size, size), Image.LANCZOS)
    im = Image.new("RGBA", (size, size), color + (255,))
    im.putalpha(a)
    return im


def _background(h: int) -> Image.Image:
    base = Image.new("RGB", (W, h), (43, 43, 45))
    # textura tipo concreto: ruido suave en dos escalas
    fine = Image.effect_noise((W, h), 22).filter(ImageFilter.GaussianBlur(0.8))
    coarse = Image.effect_noise((W // 8, h // 8), 40).resize((W, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(6))
    tex = ImageChops.blend(fine, coarse, 0.5)
    base = Image.composite(Image.new("RGB", (W, h), (58, 58, 61)), base, tex.point(lambda v: max(0, v - 100)))
    # viñeta
    vg = Image.radial_gradient("L").resize((W, h)).point(lambda v: int(v * 0.55))
    return Image.composite(Image.new("RGB", (W, h), (16, 16, 18)), base, vg)


def _fit(draw, text, weight, size, max_w, min_size=22):
    while size > min_size and draw.textlength(text, font=_font(weight, size)) > max_w:
        size -= 2
    f = _font(weight, size)
    while draw.textlength(text, font=f) > max_w and len(text) > 4:
        text = text[:-2].rstrip() + "…"
    return text, f


MARKET_NAME = {"1x2": "Resultado final", "totals": "Total de goles", "bothteamsscore": "Ambos marcan",
               "spreads": "Hándicap asiático", "drawnobet": "Empate no apuesta"}


def _market(l: dict) -> str:
    t = l.get("mtype") or ""
    if t in MARKET_NAME:
        return MARKET_NAME[t]
    if t.startswith("teamtotals"):
        return f"Goles de {l['home'] if t.endswith('1') else l['away']}"
    if t.startswith("toscore"):
        return f"Marca {l['home'] if t.endswith('1') else l['away']}"
    return l.get("market") or ""


def _selection_parts(l: dict) -> tuple[str, str]:
    sel = formatting.outcome_label(l)
    if " (" in sel and sel.endswith(")"):
        i = sel.index(" (")
        note = sel[i + 2:-1]
        if note.lower().startswith("hándicap asiático"):   # ya lo dice la línea del mercado
            note = note[len("hándicap asiático"):].lstrip(";, ")
        return sel[:i], note
    return sel, ""


def _when(iso: str) -> tuple[str, str]:
    t = formatting.local_time(iso)          # "19/10 15:45 p. m."
    day, _, hour = t.partition(" ")
    return day, hour


def _leg_height(l: dict) -> int:
    return 230 if _selection_parts(l)[1] else 196


def render(pick: dict) -> bytes:
    legs = pick["legs"]
    sports = []
    for l in legs:
        s = l.get("sport") or "soccer"
        if s not in sports:
            sports.append(s)

    card_x, card_w, pad = 90, W - 180, 44
    legs_h = sum(_leg_height(l) for l in legs) + 36 * (len(legs) - 1)
    card_h = pad + legs_h + 24 + 86          # + barra de stake/cuota
    logo_w = 540
    top = 60
    logo = Image.open(LOGO).convert("RGBA")
    logo = logo.resize((logo_w, round(logo.height * logo_w / logo.width)), Image.LANCZOS)
    card_y = top + logo.height + 46
    icon_size = 150
    icon_y = card_y + card_h + 60
    footer_y = icon_y + icon_size + 70
    H = max(1080, footer_y + 70)
    if H > 1080:  # en dobles la imagen crece a lo alto (formato 4:5 como máximo)
        H = max(H, 1080)

    im = _background(H).convert("RGBA")
    # resplandor verde detrás de los ojos
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((W / 2 - 300, top - 20, W / 2 + 300, top + 200), fill=(90, 255, 60, 38))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(60)))
    im.alpha_composite(logo, ((W - logo.width) // 2, top))

    # tarjeta con sombra
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((card_x, card_y + 14, card_x + card_w, card_y + card_h + 14), 34, fill=(0, 0, 0, 150))
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(22)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((card_x, card_y, card_x + card_w, card_y + card_h), 34, fill=(255, 255, 255))

    x0, x1 = card_x + pad, card_x + card_w - pad
    y = card_y + pad
    for i, l in enumerate(legs):
        if i:
            d.line((x0, y - 18, x1, y - 18), fill=LINE, width=2)
        sport = l.get("sport") or "soccer"
        im.alpha_composite(_icon(sport, 46, SPORT_COLOR.get(sport, INK)), (x0, y + 4))
        odds = formatting.odds(l["price"])
        fo = _font("Bold", 44)
        ow = d.textlength(odds, font=fo)
        d.text((x1 - ow, y - 2), odds, font=fo, fill=INK)
        sel, note = _selection_parts(l)
        sel, fs = _fit(d, sel, "Bold", 42, x1 - ow - 40 - (x0 + 64))
        d.text((x0 + 64, y - 2), sel, font=fs, fill=INK)
        y += 60
        market, fm = _fit(d, _market(l), "Regular", 30, x1 - x0)
        d.text((x0, y), market, font=fm, fill=MUTED)
        y += 42
        if note:
            note, fn = _fit(d, note[0].upper() + note[1:], "Regular", 26, x1 - x0)
            d.text((x0, y), note, font=fn, fill=GREEN)
            y += 36
        day, hour = _when(l["kickoff"])
        fr = _font("Medium", 28)
        right_w = max(d.textlength(day, font=fr), d.textlength(hour, font=fr))
        for j, team in enumerate((l["home"], l["away"])):
            t, ft = _fit(d, team, "Regular", 33, x1 - x0 - right_w - 30)
            d.text((x0, y + j * 44), t, font=ft, fill=SOFT)
        d.text((x1 - d.textlength(day, font=fr), y + 2), day, font=fr, fill=GREEN)
        d.text((x1 - d.textlength(hour, font=fr), y + 46), hour, font=fr, fill=GREEN)
        y += 94 + 36

    # barra inferior: stake y cuota total
    by = card_y + card_h - 86
    d.rounded_rectangle((card_x, by, card_x + card_w, card_y + card_h), 34, fill=(243, 244, 246))
    d.rectangle((card_x, by, card_x + card_w, by + 34), fill=(243, 244, 246))
    fl, fv = _font("Medium", 26), _font("Bold", 34)
    d.text((x0, by + 26), "STAKE", font=fl, fill=MUTED)
    stake = f"{pick['stake']}/10"
    d.text((x0 + d.textlength("STAKE", font=fl) + 16, by + 19), stake, font=fv, fill=INK)
    total = formatting.odds(pick["price"])
    lab = "CUOTA TOTAL" if len(legs) > 1 else "CUOTA"
    tw = d.textlength(total, font=fv)
    d.text((x1 - tw, by + 19), total, font=fv, fill=GREEN)
    d.text((x1 - tw - 16 - d.textlength(lab, font=fl), by + 26), lab, font=fl, fill=MUTED)

    # ícono(s) del deporte
    n = len(sports)
    gap = 60
    sx = (W - (n * icon_size + (n - 1) * gap)) // 2
    for k, s in enumerate(sports):
        ic = _icon(s, icon_size)
        halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        cx, cy = sx + k * (icon_size + gap) + icon_size // 2, icon_y + icon_size // 2
        ImageDraw.Draw(halo).ellipse((cx - 110, cy - 110, cx + 110, cy + 110), fill=(120, 255, 80, 26))
        im.alpha_composite(halo.filter(ImageFilter.GaussianBlur(30)))
        im.alpha_composite(ic, (sx + k * (icon_size + gap), icon_y))

    # pie: Instagram
    ig = Image.open(os.path.join(POST, "instagram.png")).convert("RGBA").resize((46, 46), Image.LANCZOS)
    ff = _font("Medium", 34)
    tw = d.textlength(INSTAGRAM, font=ff)
    fx = (W - (46 + 14 + tw)) // 2
    fy = H - 92
    im.alpha_composite(ig, (int(fx), fy))
    d = ImageDraw.Draw(im)
    d.text((fx + 60, fy - 1), INSTAGRAM, font=ff, fill=(240, 240, 240))

    out = io.BytesIO()
    im.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


# ---------------------------------------------------------------- celebración (verde)
def _confetti(im: Image.Image, area: tuple[int, int, int, int], n: int, seed: int) -> None:
    import random
    rnd = random.Random(seed)
    colors = [(124, 255, 90), (90, 220, 70), (200, 255, 170), (255, 255, 255), (60, 190, 60)]
    x0, y0, x1, y1 = area
    placed = 0
    while placed < n:
        px, py = rnd.randint(x0, x1), rnd.randint(y0, y1)
        if 200 < px < 860:          # el centro queda libre para el logo y el titular
            continue
        placed += 1
        w, h = rnd.randint(8, 18), rnd.randint(16, 34)
        piece = Image.new("RGBA", (w, h), rnd.choice(colors) + (rnd.randint(150, 255),))
        piece = piece.rotate(rnd.randint(0, 179), expand=True, resample=Image.BICUBIC)
        im.alpha_composite(piece, (px, py))


def _check_badge(size: int) -> Image.Image:
    s = size * 4
    b = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(b)
    d.ellipse((0, 0, s - 1, s - 1), fill=(58, 190, 58))
    w = s // 11
    d.line([(s * 0.28, s * 0.52), (s * 0.44, s * 0.68), (s * 0.73, s * 0.36)], fill="white", width=w, joint="curve")
    for x, y in ((s * 0.28, s * 0.52), (s * 0.44, s * 0.68), (s * 0.73, s * 0.36)):
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill="white")
    return b.resize((size, size), Image.LANCZOS)


def _return_badge(size: int) -> Image.Image:
    s = size * 4
    b = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(b)
    d.ellipse((0, 0, s - 1, s - 1), fill=(150, 156, 166))
    w = s // 12
    d.arc((s * 0.26, s * 0.26, s * 0.74, s * 0.74), 200, 520, fill="white", width=w)
    d.polygon([(s * 0.22, s * 0.30), (s * 0.40, s * 0.30), (s * 0.27, s * 0.47)], fill="white")
    return b.resize((size, size), Image.LANCZOS)


def render_win(pick: dict, streak: int = 1, result: str = "W") -> bytes:
    """Imagen 1080x1350 (formato vertical de Instagram) para un pick verde o nulo."""
    nula = result == "V"
    H = 1350
    im = _background(H).convert("RGBA")
    d = ImageDraw.Draw(im)

    # resplandor verde detrás del titular
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((W / 2 - 420, 250, W / 2 + 420, 640),
                                 fill=(180, 186, 196, 40) if nula else (90, 255, 60, 60))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(90)))
    legs = pick["legs"]
    compact = len(legs) > 1
    if not nula:
        _confetti(im, (30, 120, W - 50, 660 if not compact else 480), 46, seed=int(pick.get("id") or 0) * 7 + 3)

    logo = Image.open(LOGO).convert("RGBA")
    lw = 330 if not compact else 260
    logo = logo.resize((lw, round(logo.height * lw / logo.width)), Image.LANCZOS)
    im.alpha_composite(logo, ((W - lw) // 2, 50))

    # titular
    y = 50 + logo.height + (40 if not compact else 10)
    if not compact:
        badge = _return_badge(120) if nula else _check_badge(120)
        im.alpha_composite(badge, ((W - 120) // 2, y))
        y += 140
    title = "NULA" if nula else "¡VERDE!"
    ft = _font("Bold", 150 if not compact else 120)
    tw = d.textlength(title, font=ft)
    tglow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(tglow).text(((W - tw) / 2, y), title, font=ft,
                               fill=(200, 205, 215, 255) if nula else (110, 255, 80, 255))
    im.alpha_composite(tglow.filter(ImageFilter.GaussianBlur(18)))
    d = ImageDraw.Draw(im)
    d.text(((W - tw) / 2, y), title, font=ft, fill=(225, 228, 234) if nula else (150, 255, 110))
    y += 190 if not compact else 155
    sub = ("Apuesta devuelta: no se pierde nada" if nula else
           f"{streak} verdes seguidos" if streak >= 2 else "Lo vimos antes del pitazo")
    fs = _font("Medium", 40)
    d.text(((W - d.textlength(sub, font=fs)) / 2, y), sub, font=fs, fill=(235, 235, 235))
    y += 90 if not compact else 72

    # tarjeta con el resultado
    card_x, card_w, pad = 90, W - 180, 44
    leg_h = 250
    card_h = pad + leg_h * len(legs) + 30 * (len(legs) - 1) + 96
    card_y = y
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((card_x, card_y + 14, card_x + card_w, card_y + card_h + 14), 34, fill=(0, 0, 0, 150))
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(22)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((card_x, card_y, card_x + card_w, card_y + card_h), 34, fill=(255, 255, 255))
    x0, x1 = card_x + pad, card_x + card_w - pad
    cy = card_y + pad
    for i, l in enumerate(legs):
        if i:
            d.line((x0, cy - 16, x1, cy - 16), fill=LINE, width=2)
        sport = l.get("sport") or "soccer"
        im.alpha_composite(_icon(sport, 40, SPORT_COLOR.get(sport, INK)), (x0, cy + 2))
        league, fl = _fit(d, l.get("league") or "", "Medium", 28, x1 - x0 - 56)
        d.text((x0 + 56, cy + 2), league, font=fl, fill=MUTED)
        cy += 62
        # marcador: Local  0 - 3  Visita
        sc = l.get("score")
        fteam = _font("Bold", 36)
        mid = W // 2
        if sc:
            score = f"{sc[0]} - {sc[1]}"
            fsc = _font("Bold", 64)
            sw = d.textlength(score, font=fsc)
            d.text((mid - sw / 2, cy - 8), score, font=fsc, fill=INK)
            home, fh = _fit(d, l["home"], "Bold", 36, mid - sw / 2 - 30 - x0)
            away, fa = _fit(d, l["away"], "Bold", 36, x1 - (mid + sw / 2 + 30))
            d.text((x0, cy + 6), home, font=fh, fill=INK)
            d.text((x1 - d.textlength(away, font=fa), cy + 6), away, font=fa, fill=INK)
        else:
            m, fm = _fit(d, f"{l['home']} vs {l['away']}", "Bold", 36, x1 - x0)
            d.text((x0, cy + 6), m, font=fm, fill=INK)
        cy += 92
        sel = formatting.outcome_label(l)
        if " (" in sel:
            sel = sel[:sel.index(" (")]
        sel, fsel = _fit(d, sel, "Bold", 36, x1 - x0 - 230)
        d.rounded_rectangle((x0, cy, x1, cy + 72), 18, fill=(240, 241, 244) if nula else (236, 249, 234))
        d.text((x0 + 22, cy + 13), sel, font=fsel, fill=SOFT if nula else (30, 110, 30))
        ok = "Devuelta" if nula else "Acertado"
        fok = _font("Bold", 28)
        okw = d.textlength(ok, font=fok)
        d.text((x1 - 22 - okw, cy + 20), ok, font=fok, fill=MUTED if nula else (46, 150, 46))
        im.alpha_composite(_return_badge(30) if nula else _check_badge(30), (int(x1 - 22 - okw - 40), int(cy + 22)))
        d = ImageDraw.Draw(im)
        cy += 72 + 24 + 30
    by = card_y + card_h - 96
    d.rounded_rectangle((card_x, by, card_x + card_w, card_y + card_h), 34, fill=(243, 244, 246))
    d.rectangle((card_x, by, card_x + card_w, by + 34), fill=(243, 244, 246))
    fl, fv = _font("Medium", 26), _font("Bold", 40)
    lab = "CUOTA TOTAL" if len(legs) > 1 else "CUOTA"
    total = formatting.odds(pick["price"])
    d.text((x0, by + 32), lab, font=fl, fill=MUTED)
    d.text((x0 + d.textlength(lab, font=fl) + 16, by + 22), total, font=fv, fill=SOFT if nula else GREEN)
    st = f"STAKE {pick['stake']}/10"
    d.text((x1 - d.textlength(st, font=fl), by + 32), st, font=fl, fill=MUTED)

    # pie
    ff = _font("Medium", 32)
    ig = Image.open(os.path.join(POST, "instagram.png")).convert("RGBA").resize((42, 42), Image.LANCZOS)
    tw = d.textlength(INSTAGRAM, font=ff)
    fx = (W - (42 + 14 + tw)) // 2
    fy = H - 130
    im.alpha_composite(ig, (int(fx), fy))
    d = ImageDraw.Draw(im)
    d.text((fx + 56, fy - 2), INSTAGRAM, font=ff, fill=(240, 240, 240))
    note = "+18 · Juega con responsabilidad"
    fn = _font("Regular", 24)
    d.text(((W - d.textlength(note, font=fn)) / 2, H - 70), note, font=fn, fill=(150, 150, 155))

    out = io.BytesIO()
    im.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


def fit_instagram(jpeg: bytes) -> bytes:
    """Instagram acepta de 4:5 (vertical) a 1.91:1. Si la imagen es más alta, se encaja en 1080x1350."""
    im = Image.open(io.BytesIO(jpeg)).convert("RGB")
    if im.height <= 1350:
        return jpeg
    scale = 1350 / im.height
    small = im.resize((round(im.width * scale), 1350), Image.LANCZOS)
    canvas = _background(1350).convert("RGB")
    canvas.paste(small, ((W - small.width) // 2, 0))
    out = io.BytesIO()
    canvas.save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


# ---------------------------------------------------------------- piezas de contenido
def _logo(w: int) -> Image.Image:
    lg = Image.open(LOGO).convert("RGBA")
    return lg.resize((w, round(lg.height * w / lg.width)), Image.LANCZOS)


def _glow(im, box, color=(90, 255, 60, 55), blur=90):
    g = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse(box, fill=color)
    im.alpha_composite(g.filter(ImageFilter.GaussianBlur(blur)))


def _card(im, box, r=30):
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + 12, x1, y1 + 12), r, fill=(0, 0, 0, 140))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(20)))
    ImageDraw.Draw(im).rounded_rectangle(box, r, fill=(255, 255, 255))


def _ctext(d, y, text, font, fill, w=W):
    d.text(((w - d.textlength(text, font=font)) / 2, y), text, font=font, fill=fill)


def _jpeg(im) -> bytes:
    out = io.BytesIO()
    im.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


def render_weekly(week: dict) -> bytes:
    """Resumen semanal 1080x1350. week = {label, picks:[{home,away,res,price,stake}], units, yield, hits, total}."""
    H = 1350
    im = _background(H).convert("RGBA")
    _glow(im, (W / 2 - 380, -80, W / 2 + 380, 380), (90, 255, 60, 45), 90)
    lg = _logo(260)
    im.alpha_composite(lg, ((W - lg.width) // 2, 46))
    d = ImageDraw.Draw(im)
    y = 46 + lg.height + 26
    _ctext(d, y, "RESUMEN SEMANAL", _font("Medium", 30), (150, 230, 120))
    _ctext(d, y + 44, week["label"], _font("Bold", 54), (240, 240, 242))
    # cifras
    y += 140
    units = week["units"]
    tiles = [("Puntos", f"{'+' if units >= 0 else ''}{units:.1f}".replace(".", ",")),
             ("Acierto", f"{week['hits']}/{week['total']}"),
             ("Yield", f"{'+' if week['yield'] >= 0 else ''}{week['yield'] * 100:.1f}%".replace(".", ","))]
    tw, gap = 286, 21
    for i, (lab, val) in enumerate(tiles):
        x = 90 + i * (tw + gap)
        d.rounded_rectangle((x, y, x + tw, y + 150), 26, fill=(22, 24, 26), outline=(52, 58, 52), width=2)
        fv = _font("Bold", 56)
        col = (150, 255, 110) if (i != 1 and (units >= 0 if i == 0 else week["yield"] >= 0)) else (240, 240, 242)
        if i != 1 and (units < 0 if i == 0 else week["yield"] < 0):
            col = (255, 120, 110)
        d.text((x + (tw - d.textlength(val, font=fv)) / 2, y + 24), val, font=fv, fill=col)
        fl = _font("Medium", 26)
        d.text((x + (tw - d.textlength(lab, font=fl)) / 2, y + 98), lab, font=fl, fill=(170, 172, 178))
    # lista de picks
    y += 190
    rows = week["picks"][:8]
    _card(im, (90, y, W - 90, y + 40 + 84 * len(rows)))
    d = ImageDraw.Draw(im)
    yy = y + 22
    for k, p in enumerate(rows):
        if k:
            d.line((130, yy - 4, W - 130, yy - 4), fill=LINE, width=2)
        badge = {"W": (_check_badge(44), "Verde", GREEN), "L": (None, "Roja", (194, 38, 26)),
                 "V": (None, "Nula", MUTED)}[p["res"]]
        if p["res"] == "W":
            im.alpha_composite(badge[0], (130, int(yy + 14)))
        else:
            d.ellipse((130, yy + 14, 174, yy + 58), fill=badge[2])
            glyph = "✕" if p["res"] == "L" else "↺"
            fg = _font("Bold", 26)
            if p["res"] == "L":
                d.line((143, yy + 27, 161, yy + 45), fill="white", width=5)
                d.line((161, yy + 27, 143, yy + 45), fill="white", width=5)
            else:
                d.arc((141, yy + 25, 163, yy + 47), 200, 520, fill="white", width=4)
        d = ImageDraw.Draw(im)
        name, fn = _fit(d, f"{p['home']} vs {p['away']}", "Medium", 32, W - 130 - 196 - 190)
        d.text((196, yy + 16), name, font=fn, fill=INK)
        right = f"@{p['price']:.2f}"
        fr = _font("Bold", 30)
        d.text((W - 130 - d.textlength(right, font=fr), yy + 18), right, font=fr, fill=SOFT)
        yy += 84
    # pie
    d = ImageDraw.Draw(im)
    _ctext(d, H - 150, "Historial completo en la web · link en la bio", _font("Medium", 30), (225, 225, 228))
    _ctext(d, H - 96, "@stakevision · +18 · Juega con responsabilidad", _font("Regular", 24), (150, 150, 155))
    return _jpeg(im)


def render_story(pick: dict) -> bytes:
    """Historia vertical 1080x1920 del pick gratis del día."""
    H = 1920
    im = _background(H).convert("RGBA")
    _glow(im, (W / 2 - 420, 120, W / 2 + 420, 760), (90, 255, 60, 60), 110)
    lg = _logo(420)
    im.alpha_composite(lg, ((W - lg.width) // 2, 150))
    d = ImageDraw.Draw(im)
    legs = pick["legs"]
    block = 76 + 64 + (120 + 300 * len(legs) + 120) + 90 + 190
    y = max(150 + lg.height + 60, (H - 140 - block) // 2 + 200)
    d.rounded_rectangle((W / 2 - 230, y, W / 2 + 230, y + 76), 38, fill=(124, 220, 90))
    _ctext(d, y + 14, "PICK GRATIS DE HOY", _font("Bold", 36), (10, 14, 10))
    y += 140
    card_h = 120 + 300 * len(legs) + 120
    _card(im, (80, y, W - 80, y + card_h), 40)
    d = ImageDraw.Draw(im)
    yy = y + 56
    for l in legs:
        sport = l.get("sport") or "soccer"
        league, fl = _fit(d, l.get("league") or "", "Medium", 32, W - 300)
        im.alpha_composite(_icon(sport, 44, SPORT_COLOR.get(sport, INK)), (130, int(yy)))
        d = ImageDraw.Draw(im)
        d.text((190, yy + 2), league, font=fl, fill=MUTED)
        yy += 70
        for team in (l["home"], l["away"]):
            t, ft = _fit(d, team, "Bold", 54, W - 260)
            d.text((130, yy), t, font=ft, fill=INK)
            yy += 70
        day, _, hour = formatting.local_time(l["kickoff"]).partition(" ")
        d.text((130, yy + 4), f"🕒 {hour}".replace("🕒 ", ""), font=_font("Medium", 34), fill=GREEN)
        yy += 70
        sel = formatting.outcome_label(l)
        sel = sel[:sel.index(" (")] if " (" in sel else sel
        d.rounded_rectangle((120, yy, W - 120, yy + 96), 24, fill=(236, 249, 234))
        s2, fs = _fit(d, sel, "Bold", 44, W - 460)
        d.text((150, yy + 22), s2, font=fs, fill=(30, 110, 30))
        od = formatting.odds(l["price"])
        fo = _font("Bold", 52)
        d.text((W - 150 - d.textlength(od, font=fo), yy + 16), od, font=fo, fill=INK)
        yy += 130
    d.text((130, yy), f"STAKE {pick['stake']}/10", font=_font("Medium", 32), fill=MUTED)
    # llamado
    d = ImageDraw.Draw(im)
    cy = y + card_h + 90
    _ctext(d, cy, "Análisis completo en Telegram", _font("Bold", 46), (240, 240, 242))
    d.rounded_rectangle((W / 2 - 290, cy + 90, W / 2 + 290, cy + 190), 50, fill=(124, 220, 90))
    _ctext(d, cy + 112, "t.me/stakevision", _font("Bold", 48), (10, 14, 10))
    _ctext(d, H - 130, "+18 · Juega con responsabilidad", _font("Regular", 30), (150, 150, 155))
    return _jpeg(im)


def render_postmatch(m: dict) -> bytes:
    """Noticia post partido 1080x1350 con datos reales: marcador, goles, estadísticas y el dato curioso."""
    H = 1350
    im = _background(H).convert("RGBA")
    _glow(im, (W / 2 - 420, 120, W / 2 + 420, 520), (90, 255, 60, 45), 100)
    lg = _logo(220)
    im.alpha_composite(lg, ((W - lg.width) // 2, 40))
    d = ImageDraw.Draw(im)
    y = 40 + lg.height + 22
    _ctext(d, y, ("FINAL · " + m["league"]).upper(), _font("Medium", 26), (150, 230, 120))
    y += 56
    # marcador
    fs = _font("Bold", 124)
    sc = f"{m['hg']}  -  {m['ag']}"
    _ctext(d, y, sc, fs, (245, 245, 247))
    fh = _font("Bold", 40)
    home, f1 = _fit(d, m["home"], "Bold", 40, 300)
    away, f2 = _fit(d, m["away"], "Bold", 40, 300)
    d.text((90, y + 52), home, font=f1, fill=(240, 240, 242))
    d.text((W - 90 - d.textlength(away, font=f2), y + 52), away, font=f2, fill=(240, 240, 242))
    y += 170
    # titular
    _card(im, (70, y, W - 70, y + 150), 30)
    d = ImageDraw.Draw(im)
    lines = []
    words, cur, ft = m["headline"].split(), "", _font("Bold", 40)
    for w_ in words:
        t = (cur + " " + w_).strip()
        if d.textlength(t, font=ft) <= W - 220:
            cur = t
        else:
            lines.append(cur)
            cur = w_
    lines.append(cur)
    yy = y + 75 - len(lines) * 26
    for ln in lines[:2]:
        _ctext(d, yy, ln, ft, INK)
        yy += 52
    y += 180
    # goles
    d.text((90, y), "GOLES", font=_font("Medium", 26), fill=(150, 230, 120))
    y += 44
    for g in m["goals"][:5]:
        d.text((90, y), g["min"], font=_font("Bold", 30), fill=(150, 255, 110))
        t, fg = _fit(d, f"{g['player']} ({g['team']})", "Medium", 30, W - 300)
        d.text((200, y), t, font=fg, fill=(240, 240, 242))
        y += 46
    y += 14
    # estadísticas: barras enfrentadas
    d.text((90, y), "ESTADÍSTICAS", font=_font("Medium", 26), fill=(150, 230, 120))
    y += 48
    for lab, a, b, fmt in m["stats"][:3]:
        tot = (a + b) or 1
        d.text((90, y), fmt(a), font=_font("Bold", 32), fill=(240, 240, 242))
        bt = fmt(b)
        d.text((W - 90 - d.textlength(bt, font=_font("Bold", 32)), y), bt, font=_font("Bold", 32), fill=(240, 240, 242))
        _ctext(d, y + 4, lab, _font("Medium", 26), (170, 172, 178))
        bx0, bx1, by = 90, W - 90, y + 48
        split = bx0 + (bx1 - bx0) * a / tot
        d.rounded_rectangle((bx0, by, split - 3, by + 12), 6, fill=(124, 220, 90))
        d.rounded_rectangle((split + 3, by, bx1, by + 12), 6, fill=(110, 116, 124))
        y += 74
    # nuestro pick
    if m.get("pick"):
        p = m["pick"]
        y = H - 190
        ok = p["res"] == "W"
        d.rounded_rectangle((90, y, W - 90, y + 96), 26, fill=(28, 52, 26) if ok else (40, 42, 46))
        if ok:
            im.alpha_composite(_check_badge(52), (120, int(y + 22)))
        d = ImageDraw.Draw(im)
        txt, fp = _fit(d, f"Nuestro pick: {p['label']} @ {p['price']:.2f}", "Bold", 34, W - 320)
        d.text((190, y + 26), txt, font=fp, fill=(150, 255, 110) if ok else (230, 230, 232))
    _ctext(d, H - 70, "@stakevision · +18 · Juega con responsabilidad", _font("Regular", 24), (150, 150, 155))
    return _jpeg(im)
