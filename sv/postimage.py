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


def render(pick: dict, tier: str | None = None) -> bytes:
    """Cupón del pick. tier: «free» (sello verde PICK GRATIS) o «vip» (dorado, PICK VIP)."""
    with accent(tier):
        return _render_coupon(pick, tier)


def _render_coupon(pick: dict, tier: str | None) -> bytes:
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
    logo = _logo_t(logo_w, "dark")
    lpad = logo.info["pad"]
    card_y = top + logo.height - 2 * lpad + 46
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
    im.alpha_composite(logo, ((W - logo.width) // 2, max(0, top - lpad)))

    # tarjeta con sombra
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((card_x, card_y + 14, card_x + card_w, card_y + card_h + 14), 34, fill=(0, 0, 0, 150))
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(22)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((card_x, card_y, card_x + card_w, card_y + card_h), 34, fill=(255, 255, 255),
                        outline=GOLD if tier == "vip" else None, width=6 if tier == "vip" else 0)
    if tier in ("free", "vip"):   # sello del canal sobre el borde de la tarjeta
        label = "PICK VIP · EXCLUSIVO" if tier == "vip" else "PICK GRATIS DEL DÍA"
        fpl = _font("Bold", 30)
        pw = d.textlength(label, font=fpl) + 64
        px0 = (W - pw) / 2
        d.rounded_rectangle((px0, card_y - 30, px0 + pw, card_y + 30), 30, fill=GOLD if tier == "vip" else BRAND)
        d.text((W / 2, card_y + 1), label, font=fpl, fill=(20, 16, 4) if tier == "vip" else (11, 26, 6), anchor="mm")

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

    lw = 330 if not compact else 260
    logo = _put_logo(im, lw, "dark", "center", 50)

    # titular
    y = 50 + logo.height - 2 * logo.info["pad"] + (40 if not compact else 10)
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


def fit_instagram(jpeg: bytes, story: bool = False) -> bytes:
    """Deja cualquier imagen lista para publicar sin deformarla ni cortarla.
    Feed: Instagram acepta de 4:5 a 1.91:1; dentro de ese rango solo se ajusta a 1080 de ancho.
    Fuera de ese rango (o para historias, 1080x1920) se encaja completa sobre un fondo hecho con
    la misma imagen, desenfocada y oscurecida."""
    from PIL import ImageEnhance
    im = Image.open(io.BytesIO(jpeg)).convert("RGB")
    tw, th = (1080, 1920) if story else (1080, 1350)
    ratio = im.width / im.height
    out = io.BytesIO()
    if (not story and 0.8 <= ratio <= 1.91) or (story and abs(ratio - tw / th) < 0.02):
        if im.width == tw:
            return jpeg
        im.resize((tw, round(tw / ratio)), Image.LANCZOS).save(out, "JPEG", quality=92, optimize=True)
        return out.getvalue()
    scale = max(tw / im.width, th / im.height)
    bg = im.resize((round(im.width * scale) + 2, round(im.height * scale) + 2), Image.LANCZOS)
    bg = bg.crop(((bg.width - tw) // 2, (bg.height - th) // 2, (bg.width - tw) // 2 + tw, (bg.height - th) // 2 + th))
    bg = ImageEnhance.Brightness(bg.filter(ImageFilter.GaussianBlur(40))).enhance(0.55).convert("RGBA")
    scale = min(tw / im.width, th / im.height)
    fg = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
    x, y = (tw - fg.width) // 2, (th - fg.height) // 2
    sh = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle((x, y + 10, x + fg.width, y + fg.height + 10), fill=(0, 0, 0, 120))
    bg.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))
    bg.paste(fg, (x, y))
    bg.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


# ---------------------------------------------------------------- piezas de contenido
LOGO_LIGHT = os.path.join(config.ROOT, "docs", "assets", "logo-full-light.png")
THEMES = {
    "dark": dict(text=(240, 240, 242), text2=(225, 225, 228), sub=(170, 172, 178), faint=(150, 150, 155),
                 tile=(22, 24, 26), tile_line=(52, 58, 52), eyebrow=(150, 230, 120), pos=(150, 255, 110),
                 neg=(255, 120, 110), bar2=(110, 116, 124), glow=(90, 255, 60, 50), btn=(124, 220, 90),
                 btn_text=(10, 14, 10), pickbox=(28, 52, 26), pickbox_neutral=(40, 42, 46), pick_text=(150, 255, 110)),
    "light": dict(text=(17, 19, 24), text2=(40, 44, 50), sub=(96, 102, 110), faint=(120, 124, 130),
                  tile=(255, 255, 255), tile_line=(220, 223, 216), eyebrow=(47, 122, 18), pos=(47, 122, 18),
                  neg=(194, 38, 26), bar2=(196, 200, 206), glow=(126, 217, 87, 70), btn=(62, 154, 28),
                  btn_text=(255, 255, 255), pickbox=(226, 244, 220), pickbox_neutral=(236, 237, 240),
                  pick_text=(30, 110, 30)),
}


def _bg(h: int, theme: str) -> Image.Image:
    if theme == "dark":
        return _background(h).convert("RGBA")
    base = Image.new("RGB", (W, h), (244, 244, 240))
    noise = Image.effect_noise((W // 6, h // 6), 30).resize((W, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(4))
    base = Image.composite(Image.new("RGB", (W, h), (236, 237, 232)), base, noise.point(lambda v: max(0, v - 110)))
    vg = Image.radial_gradient("L").resize((W, h)).point(lambda v: int(v * 0.35))
    return Image.composite(Image.new("RGB", (W, h), (222, 224, 218)), base, vg).convert("RGBA")


_LOGO_CACHE: dict = {}


def _logo_t(w: int, theme: str) -> Image.Image:
    """Logo reforzado: bordes nítidos, ojos verde neón con brillo y letras en blanco (o negro) puro.
    La imagen trae un margen para el brillo; su tamaño está en lg.info["pad"]."""
    key = (w, theme)
    if key in _LOGO_CACHE:
        return _LOGO_CACHE[key].copy()
    from PIL import ImageEnhance
    src = Image.open(LOGO if theme == "dark" else LOGO_LIGHT).convert("RGBA")
    s = 3
    big_w = w * s
    big = src.resize((big_w, round(src.height * big_w / src.width)), Image.LANCZOS)
    pad = round(w * 0.16) * s
    r, g, b, a = big.split()
    a = a.point(lambda v: max(0, min(255, (v - 70) * 255 // 110)))       # bordes nítidos
    green = ImageChops.multiply(
        ImageChops.subtract(g, ImageChops.lighter(r, b)).point(lambda v: 255 if v > 25 else 0), a)
    text = ImageChops.subtract(a, green)
    light = theme != "dark"
    vivid = ImageEnhance.Brightness(ImageEnhance.Color(big.convert("RGB")).enhance(2.6 if light else 2.0)).enhance(
        0.68 if light else 1.35)
    out = Image.new("RGBA", (big.width + 2 * pad, big.height + 2 * pad), (0, 0, 0, 0))
    for radius, alpha in (((22, 0.3), (9, 0.45)) if light else ((22, 0.55), (9, 0.85))):   # brillo neón
        glow = Image.new("L", out.size, 0)
        glow.paste(green, (pad, pad))
        glow = glow.filter(ImageFilter.GaussianBlur(radius * s * w / 300)).point(lambda v, k=alpha: round(min(255, v * 1.6) * k))
        tint = (70, 210, 30) if light else (110, 255, 60)
        out.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", out.size, tint).split(), glow)))
    ink = (255, 255, 255) if theme == "dark" else (12, 14, 16)
    layer = Image.new("RGBA", big.size, ink + (0,))
    layer.putalpha(text)
    out.alpha_composite(layer, (pad, pad))
    eyes = vivid.convert("RGBA")
    eyes.putalpha(green)
    out.alpha_composite(eyes, (pad, pad))
    small = out.resize((out.width // s, out.height // s), Image.LANCZOS)
    small.info["pad"] = pad // s
    _LOGO_CACHE[key] = small
    return small.copy()

def _logo(w: int) -> Image.Image:
    return _logo_t(w, "dark")


def _put_logo(im, w: int, theme: str, x, y) -> Image.Image:
    """Pega el logo con su brillo. x="center" lo centra. Devuelve el logo (alto útil: lg.height - 2*pad)."""
    lg = _logo_t(w, theme)
    p = lg.info.get("pad", 0)
    xx = (W - lg.width) // 2 if x == "center" else x - p
    im.alpha_composite(lg, (xx, max(0, y - p)))
    return lg


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


def render_weekly(week: dict, theme: str = "dark") -> bytes:
    """Resumen semanal 1080x1350. week = {label, picks:[{home,away,res,price,stake}], units, yield, hits, total}."""
    H = 1350
    T = THEMES[theme]
    im = _bg(H, theme)
    _glow(im, (W / 2 - 380, -80, W / 2 + 380, 380), T["glow"], 90)
    lg = _put_logo(im, 260, theme, "center", 46)
    d = ImageDraw.Draw(im)
    y = 46 + lg.height - 2 * lg.info["pad"] + 26
    _ctext(d, y, "RESUMEN SEMANAL", _font("Medium", 30), T["eyebrow"])
    _ctext(d, y + 44, week["label"], _font("Bold", 54), T["text"])
    # cifras
    y += 140
    units = week["units"]
    tiles = [("Puntos", f"{'+' if units >= 0 else ''}{units:.1f}".replace(".", ",")),
             ("Acierto", f"{week['hits']}/{week['total']}"),
             ("Yield", f"{'+' if week['yield'] >= 0 else ''}{week['yield'] * 100:.1f}%".replace(".", ","))]
    tw, gap = 286, 21
    for i, (lab, val) in enumerate(tiles):
        x = 90 + i * (tw + gap)
        d.rounded_rectangle((x, y, x + tw, y + 150), 26, fill=T["tile"], outline=T["tile_line"], width=2)
        fv = _font("Bold", 56)
        col = T["pos"] if (i != 1 and (units >= 0 if i == 0 else week["yield"] >= 0)) else T["text"]
        if i != 1 and (units < 0 if i == 0 else week["yield"] < 0):
            col = T["neg"]
        d.text((x + (tw - d.textlength(val, font=fv)) / 2, y + 24), val, font=fv, fill=col)
        fl = _font("Medium", 26)
        d.text((x + (tw - d.textlength(lab, font=fl)) / 2, y + 98), lab, font=fl, fill=T["sub"])
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
    _ctext(d, H - 150, "Historial completo en la web · link en la bio", _font("Medium", 30), T["text2"])
    _ctext(d, H - 96, "@stakevision · +18 · Juega con responsabilidad", _font("Regular", 24), T["faint"])
    return _jpeg(im)


def render_story(pick: dict, theme: str = "dark") -> bytes:
    """Historia vertical 1080x1920 del pick gratis del día."""
    H = 1920
    T = THEMES[theme]
    im = _bg(H, theme)
    _glow(im, (W / 2 - 420, 120, W / 2 + 420, 760), T["glow"], 110)
    lg = _put_logo(im, 420, theme, "center", 150)
    d = ImageDraw.Draw(im)
    legs = pick["legs"]
    block = 76 + 64 + (120 + 300 * len(legs) + 120) + 90 + 190
    y = max(150 + lg.height - 2 * lg.info["pad"] + 60, (H - 140 - block) // 2 + 200)
    d.rounded_rectangle((W / 2 - 230, y, W / 2 + 230, y + 76), 38, fill=T["btn"])
    _ctext(d, y + 14, "PICK GRATIS DE HOY", _font("Bold", 36), T["btn_text"])
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
    _ctext(d, cy, "Análisis completo en Telegram", _font("Bold", 46), T["text"])
    d.rounded_rectangle((W / 2 - 290, cy + 90, W / 2 + 290, cy + 190), 50, fill=T["btn"])
    _ctext(d, cy + 112, "t.me/stakevision", _font("Bold", 48), T["btn_text"])
    _ctext(d, H - 130, "+18 · Juega con responsabilidad", _font("Regular", 30), T["faint"])
    return _jpeg(im)


def render_postmatch(m: dict, theme: str = "dark") -> bytes:
    """Noticia post partido 1080x1350 con datos reales: marcador, goles, estadísticas y el dato curioso."""
    H = 1350
    T = THEMES[theme]
    im = _bg(H, theme)
    _glow(im, (W / 2 - 420, 120, W / 2 + 420, 520), T["glow"], 100)
    lg = _put_logo(im, 220, theme, "center", 40)
    d = ImageDraw.Draw(im)
    y = 40 + lg.height - 2 * lg.info["pad"] + 22
    _ctext(d, y, ("FINAL · " + m["league"]).upper(), _font("Medium", 26), T["eyebrow"])
    y += 56
    # marcador
    fs = _font("Bold", 124)
    sc = f"{m['hg']}  -  {m['ag']}"
    _ctext(d, y, sc, fs, T["text"])
    fh = _font("Bold", 40)
    home, f1 = _fit(d, m["home"], "Bold", 40, 300)
    away, f2 = _fit(d, m["away"], "Bold", 40, 300)
    d.text((90, y + 52), home, font=f1, fill=T["text"])
    d.text((W - 90 - d.textlength(away, font=f2), y + 52), away, font=f2, fill=T["text"])
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
    d.text((90, y), "GOLES", font=_font("Medium", 26), fill=T["eyebrow"])
    y += 44
    for g in m["goals"][:5]:
        d.text((90, y), g["min"], font=_font("Bold", 30), fill=T["pos"])
        t, fg = _fit(d, f"{g['player']} ({g['team']})", "Medium", 30, W - 300)
        d.text((200, y), t, font=fg, fill=T["text"])
        y += 46
    y += 14
    # estadísticas: barras enfrentadas
    d.text((90, y), "ESTADÍSTICAS", font=_font("Medium", 26), fill=T["eyebrow"])
    y += 48
    for lab, a, b, fmt in m["stats"][:3]:
        tot = (a + b) or 1
        d.text((90, y), fmt(a), font=_font("Bold", 32), fill=T["text"])
        bt = fmt(b)
        d.text((W - 90 - d.textlength(bt, font=_font("Bold", 32)), y), bt, font=_font("Bold", 32), fill=T["text"])
        _ctext(d, y + 4, lab, _font("Medium", 26), T["sub"])
        bx0, bx1, by = 90, W - 90, y + 48
        split = bx0 + (bx1 - bx0) * a / tot
        d.rounded_rectangle((bx0, by, split - 3, by + 12), 6, fill=T["btn"])
        d.rounded_rectangle((split + 3, by, bx1, by + 12), 6, fill=T["bar2"])
        y += 74
    # nuestro pick
    if m.get("pick"):
        p = m["pick"]
        y = H - 190
        ok = p["res"] == "W"
        d.rounded_rectangle((90, y, W - 90, y + 96), 26, fill=T["pickbox"] if ok else T["pickbox_neutral"])
        if ok:
            im.alpha_composite(_check_badge(52), (120, int(y + 22)))
        d = ImageDraw.Draw(im)
        txt, fp = _fit(d, f"Nuestro pick: {p['label']} @ {p['price']:.2f}", "Bold", 34, W - 320)
        d.text((190, y + 26), txt, font=fp, fill=T["pos"] if ok else T["text2"])
    _ctext(d, H - 70, "@stakevision · +18 · Juega con responsabilidad", _font("Regular", 24), T["faint"])
    return _jpeg(im)


# ---------------------------------------------------------------- post partido (formato revista)
BRAND = (126, 217, 87)
_DARK = (5, 6, 5)


def _bebas(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(os.path.join(FONTS, "BebasNeue-Regular.ttf"), size)


def _oswald(size: int, weight: int = 600) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(os.path.join(FONTS, "Oswald-Variable.ttf"), size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:  # noqa: BLE001
        pass
    return f


def _lum(c) -> float:
    r, g, b = (x / 255 for x in c[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _mix(c, other, t: float) -> tuple:
    return tuple(round(a + (b - a) * t) for a, b in zip(c[:3], other[:3]))


def team_palette(team: dict) -> tuple[tuple, tuple]:
    """(relleno del escudo, acento). El relleno es el color más oscuro del club; el acento, el más claro."""
    a, b = tuple(team.get("color") or (40, 44, 50)), tuple(team.get("alt") or (240, 240, 240))
    fill, accent = (a, b) if _lum(a) <= _lum(b) else (b, a)
    if _lum(accent) < 0.35:
        accent = _mix(accent, (255, 255, 255), 0.55)
    if abs(_lum(accent) - _lum(fill)) < 0.25:
        fill = _mix(fill, (0, 0, 0), 0.6)
    return fill, accent


def _spaced(d, xy, text, font, fill, spacing=0.0, anchor="ls"):
    """Texto con espaciado entre letras (Pillow no lo trae)."""
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill, anchor=anchor)
        x += d.textlength(ch, font=font) + spacing
    return x


def _spaced_len(d, text, font, spacing=0.0) -> float:
    return sum(d.textlength(ch, font=font) for ch in text) + spacing * max(len(text) - 1, 0)


def _bez(p0, p1, p2, p3, n=24):
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return out


def _shield_poly(inset: float, k: float) -> list:
    """Silueta de escudo genérica (viewBox 200x236), escalada por k."""
    i = inset
    top, side = 6 + i, 12 + i
    pts = [(100, top), (188 - i, 30 + i * 0.7), (188 - i, 110)]
    pts += _bez((188 - i, 110), (188 - i, 168 - i * 0.6), (150 - i * 0.6, 206 - i), (100, 230 - i))
    pts += _bez((100, 230 - i), (50 + i * 0.6, 206 - i), (side, 168 - i * 0.6), (side, 110))
    pts += [(side, 30 + i * 0.7)]
    return [(x * k, y * k) for x, y in pts]


def _vgrad(size, c0, c1) -> Image.Image:
    w, h = size
    g = Image.new("RGB", (1, h))
    for y in range(h):
        g.putpixel((0, y), _mix(c0, c1, y / max(h - 1, 1)))
    return g.resize((w, h))


def shield(team: dict, width: int) -> Image.Image:
    """Escudo propio del equipo: forma clásica, colores del club, iniciales y borde metálico.
    No reproduce el escudo oficial."""
    fill, accent = team_palette(team)
    s = 4
    k = width * s / 200
    W2, H2 = round(200 * k), round(236 * k)
    out = Image.new("RGBA", (W2, H2 + round(14 * k)), (0, 0, 0, 0))
    outer = Image.new("L", out.size, 0)
    ImageDraw.Draw(outer).polygon(_shield_poly(0, k), fill=255)
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    sh.paste((0, 0, 0, 150), (0, round(8 * k)), outer.crop((0, 0, out.width, out.height - round(8 * k))))
    out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6 * k)))
    rim = Image.new("RGB", out.size)
    rim.paste(_vgrad(out.size, _mix(accent, (255, 255, 255), 0.55), _mix(accent, (0, 0, 0), 0.45)))
    out.paste(rim, (0, 0), outer)
    inner = Image.new("L", out.size, 0)
    ImageDraw.Draw(inner).polygon(_shield_poly(14, k), fill=255)
    out.paste(_vgrad(out.size, _mix(fill, (255, 255, 255), 0.18), _mix(fill, (0, 0, 0), 0.35)), (0, 0), inner)
    gloss = Image.new("L", out.size, 0)
    ImageDraw.Draw(gloss).ellipse((-60 * k, -150 * k, 260 * k, 92 * k), fill=60)
    out.paste((255, 255, 255), (0, 0), ImageChops.multiply(gloss, inner))
    d = ImageDraw.Draw(out)
    abbr = (team.get("abbr") or team.get("short", "")[:3]).upper()[:4]
    size = round((78 if len(abbr) <= 3 else 62) * k)
    f = _bebas(size)
    tw = d.textlength(abbr, font=f)
    d.text(((W2 - tw) / 2, 146 * k), abbr, font=f, fill=accent, anchor="ls",
           stroke_width=round(1.2 * k), stroke_fill=_mix(fill, (0, 0, 0), 0.5))
    return out.resize((out.width // s, out.height // s), Image.LANCZOS)


def _best_offset(energy: list, window: int, weights) -> int:
    """Desplazamiento de la ventana que deja más 'detalle' (bordes) en las zonas que pesan más."""
    n = len(energy)
    if window >= n:
        return 0
    best, best_i = -1.0, 0
    for i in range(0, n - window + 1):
        sc = sum(energy[i + k] * weights(k / window) for k in range(window))
        if sc > best:
            best, best_i = sc, i
    return best_i


def _cover(photo: bytes, size, focus=None, side: str = "right") -> Image.Image:
    """Llena el tamaño sin deformar. Sin focus, elige el recorte solo: deja al protagonista (la zona con
    más detalle) en la mitad derecha, que es la que no tapa el texto, y prioriza la parte de arriba (caras)."""
    im = Image.open(io.BytesIO(photo)).convert("RGB")
    w, h = size
    scale = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    if focus:
        x = round((im.width - w) * focus[0])
        y = round((im.height - h) * focus[1])
        return im.crop((x, y, x + w, y + h))
    k = 8   # análisis en una versión chica
    small = im.convert("L").resize((max(1, im.width // k), max(1, im.height // k))).filter(ImageFilter.FIND_EDGES)
    px = small.load()
    x = y = 0
    if im.width > w:
        cols = [sum(px[i, j] for j in range(small.height)) for i in range(small.width)]
        wts = (lambda t: 0.35 if t < 0.38 else 1.0) if side == "right" else (lambda t: 1.0 - abs(t - 0.5))
        x = _best_offset(cols, w // k, wts) * k
    if im.height > h:
        rows = [sum(px[i, j] for i in range(small.width)) for j in range(small.height)]
        y = _best_offset(rows, h // k, lambda t: 1.0 if t < 0.55 else 0.55) * k
        y = min(y, round((im.height - h) * 0.35))   # nunca bajar demasiado: las cabezas van arriba
    x, y = min(x, im.width - w), min(y, im.height - h)
    return im.crop((x, y, x + w, y + h))


def _alpha_ramp(size, stops, horizontal: bool) -> Image.Image:
    """Máscara L con rampas lineales entre (posición 0..1, opacidad 0..255)."""
    w, h = size
    n = w if horizontal else h
    line = Image.new("L", (n, 1))
    for i in range(n):
        t = i / max(n - 1, 1)
        for (p0, a0), (p1, a1) in zip(stops, stops[1:]):
            if p0 <= t <= p1:
                line.putpixel((i, 0), round(a0 + (a1 - a0) * (t - p0) / max(p1 - p0, 1e-6)))
                break
        else:
            line.putpixel((i, 0), stops[-1][1] if t > stops[-1][0] else stops[0][1])
    return line.resize((w, h)) if horizontal else line.transpose(Image.ROTATE_270).resize((w, h))


def split_headline(text: str) -> tuple[str, str]:
    """Parte el titular en dos líneas (la segunda va en contorno verde).
    Respeta un guion o un espacio puesto a mano; si no, corta una palabra larga por sílaba."""
    t = " ".join(text.upper().split())
    if "-" in t:
        a, b = t.split("-", 1)
        return a.strip() + "-", b.strip()
    words = t.split(" ")
    if len(words) > 1:
        best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
        return " ".join(words[:best]), " ".join(words[best:])
    if len(t) <= 6:
        return t, ""
    vow = set("AEIOUÁÉÍÓÚ")
    keep = {"BL", "BR", "CL", "CR", "DR", "FL", "FR", "GL", "GR", "PL", "PR", "TR", "CH", "LL", "RR"}
    cuts = []
    for i in range(2, len(t) - 1):
        a, b, c = t[i - 1], t[i], t[i + 1] if i + 1 < len(t) else ""
        if b not in vow and c in vow and a in vow:
            cuts.append(i)
        elif a not in vow and b not in vow and c in vow and (a + b) not in keep:
            cuts.append(i)
        elif a in "AEO" and b in "AEO":
            cuts.append(i)
    if not cuts:
        return t, ""
    i = min(cuts, key=lambda c: (abs(c - len(t) / 2), -c))
    return t[:i] + "-", t[i:]


def _clusters(goals: list, gap: int = 10) -> list[list]:
    out = []
    for g in goals:
        if out and g["min"] - out[-1][-1]["min"] < gap:
            out[-1].append(g)
        else:
            out.append([g])
    return out


GOLD, L_GOLD = (236, 188, 66), (170, 124, 16)


class accent:
    """Colores por canal: «vip» cambia el verde de la marca por dorado mientras se dibuja la imagen."""

    def __init__(self, tier: str | None):
        self.tier = tier

    def __enter__(self):
        global BRAND, L_GREEN, GREEN
        self._old = (BRAND, L_GREEN, GREEN)
        if self.tier == "vip":
            BRAND, L_GREEN, GREEN = GOLD, L_GOLD, L_GOLD
        return self

    def __exit__(self, *exc):
        global BRAND, L_GREEN, GREEN
        BRAND, L_GREEN, GREEN = self._old
        return False


def _mag(theme: str) -> dict:
    """Colores del formato revista en modo noche (dark) o día (light)."""
    if theme == "light":
        return {"bg": L_BG, "fg": L_TEXT, "sub": (70, 76, 70), "muted": L_GREY, "tick": (150, 156, 148),
                "brand": L_GREEN, "card": (255, 255, 255, 240), "card_line": (222, 226, 218, 255), "shadow": True,
                "track": (222, 226, 218), "dot_in": (255, 255, 255), "ht": (17, 19, 24, 60),
                "credit": (17, 19, 24, 170)}
    return {"bg": _DARK, "fg": (241, 243, 239), "sub": (201, 206, 198), "muted": (154, 160, 149),
            "tick": (110, 117, 106), "brand": BRAND, "card": (18, 22, 18, 205), "card_line": BRAND + (64,),
            "shadow": False, "track": (42, 51, 42), "dot_in": _DARK, "ht": (255, 255, 255, 90),
            "credit": (255, 255, 255, 160)}


def _mag_card(im, box, T, r=24):
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    if T["shadow"]:
        x0, y0, x1, y1 = box
        ImageDraw.Draw(layer).rounded_rectangle((x0, y0 + 16, x1, y1 + 16), r, fill=(17, 19, 24, 45))
        layer = layer.filter(ImageFilter.GaussianBlur(22))
    ImageDraw.Draw(layer).rounded_rectangle(box, r, fill=T["card"], outline=T["card_line"], width=1 if not T["shadow"] else 2)
    im.alpha_composite(layer)


def _accents(home: dict, away: dict, theme: str) -> tuple:
    """Color de cada equipo para marcador y línea de tiempo, legible sobre el fondo del tema."""
    out = []
    for t in (home, away):
        fill, acc = team_palette(t)
        if theme == "light" and _lum(acc) > 0.62:
            acc = fill if _lum(fill) < 0.55 else _mix(acc, (0, 0, 0), 0.5)
        out.append(tuple(acc))
    h, a = out
    if sum(abs(x - y) for x, y in zip(h, a)) < 120:   # acentos casi iguales: separarlos
        a = (L_TEXT if theme == "light" else (241, 243, 239)) if _lum(h) < 0.8 or theme == "light" else BRAND
        if theme == "light" and _lum(h) < 0.2:
            a = L_GREEN
    return h, a


def _result_line(d, T, m: dict, y: int, x_center: float = W / 2) -> None:
    """Línea de cierre: el resultado de nuestro pick (✓ VERDE / ✕ ROJA / ↺ NULA) o «El dato»."""
    pk = m.get("pick")
    fb_, fr_ = _font("Bold", 22), _font("Medium", 22)
    if pk:
        tag = {"W": ("✓ VERDE", BRAND, (11, 26, 6)), "L": ("✕ ROJA", (227, 38, 46), (255, 255, 255)),
               "V": ("↺ NULA", (110, 116, 124), (255, 255, 255))}[pk["result"]]
        lead, body = "Nuestro pick:", f" {pk['label']} · {pk['odds']}  "
        ftag = _font("Bold", 21)
        tag_txt = tag[0].split(" ", 1)[1]
        total = d.textlength(lead, font=fb_) + d.textlength(body, font=fr_) + d.textlength(tag_txt, font=ftag) + 58
        x = x_center - total / 2
        d.text((x, y), lead, font=fb_, fill=T["brand"], anchor="ls")
        x += d.textlength(lead, font=fb_)
        d.text((x, y), body, font=fr_, fill=T["sub"], anchor="ls")
        x += d.textlength(body, font=fr_)
        tw = d.textlength(tag_txt, font=ftag) + 58
        d.rounded_rectangle((x, y - 26, x + tw, y + 10), 18, fill=tag[1])
        cx, cy = x + 22, y - 8
        if pk["result"] == "W":
            d.line((cx - 7, cy, cx - 2, cy + 6, cx + 8, cy - 6), fill=tag[2], width=4, joint="curve")
        elif pk["result"] == "L":
            d.line((cx - 6, cy - 6, cx + 6, cy + 6), fill=tag[2], width=4)
            d.line((cx - 6, cy + 6, cx + 6, cy - 6), fill=tag[2], width=4)
        else:
            d.arc((cx - 8, cy - 8, cx + 8, cy + 8), 40, 330, fill=tag[2], width=4)
        d.text((x + 40, y), tag_txt, font=ftag, fill=tag[2], anchor="ls")
    elif m.get("dato"):
        lead, body = "El dato:", " " + m["dato"]
        total = d.textlength(lead, font=fb_) + d.textlength(body, font=fr_)
        x = x_center - total / 2
        d.text((x, y), lead, font=fb_, fill=T["brand"], anchor="ls")
        d.text((x + d.textlength(lead, font=fb_), y), body, font=fr_, fill=T["sub"], anchor="ls")


def render_recap(m: dict, theme: str = "dark") -> bytes:
    """Post partido estilo revista: foto a color del protagonista, titular gigante, marcador con
    escudos propios, línea de tiempo de los goles y el resultado de nuestro pick.

    m = {"report": espn.report_from_event(...), "eyebrow": str, "headline": str, "subline": (normal, bold),
         "pick": {"label": str, "odds": str, "result": "W"|"L"|"V"} | None, "dato": str | None,
         "photo": bytes | None, "credit": str | None}
    """
    H = 1350
    rep = m["report"]
    home, away = rep["home"], rep["away"]
    T = _mag(theme)
    hacc, aacc = _accents(home, away, theme)
    im = Image.new("RGBA", (W, H), T["bg"] + (255,))
    if m.get("photo"):
        ph = _cover(m["photo"], (W, H))
        ph = _enhance(ph)
        im.paste(ph, (0, 0))
    else:
        im = _bg(H, theme)
        win = aacc if away["score"] > home["score"] else hacc
        lose = hacc if win is aacc else aacc
        _glow(im, (500, 80, 1300, 900), tuple(win) + (80,), 160)
        _glow(im, (-300, 300, 500, 1000), tuple(lose) + (35,), 160)
    dark = Image.new("RGBA", (W, H), T["bg"] + (255,))
    im = Image.composite(dark, im, _alpha_ramp((W, H), [(0, 255), (0.30, 217), (0.62, 0), (1, 0)], True))
    im = Image.composite(dark, im, _alpha_ramp((W, H), [(0, 0), (0.45, 0), (0.72, 255), (1, 255)], False))
    d = ImageDraw.Draw(im)

    _put_logo(im, 165, theme, 56, 40)
    _spaced(d, (60, 248), m.get("eyebrow", "").upper(), _oswald(28), T["brand"], spacing=28 * 0.14)

    l1, l2 = split_headline(m.get("headline") or "")
    size = 210
    while size > 120 and max(d.textlength(l1, font=_bebas(size)), d.textlength(l2, font=_bebas(size))) > 640:
        size -= 6
    fb = _bebas(size)
    b1 = 262 + round(0.714 * size)
    d.text((52, b1), l1, font=fb, fill=T["fg"], anchor="ls")
    if l2:
        b2 = b1 + round(0.84 * size)
        outer = Image.new("L", (W, H), 0)
        inner = Image.new("L", (W, H), 0)
        ImageDraw.Draw(outer).text((52, b2), l2, font=fb, fill=255, anchor="ls", stroke_width=3, stroke_fill=255)
        ImageDraw.Draw(inner).text((52, b2), l2, font=fb, fill=255, anchor="ls")
        im.paste(T["brand"] + (255,), (0, 0), ImageChops.subtract(outer, inner))

    # marcador
    y0 = 668
    sh_h = shield(home, 96)
    sh_a = shield(away, 96)
    im.alpha_composite(sh_h, (60, y0))
    x = 60 + 96 + 30
    fs = _bebas(150)
    hs, as_ = str(home["score"]), str(away["score"])
    winner = "home" if home["score"] > away["score"] else "away" if away["score"] > home["score"] else ""
    base = y0 + 106
    d.text((x, base), hs, font=fs, fill=hacc if winner == "home" else T["fg"], anchor="ls")
    x += d.textlength(hs, font=fs) + 34
    d.rectangle((x, base - 64, x + 44, base - 54), fill=T["brand"])
    x += 44 + 34
    d.text((x, base), as_, font=fs, fill=aacc if winner == "away" else T["fg"], anchor="ls")
    x += d.textlength(as_, font=fs) + 30
    im.alpha_composite(sh_a, (round(x), y0))
    sub_n, sub_b = m.get("subline") or ("", "")
    fsub, fsubb = _oswald(28, 500), _oswald(28, 600)
    xx = _spaced(d, (62, 836), sub_n, fsub, T["sub"], spacing=1.6)
    _spaced(d, (xx + 6, 836), sub_b, fsubb, T["fg"], spacing=1.6)

    # línea de tiempo
    _mag_card(im, (40, 880, 1040, 1180), T)
    d = ImageDraw.Draw(im)
    end = max(90, max([g["min"] for g in rep["goals"]] + [0]))
    end = 120 if end > 100 else end
    _spaced(d, (70, 930), f"EL PARTIDO EN {end}'", _oswald(22), T["muted"], spacing=22 * 0.16)
    fl = _oswald(19, 400)
    lx = 1010
    for team, col in ((away, aacc), (home, hacc)):
        name = (team.get("short") or team.get("name") or "").strip()
        tw = d.textlength(name, font=fl)
        d.text((lx - tw, 930), name, font=fl, fill=T["sub"], anchor="ls")
        d.ellipse((lx - tw - 20, 917, lx - tw - 8, 929), fill=col)
        lx = lx - tw - 40
    L, R, ly = 110, 930, 1050
    track = _vgrad((6, R - L), T["brand"], T["track"]).rotate(-90, expand=True)
    mask = Image.new("L", track.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, track.width - 1, track.height - 1), 3, fill=255)
    im.paste(track, (L, ly - 3), mask)
    d = ImageDraw.Draw(im)
    hx = L + (R - L) * 45 / end
    d.line((hx, ly - 20, hx, ly + 26), fill=T["ht"], width=2)
    ft = _oswald(18, 400)
    for t in range(0, end + 1, 15):
        tx = L + (R - L) * t / end
        lab = f"{t}'"
        d.text((tx - d.textlength(lab, font=ft) / 2, ly + 34), lab, font=ft, fill=T["tick"], anchor="ls")
    fmin, fname = _bebas(40), _oswald(19)

    def label_x(cx, wdt):
        return min(max(cx - wdt / 2, 60), 1020 - wdt)

    for side, col, up in (("home", hacc, True), ("away", aacc, False)):
        goals = [g for g in rep["goals"] if g["side"] == side]
        for cl in _clusters(goals):
            xs = [L + (R - L) * min(g["min"], end) / end for g in cl]
            for gx in xs:
                d.ellipse((gx - 13, ly - 13, gx + 13, ly + 13), fill=col)
                d.ellipse((gx - 9, ly - 9, gx + 9, ly + 9), fill=T["dot_in"])
                d.ellipse((gx - 6, ly - 6, gx + 6, ly + 6), fill=col)
            mins = " · ".join(g["label"] for g in cl)
            players = []
            for g in cl:
                nm = (g["player"].split(". ", 1)[-1] if ". " in g["player"] else g["player"]).upper()
                nm += " (P)" if g["kind"] == "penalty" else " (EC)" if g["kind"] == "own" else ""
                if players and players[-1][0] == nm:
                    players[-1][1] += 1
                else:
                    players.append([nm, 1])
            who = " · ".join(n + (f" x{c}" if c > 1 else "") for n, c in players)
            cx = sum(xs) / len(xs)
            wm, wn = d.textlength(mins, font=fmin), _spaced_len(d, who, fname, 0.8)
            if up:
                d.text((label_x(cx, wm), ly - 64), mins, font=fmin, fill=col, anchor="ls")
                _spaced(d, (label_x(cx, wn), ly - 26), who, fname, col, 0.8)
            else:
                d.text((label_x(cx, wm), ly + 84), mins, font=fmin, fill=col, anchor="ls")
                _spaced(d, (label_x(cx, wn), ly + 116), who, fname, col, 0.8)
    if not rep["goals"]:
        msg = "Sin goles: el cero no se movió en todo el partido"
        _ctext(d, ly - 52, msg, _oswald(24, 500), T["sub"])

    _result_line(d, T, m, 1238)
    _ctext(d, 1306, "+18 · Juega con responsabilidad", _font("Medium", 17), T["muted"])

    if m.get("credit"):
        fc = _font("Regular", 14)
        tw = round(d.textlength(m["credit"], font=fc)) + 8
        tmp = Image.new("RGBA", (tw, 22), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((0, 2), m["credit"], font=fc, fill=T["credit"])
        im.alpha_composite(tmp.rotate(-90, expand=True), (1040, 180))
    return _jpeg(im)


def _enhance(ph: Image.Image) -> Image.Image:
    from PIL import ImageEnhance
    return ImageEnhance.Color(ImageEnhance.Contrast(ph).enhance(1.08)).enhance(1.1)


# ---------------------------------------------------------------- adelanto (historia, modo día)
L_BG, L_TEXT, L_GREEN, L_BTN, L_GREY = (244, 244, 240), (17, 19, 24), (47, 122, 18), (62, 154, 28), (122, 128, 121)


def _rich(d, x, y, parts, fonts, colors):
    """Texto en una línea con tramos normal/negrita."""
    for txt, f, c in zip(parts, fonts, colors):
        if txt:
            d.text((x, y), txt, font=f, fill=c, anchor="ls")
            x += d.textlength(txt, font=f)
    return x


def _lock_icon(d, x, y, h, color):
    w = h * 0.75
    d.rounded_rectangle((x, y + h * 0.42, x + w, y + h), round(h * 0.12), fill=color)
    d.arc((x + w * 0.18, y, x + w * 0.82, y + h * 0.75), 180, 360, fill=color, width=max(3, round(h * 0.12)))
    d.line((x + w * 0.18, y + h * 0.37, x + w * 0.18, y + h * 0.48), fill=color, width=max(3, round(h * 0.12)))
    d.line((x + w * 0.82, y + h * 0.37, x + w * 0.82, y + h * 0.48), fill=color, width=max(3, round(h * 0.12)))


def render_teaser(m: dict) -> bytes:
    """Historia 1080x1920 en modo día: pistas del pick y el pick tapado hasta la hora de revelación.
    m = {"pill", "line1", "line2", "clues": [(normal, negrita, normal)], "lock", "cta": (l1, l2)}"""
    H = 1920
    im = Image.new("RGBA", (W, H), L_BG + (255,))
    _glow(im, (190, 40, 890, 900), (150, 230, 110, 120), 140)
    g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(g)
    for x in range(0, W, 90):
        gd.line((x, 0, x, H), fill=(17, 19, 24, 7), width=2)
    for y in range(0, H, 90):
        gd.line((0, y, W, y), fill=(17, 19, 24, 7), width=2)
    im.alpha_composite(g)
    _put_logo(im, 300, "light", "center", 80)
    d = ImageDraw.Draw(im)
    fp = _oswald(30)
    pw = _spaced_len(d, m["pill"], fp, 4.2) + 68
    d.rounded_rectangle(((W - pw) / 2, 300, (W + pw) / 2, 368), 34, fill=L_BTN)
    _spaced(d, ((W - pw) / 2 + 34, 347), m["pill"], fp, (255, 255, 255), 4.2)

    size = 240
    while size > 140 and max(d.textlength(m["line1"], font=_bebas(size)), d.textlength(m["line2"], font=_bebas(size))) > 960:
        size -= 6
    fb = _bebas(size)
    b1 = 420 + round(0.714 * size) + 30
    d.text(((W - d.textlength(m["line1"], font=fb)) / 2, b1), m["line1"], font=fb, fill=L_TEXT, anchor="ls")
    b2 = b1 + round(0.84 * size)
    x2 = (W - d.textlength(m["line2"], font=fb)) / 2
    outer, inner = Image.new("L", (W, H), 0), Image.new("L", (W, H), 0)
    ImageDraw.Draw(outer).text((x2, b2), m["line2"], font=fb, fill=255, anchor="ls", stroke_width=4, stroke_fill=255)
    ImageDraw.Draw(inner).text((x2, b2), m["line2"], font=fb, fill=255, anchor="ls")
    im.paste(L_GREEN + (255,), (0, 0), ImageChops.subtract(outer, inner))

    # tarjeta de pistas
    x0, y0, x1, y1 = 70, 880, 1010, 1545
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + 24, x1, y1 + 24), 34, fill=(17, 19, 24, 50))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(28)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((x0, y0, x1, y1), 34, fill=(255, 255, 255))
    _spaced(d, (118, 950), "LAS PISTAS", _oswald(26), L_GREY, 4.7)
    fr, fbold, fnum = _font("Medium", 33), _font("Bold", 33), _bebas(40)
    y = 1000
    for i, clue in enumerate(m["clues"][:4]):
        d.ellipse((118, y, 176, y + 58), fill=(226, 244, 220))
        n = str(i + 1)
        d.text((147 - d.textlength(n, font=fnum) / 2, y + 45), n, font=fnum, fill=L_GREEN, anchor="ls")
        parts = list(clue)
        while sum(d.textlength(t, font=f) for t, f in zip(parts, (fr, fbold, fr))) > 760 and len(parts[0]) > 4:
            parts[0] = parts[0][:-2].rstrip() + " "
        _rich(d, 202, y + 41, parts, (fr, fbold, fr), (L_TEXT, L_TEXT, L_TEXT))
        y += 96
        if i < 3:
            d.line((118, y - 16, 962, y - 16), fill=(238, 240, 234), width=2)
    # el pick, tapado
    d.rounded_rectangle((118, 1383, 962, 1507), 22, fill=L_TEXT)
    _spaced(d, (150, 1438), "EL PICK", _oswald(24), (154, 160, 149), 3.8)
    bx = 150
    for wbar in (180, 110, 150):
        d.rounded_rectangle((bx, 1455, bx + wbar, 1481), 6, fill=(42, 47, 42))
        bx += wbar + 12
    fl = _bebas(48)
    lw = d.textlength(m["lock"], font=fl) + 92
    d.rounded_rectangle((930 - lw, 1411, 930, 1479), 16, fill=BRAND)
    _lock_icon(d, 930 - lw + 26, 1428, 32, (11, 26, 6))
    d.text((930 - lw + 70, 1466), m["lock"], font=fl, fill=(11, 26, 6), anchor="ls")

    # llamado
    fc = _font("Bold", 32)
    _ctext(d, 1585, m["cta"][0], fc, L_TEXT)
    _ctext(d, 1627, m["cta"][1], fc, L_TEXT)
    fbt = _font("Bold", 46)
    t = "t.me/stakevision"
    bw = d.textlength(t, font=fbt) + 140
    d.rounded_rectangle(((W - bw) / 2, 1690, (W + bw) / 2, 1798), 54, fill=L_BTN)
    d.text(((W - d.textlength(t, font=fbt)) / 2, 1762), t, font=fbt, fill=(255, 255, 255), anchor="ls")
    _ctext(d, 1810, "+18 · Juega con responsabilidad", _font("Medium", 22), L_GREY)
    return _jpeg(im)


# ---------------------------------------------------------------- pick con foto (estilo revista)
def _wrap_fit(d, text, font_name, size, max_w, min_size=18):
    while size > min_size and d.textlength(text, font=_font(font_name, size)) > max_w:
        size -= 1
    f = _font(font_name, size)
    if d.textlength(text, font=f) > max_w:
        while d.textlength(text + "…", font=f) > max_w and len(text) > 8:
            text = text[:-1]
        text = text.rstrip(" ,.;") + "…"
    return text, f


def render_pick_photo(m: dict, theme: str = "dark") -> bytes:
    """Pick antes del partido con foto real del equipo/jugador (formato revista, oscuro).
    m = {"eyebrow", "headline", "teams": {"home", "away"}, "selection", "odds", "stake", "lines", "photo", "credit"}"""
    H = 1350
    home, away = m["teams"]["home"], m["teams"]["away"]
    T = _mag(theme)
    hacc, aacc = _accents(home, away, theme)
    if m.get("photo"):
        im = Image.new("RGBA", (W, H), T["bg"] + (255,))
        im.paste(_enhance(_cover(m["photo"], (W, H))), (0, 0))
    else:
        im = _bg(H, theme)
        _glow(im, (500, 80, 1300, 900), tuple(hacc) + (70,), 160)
        _glow(im, (-300, 300, 500, 1000), tuple(aacc) + (40,), 160)
    dark = Image.new("RGBA", (W, H), T["bg"] + (255,))
    im = Image.composite(dark, im, _alpha_ramp((W, H), [(0, 255), (0.30, 217), (0.62, 0), (1, 0)], True))
    im = Image.composite(dark, im, _alpha_ramp((W, H), [(0, 0), (0.45, 0), (0.72, 255), (1, 255)], False))
    d = ImageDraw.Draw(im)
    _put_logo(im, 165, theme, 56, 40)
    _spaced(d, (60, 248), m["eyebrow"].upper(), _oswald(28), T["brand"], spacing=3.9)
    l1, l2 = split_headline(m["headline"])
    size = 210
    while size > 120 and max(d.textlength(l1, font=_bebas(size)), d.textlength(l2, font=_bebas(size))) > 640:
        size -= 6
    fb = _bebas(size)
    b1 = 262 + round(0.714 * size)
    d.text((52, b1), l1, font=fb, fill=T["fg"], anchor="ls")
    if l2:
        b2 = b1 + round(0.84 * size)
        outer, inner = Image.new("L", (W, H), 0), Image.new("L", (W, H), 0)
        ImageDraw.Draw(outer).text((52, b2), l2, font=fb, fill=255, anchor="ls", stroke_width=3, stroke_fill=255)
        ImageDraw.Draw(inner).text((52, b2), l2, font=fb, fill=255, anchor="ls")
        im.paste(T["brand"] + (255,), (0, 0), ImageChops.subtract(outer, inner))
    # cruce
    y0 = 668
    im.alpha_composite(shield(home, 96), (60, y0))
    fv = _bebas(110)
    d.text((60 + 96 + 34, y0 + 100), "VS", font=fv, fill=T["brand"], anchor="ls")
    im.alpha_composite(shield(away, 96), (round(60 + 96 + 68 + d.textlength("VS", font=fv)), y0))
    names = f"{(home.get('short') or home.get('name') or '').strip()} vs {(away.get('short') or away.get('name') or '').strip()}"
    names, fn = _wrap_fit(d, names, "Medium", 28, 600)
    d.text((62, 836), names, font=fn, fill=T["sub"], anchor="ls")
    # tarjeta del pick
    _mag_card(im, (40, 880, 1040, 1200), T)
    d = ImageDraw.Draw(im)
    _spaced(d, (70, 930), "EL PICK", _oswald(22), T["muted"], 3.5)
    fo = _bebas(64)
    ow = d.textlength(m["odds"], font=fo) + 56
    d.rounded_rectangle((1010 - ow, 905, 1010, 985), 18, fill=BRAND)
    d.text((1010 - ow + 28, 970), m["odds"], font=fo, fill=(11, 26, 6), anchor="ls")
    if m.get("stake"):
        st = f"STAKE {m['stake']}/10"
        fs = _oswald(20)
        _spaced(d, (1010 - _spaced_len(d, st, fs, 2), 1012), st, fs, T["muted"], 2)
    sel = m["selection"].upper()
    size = 76
    while size > 40 and d.textlength(sel, font=_bebas(size)) > 1010 - ow - 100:
        size -= 2
    d.text((70, 1004), sel, font=_bebas(size), fill=T["fg"], anchor="ls")
    d.line((70, 1034, 1010, 1034), fill=T["track"], width=2)
    y = 1074
    for ln in m["lines"][:3]:
        t, f = _wrap_fit(d, ln, "Medium", 22, 900)
        d.ellipse((72, y - 13, 82, y - 3), fill=T["brand"])
        d.text((96, y), t, font=f, fill=T["sub"], anchor="ls")
        y += 42
    fcta = _font("Bold", 24)
    _ctext(d, 1218, "Análisis completo en Telegram · t.me/stakevision", fcta, T["brand"])
    _ctext(d, 1306, "+18 · Juega con responsabilidad", _font("Medium", 17), T["muted"])
    if m.get("credit"):
        fc = _font("Regular", 14)
        tw = round(d.textlength(m["credit"], font=fc)) + 8
        tmp = Image.new("RGBA", (tw, 22), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((0, 2), m["credit"], font=fc, fill=T["credit"])
        im.alpha_composite(tmp.rotate(-90, expand=True), (1040, 180))
    return _jpeg(im)



# ---------------------------------------------------------------- Bet Builder
def render_builder(pick: dict, tier: str | None = "vip") -> bytes:
    with accent(tier):
        return _render_builder(pick, tier)


def _render_builder(pick: dict, tier: str | None) -> bytes:
    """Cupón del Bet Builder: partido, 3 patas con su % de acierto, stake y cuota."""
    b = pick["bb"]
    l0 = pick["legs"][0]
    H = 1350
    im = _background(H).convert("RGBA")
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((W / 2 - 300, 40, W / 2 + 300, 260), fill=BRAND + (40,))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(60)))
    logo = _logo_t(460, "dark")
    lpad = logo.info["pad"]
    im.alpha_composite(logo, ((W - logo.width) // 2, max(0, 50 - lpad)))
    y0 = 50 + logo.height - 2 * lpad + 70
    card_h = 70 + 58 + 64 + 120 * len(b["legs"]) + 150
    y0 += max(0, (H - 200 - y0 - card_h) // 2)   # centrar la tarjeta en el espacio libre
    card = (80, y0, W - 80, y0 + card_h)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((card[0], card[1] + 14, card[2], card[3] + 14), 34, fill=(0, 0, 0, 150))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(22)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(card, 34, fill=(255, 255, 255), outline=BRAND if tier == "vip" else None,
                        width=6 if tier == "vip" else 0)
    label = "BET BUILDER · VIP" if tier == "vip" else "BET BUILDER"
    fpl = _font("Bold", 30)
    pw = d.textlength(label, font=fpl) + 64
    d.rounded_rectangle(((W - pw) / 2, y0 - 30, (W + pw) / 2, y0 + 30), 30, fill=BRAND)
    d.text((W / 2, y0 + 1), label, font=fpl, fill=(16, 20, 8), anchor="mm")
    x0, x1 = card[0] + 48, card[2] - 48
    y = y0 + 70
    title, ft = _fit(d, f"{l0['home']} vs {l0['away']}", "Bold", 40, x1 - x0)
    d.text((x0, y), title, font=ft, fill=INK)
    y += 58
    d.text((x0, y), f"{l0.get('league') or ''} · {formatting.local_time(l0['kickoff'])}", font=_font("Medium", 26), fill=MUTED)
    y += 64
    for i, x in enumerate(b["legs"]):
        d.ellipse((x0, y + 4, x0 + 44, y + 48), fill=BRAND)
        d.text((x0 + 22, y + 26), str(i + 1), font=_font("Bold", 26), fill=(16, 20, 8), anchor="mm")
        lab, fl = _fit(d, x["label"], "Bold", 32, x1 - x0 - 200)
        d.text((x0 + 64, y + 4), lab, font=fl, fill=INK)
        rate = f"{x['hits']}/{x['n']}"
        fr = _font("Bold", 30)
        d.text((x1 - d.textlength(rate, font=fr), y + 6), rate, font=fr, fill=GREEN)
        d.text((x0 + 64, y + 50), f"Promedio {formatting._n(x['avg'])} {x['word']} · cumplió {x['hits']} de {x['n']}",
               font=_font("Medium", 23), fill=MUTED)
        y += 120
    by = card[3] - 110
    d.rounded_rectangle((card[0], by, card[2], card[3]), 34, fill=(244, 245, 242))
    d.rectangle((card[0], by, card[2], by + 34), fill=(244, 245, 242))
    fl2, fv = _font("Medium", 26), _font("Bold", 44)
    d.text((x0, by + 36), "STAKE", font=fl2, fill=MUTED)
    d.text((x0 + d.textlength("STAKE", font=fl2) + 16, by + 26), f"{pick['stake']}/10", font=fv, fill=INK)
    tot = formatting.odds(pick["price"])
    tw = d.textlength(tot, font=fv)
    d.text((x1 - tw, by + 26), tot, font=fv, fill=GREEN)
    d.text((x1 - tw - 16 - d.textlength("CUOTA", font=fl2), by + 36), "CUOTA", font=fl2, fill=MUTED)
    pr = f"Probabilidad estimada {formatting.pct(pick['prob'])}"
    _ctext(d, card[3] + 50, pr, _font("Medium", 30), (220, 224, 218))
    _ctext(d, H - 70, "@stakevision · +18 · Juega con responsabilidad", _font("Regular", 24), (150, 156, 148))
    return _jpeg(im)
