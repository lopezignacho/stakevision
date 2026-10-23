"""Diseños alternativos para que el feed no se vea siempre igual.

Post partido: «revista» (postimage.render_recap), «marcador» y «póster».
Pick con foto: «revista» (postimage.render_pick_photo), «ticket» y «dividido».
Todos aceptan modo noche (dark) y día (light) y usan los mismos datos.
"""
from __future__ import annotations

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import postimage as P

W, H = 1080, 1350
RECAP_LAYOUTS = ["revista", "marcador", "poster"]
PICK_LAYOUTS = ["revista", "ticket", "dividido"]
LAYOUT_NAMES = {"revista": "Revista", "marcador": "Marcador", "poster": "Póster", "ticket": "Ticket",
                "dividido": "Dividido"}


# ---------------------------------------------------------------- piezas comunes
def _photo_area(im, m, box, T, side="center", fade=("bottom",)):
    """Pega la foto en una zona y la funde con el fondo por los lados indicados."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if m.get("photo"):
        ph = P._enhance(P._cover(m["photo"], (w, h), side=side)).convert("RGBA")
    else:
        ph = Image.new("RGBA", (w, h), T["bg"] + (255,))
    bg = Image.new("RGBA", (w, h), T["bg"] + (255,))
    for f in fade:
        if f == "bottom":
            ph = Image.composite(bg, ph, P._alpha_ramp((w, h), [(0, 0), (0.55, 0), (1, 255)], False))
        elif f == "top":
            ph = Image.composite(bg, ph, P._alpha_ramp((w, h), [(0, 150), (0.25, 0), (1, 0)], False))
        elif f == "left":
            ph = Image.composite(bg, ph, P._alpha_ramp((w, h), [(0, 255), (0.25, 0), (1, 0)], True))
    im.alpha_composite(ph, (x0, y0))


def _outline_text(im, xy, text, font, color, stroke=3):
    outer, inner = Image.new("L", im.size, 0), Image.new("L", im.size, 0)
    ImageDraw.Draw(outer).text(xy, text, font=font, fill=255, anchor="ls", stroke_width=stroke, stroke_fill=255)
    ImageDraw.Draw(inner).text(xy, text, font=font, fill=255, anchor="ls")
    im.paste(tuple(color) + (255,), (0, 0), ImageChops.subtract(outer, inner))


def _fit_bebas(d, lines, size, max_w, min_size=90):
    while size > min_size and max(d.textlength(t, font=P._bebas(size)) for t in lines if t) > max_w:
        size -= 4
    return P._bebas(size), size


def _pill(d, xy, text, font, fill, color, pad=(22, 10), spacing=3.0):
    x, y = xy
    tw = P._spaced_len(d, text, font, spacing)
    d.rounded_rectangle((x, y, x + tw + 2 * pad[0], y + font.size + 2 * pad[1]), (font.size + 2 * pad[1]) // 2, fill=fill)
    P._spaced(d, (x + pad[0], y + pad[1] + font.size * 0.86), text, font, color, spacing)
    return x + tw + 2 * pad[0]


def _credit(im, T, text, x=1040, y=180):
    if not text:
        return
    d = ImageDraw.Draw(im)
    fc = P._font("Regular", 14)
    tmp = Image.new("RGBA", (round(d.textlength(text, font=fc)) + 8, 22), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((0, 2), text, font=fc, fill=T["credit"])
    im.alpha_composite(tmp.rotate(-90, expand=True), (x, y))


def _team_name(t):
    return (t.get("short") or t.get("name") or "").strip()


def _goal_name(g):
    nm = g["player"].split(". ", 1)[-1] if ". " in g["player"] else g["player"]
    return nm + (" (P)" if g["kind"] == "penalty" else " (EC)" if g["kind"] == "own" else "")


def _legal(d, T, y=1306):
    P._ctext(d, y, "+18 · Juega con responsabilidad", P._font("Medium", 17), T["muted"])


# ---------------------------------------------------------------- post partido: «marcador»
def recap_marcador(m: dict, theme: str = "dark") -> bytes:
    """Foto arriba a todo lo ancho, gran barra de marcador con escudos y los goles en dos columnas."""
    T = P._mag(theme)
    rep = m["report"]
    home, away = rep["home"], rep["away"]
    hacc, aacc = P._accents(home, away, theme)
    im = Image.new("RGBA", (W, H), T["bg"] + (255,))
    _photo_area(im, m, (0, 0, W, 800), T, side="center", fade=("bottom", "top"))
    d = ImageDraw.Draw(im)
    P._put_logo(im, 165, theme, 56, 40)
    if m.get("eyebrow"):
        f = P._oswald(22)
        tw = P._spaced_len(d, m["eyebrow"].upper(), f, 3) + 44
        _pill(d, (W - 40 - tw, 56), m["eyebrow"].upper(), f, T["brand"], (11, 26, 6) if theme == "dark" else (255, 255, 255))
    title = (m.get("headline") or "").replace("-", "")
    ft, _s = _fit_bebas(d, [title], 92, 900, 56)
    tw = d.textlength(title, font=ft) + 60
    d.rounded_rectangle((40, 560, 40 + tw, 560 + ft.size + 14), 14, fill=T["brand"])
    d.text((70, 560 + ft.size * 0.93), title, font=ft, fill=(11, 26, 6) if theme == "dark" else (255, 255, 255), anchor="ls")
    # barra del marcador
    P._mag_card(im, (40, 690, 1040, 900), T, r=28)
    d = ImageDraw.Draw(im)
    im.alpha_composite(P.shield(home, 120), (78, 718))
    im.alpha_composite(P.shield(away, 120), (W - 78 - 120, 718))
    win = "home" if home["score"] > away["score"] else "away" if away["score"] > home["score"] else ""
    fs = P._bebas(210)
    hs, as_ = str(home["score"]), str(away["score"])
    gap = 120
    total = d.textlength(hs, font=fs) + gap + d.textlength(as_, font=fs)
    x = (W - total) / 2
    d.text((x, 872), hs, font=fs, fill=hacc if win == "home" else T["fg"], anchor="ls")
    d.rectangle((x + d.textlength(hs, font=fs) + 34, 790, x + d.textlength(hs, font=fs) + gap - 34, 802), fill=T["brand"])
    d.text((x + d.textlength(hs, font=fs) + gap, 872), as_, font=fs, fill=aacc if win == "away" else T["fg"], anchor="ls")
    fn = P._oswald(24)
    d.text((80, 940), _team_name(home).upper(), font=fn, fill=T["sub"], anchor="ls")
    an = _team_name(away).upper()
    d.text((W - 80 - d.textlength(an, font=fn), 940), an, font=fn, fill=T["sub"], anchor="ls")
    sub = " ".join(x for x in (m.get("subline") or ("", "")) if x).strip()
    if sub:
        P._ctext(d, 916, sub, P._oswald(24, 500), T["muted"])
    # goles en dos columnas
    fm, fg = P._bebas(40), P._oswald(24)
    for side, col, x0 in (("home", hacc, 80), ("away", aacc, 560)):
        gs = [g for g in rep["goals"] if g["side"] == side]
        y = 1010
        for g in gs[:5]:
            d.ellipse((x0, y - 22, x0 + 14, y - 8), fill=col)
            d.text((x0 + 28, y), g["label"], font=fm, fill=col, anchor="ls")
            d.text((x0 + 28 + d.textlength(g["label"], font=fm) + 14, y - 4), _goal_name(g).upper(), font=fg,
                   fill=T["fg"], anchor="ls")
            y += 44
        if len(gs) > 5:
            d.text((x0 + 28, y), f"+{len(gs) - 5} más", font=fg, fill=T["muted"], anchor="ls")
    if not rep["goals"]:
        P._ctext(d, 1060, "Sin goles: el cero no se movió", P._oswald(28, 500), T["sub"])
    P._result_line(d, T, m, 1250)
    _legal(d, T)
    _credit(im, T, m.get("credit"))
    return P._jpeg(im)


# ---------------------------------------------------------------- post partido: «póster»
def recap_poster(m: dict, theme: str = "dark") -> bytes:
    """Fondo con el color del ganador, foto enmarcada e inclinada, titular apilado y goles en fichas."""
    T = P._mag(theme)
    rep = m["report"]
    home, away = rep["home"], rep["away"]
    hacc, aacc = P._accents(home, away, theme)
    win = "home" if home["score"] > away["score"] else "away" if away["score"] > home["score"] else ""
    wt = rep[win] if win else home
    fill, acc = P.team_palette(wt)
    if theme == "dark":
        top, bot = P._mix(fill, (0, 0, 0), 0.35), P._mix(fill, (0, 0, 0), 0.85)
    else:
        top, bot = P._mix(acc if P._lum(acc) < 0.9 else fill, (255, 255, 255), 0.82), T["bg"]
    im = P._vgrad((W, H), top, bot).convert("RGBA")
    d = ImageDraw.Draw(im)
    # marcador gigante de fondo
    big = f"{home['score']}-{away['score']}"
    fb = P._bebas(420)
    ghost = Image.new("L", im.size, 0)
    gd = ImageDraw.Draw(ghost)
    gx = W - gd.textlength(big, font=fb) + 20
    gd.text((gx, 1190), big, font=fb, fill=255, anchor="ls", stroke_width=3, stroke_fill=255)
    inner = Image.new("L", im.size, 0)
    ImageDraw.Draw(inner).text((gx, 1190), big, font=fb, fill=255, anchor="ls")
    edge = ImageChops.subtract(ghost, inner).point(lambda v: v * 0.2)
    im.paste((tuple(T["fg"]) + (255,)), (0, 0), edge)
    # foto enmarcada
    if m.get("photo"):
        fw, fh = 520, 660
        ph = P._enhance(P._cover(m["photo"], (fw, fh), side="center")).convert("RGBA")
        frame = Image.new("RGBA", (fw + 28, fh + 28), (255, 255, 255, 255))
        frame.alpha_composite(ph, (14, 14))
        sh = Image.new("RGBA", (frame.width + 80, frame.height + 80), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rectangle((40, 54, 40 + frame.width, 54 + frame.height), fill=(0, 0, 0, 120))
        sh = sh.filter(ImageFilter.GaussianBlur(22))
        sh.alpha_composite(frame, (40, 40))
        rot = sh.rotate(-4, resample=Image.BICUBIC, expand=True)
        im.alpha_composite(rot, (W - rot.width + 30, 120))
    d = ImageDraw.Draw(im)
    P._put_logo(im, 165, theme, 56, 40)
    if m.get("eyebrow"):
        P._spaced(d, (60, 250), m["eyebrow"].upper(), P._oswald(24), T["brand"], 3.2)
    l1, l2 = P.split_headline(m.get("headline") or "")
    ft, size = _fit_bebas(d, [l1, l2], 170, 470, 90)
    b1 = 270 + round(0.714 * size)
    d.text((56, b1), l1, font=ft, fill=T["fg"], anchor="ls")
    if l2:
        _outline_text(im, (56, b1 + round(0.84 * size)), l2, ft, T["brand"])
    d = ImageDraw.Draw(im)
    y0 = 700
    im.alpha_composite(P.shield(home, 84), (56, y0))
    fs = P._bebas(130)
    x = 56 + 84 + 22
    d.text((x, y0 + 96), str(home["score"]), font=fs, fill=hacc if win == "home" else T["fg"], anchor="ls")
    x += d.textlength(str(home["score"]), font=fs) + 20
    d.rectangle((x, y0 + 44, x + 34, y0 + 52), fill=T["brand"])
    x += 34 + 20
    d.text((x, y0 + 96), str(away["score"]), font=fs, fill=aacc if win == "away" else T["fg"], anchor="ls")
    x += d.textlength(str(away["score"]), font=fs) + 22
    im.alpha_composite(P.shield(away, 84), (round(x), y0))
    sub = " ".join(t for t in (m.get("subline") or ("", "")) if t).strip()
    if sub:
        d.text((58, 850), sub, font=P._oswald(24, 500), fill=T["sub"], anchor="ls")
    # goles en fichas
    fchip, fmin = P._oswald(22), P._bebas(34)
    x, y = 56, 922
    for g in rep["goals"][:8]:
        col = hacc if g["side"] == "home" else aacc
        name = _goal_name(g).upper()
        cw = d.textlength(g["label"], font=fmin) + d.textlength(name, font=fchip) + 66
        if x + cw > 1024:
            x, y = 56, y + 70
        if y > 1130:
            break
        P._mag_card(im, (x, y, x + cw, y + 54), T, r=27)
        d = ImageDraw.Draw(im)
        d.ellipse((x + 18, y + 20, x + 32, y + 34), fill=col)
        d.text((x + 42, y + 42), g["label"], font=fmin, fill=col, anchor="ls")
        d.text((x + 42 + d.textlength(g["label"], font=fmin) + 10, y + 37), name, font=fchip, fill=T["fg"], anchor="ls")
        x += cw + 14
    if not rep["goals"]:
        d.text((58, 950), "Sin goles: el cero no se movió", font=P._oswald(26, 500), fill=T["sub"], anchor="ls")
    P._result_line(d, T, m, 1238)
    _legal(d, T)
    if m.get("credit"):
        fc = P._font("Regular", 14)
        d.text((W - 40 - d.textlength(m["credit"], font=fc), 906), m["credit"], font=fc, fill=T["credit"], anchor="ls")
    return P._jpeg(im)


# ---------------------------------------------------------------- pick: «ticket»
def pick_ticket(m: dict, theme: str = "dark") -> bytes:
    """Foto arriba y el pick como un boleto troquelado: cruce arriba, selección y cuota abajo."""
    T = P._mag(theme)
    home, away = m["teams"]["home"], m["teams"]["away"]
    im = Image.new("RGBA", (W, H), T["bg"] + (255,))
    _photo_area(im, m, (0, 0, W, 760), T, side="center", fade=("bottom", "top"))
    d = ImageDraw.Draw(im)
    P._put_logo(im, 165, theme, 56, 40)
    l1, l2 = P.split_headline(m["headline"])
    title = f"{l1.rstrip('-')} {l2}".strip() if l2 else l1
    ft, _s = _fit_bebas(d, [title], 150, 960, 80)
    d.text((56, 600), title, font=ft, fill=T["fg"], anchor="ls")
    P._spaced(d, (60, 646), m["eyebrow"].upper(), P._oswald(24), T["brand"], 3.2)
    # boleto
    x0, y0, x1, y1 = 50, 690, 1030, 1220
    P._mag_card(im, (x0, y0, x1, y1), T, r=30)
    d = ImageDraw.Draw(im)
    cut = 880
    for cx in (x0, x1):
        d.ellipse((cx - 26, cut - 26, cx + 26, cut + 26), fill=T["bg"])
    for xx in range(x0 + 40, x1 - 40, 26):
        d.line((xx, cut, xx + 12, cut), fill=T["track"], width=3)
    im.alpha_composite(P.shield(home, 84), (116, 712))
    im.alpha_composite(P.shield(away, 84), (W - 116 - 84, 712))
    fv = P._bebas(110)
    P._ctext(d, 738, "VS", fv, T["brand"])
    for t, cx in ((home, 158), (away, W - 158)):
        nm, fnm = P._wrap_fit(d, _team_name(t).upper(), "Bold", 24, 300)
        d.text((cx - d.textlength(nm, font=fnm) / 2, 860), nm, font=fnm, fill=T["sub"], anchor="ls")
    P._spaced(d, (100, 940), "EL PICK", P._oswald(22), T["muted"], 3.5)
    sel = m["selection"].upper()
    fsel, _s = _fit_bebas(d, [sel], 92, 640, 50)
    d.text((100, 1030), sel, font=fsel, fill=T["fg"], anchor="ls")
    # cuota en sello circular
    cx, cy, r = 880, 1000, 92
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=P.BRAND)
    d.ellipse((cx - r + 10, cy - r + 10, cx + r - 10, cy + r - 10), outline=(11, 26, 6), width=2)
    fo = P._bebas(76)
    d.text((cx - d.textlength(m["odds"], font=fo) / 2, cy + 22), m["odds"], font=fo, fill=(11, 26, 6), anchor="ls")
    fsm = P._oswald(16)
    P._spaced(d, (cx - P._spaced_len(d, "CUOTA", fsm, 2) / 2, cy - 38), "CUOTA", fsm, (11, 26, 6), 2)
    y = 1086
    for ln in m["lines"][:3]:
        t, f = P._wrap_fit(d, ln, "Medium", 22, 640)
        d.ellipse((102, y - 13, 112, y - 3), fill=T["brand"])
        d.text((126, y), t, font=f, fill=T["sub"], anchor="ls")
        y += 40
    if m.get("stake"):
        st = f"STAKE {m['stake']}/10"
        fs_ = P._oswald(20)
        P._spaced(d, (cx - P._spaced_len(d, st, fs_, 2) / 2, cy + r + 36), st, fs_, T["muted"], 2)
    P._ctext(d, 1262, "Análisis completo en Telegram · t.me/stakevision", P._font("Bold", 24), T["brand"])
    _legal(d, T, 1316)
    _credit(im, T, m.get("credit"), x=1046, y=150)
    return P._jpeg(im)


# ---------------------------------------------------------------- pick: «dividido»
def pick_dividido(m: dict, theme: str = "dark") -> bytes:
    """Panel con los colores del equipo a la izquierda, foto a la derecha y franja verde con el pick."""
    T = P._mag(theme)
    home, away = m["teams"]["home"], m["teams"]["away"]
    fill, acc = P.team_palette(home)
    im = Image.new("RGBA", (W, H), T["bg"] + (255,))
    _photo_area(im, m, (430, 0, W, 1080), T, side="center", fade=("left", "bottom"))
    if theme == "dark":
        c0, c1 = P._mix(fill, (0, 0, 0), 0.25), P._mix(fill, (0, 0, 0), 0.8)
    else:
        c0, c1 = P._mix(fill if P._lum(fill) < 0.8 else acc, (255, 255, 255), 0.78), T["bg"]
    panel = P._vgrad((520, 1080), c0, c1).convert("RGBA")
    mask = Image.new("L", panel.size, 0)
    ImageDraw.Draw(mask).polygon([(0, 0), (520, 0), (430, 1080), (0, 1080)], fill=255)
    im.paste(panel, (0, 0), mask)
    d = ImageDraw.Draw(im)
    P._put_logo(im, 165, theme, 56, 40)
    P._spaced(d, (60, 250), m["eyebrow"].upper(), P._oswald(22), T["brand"] if theme == "light" else P.BRAND, 3)
    l1, l2 = P.split_headline(m["headline"])
    ft, size = _fit_bebas(d, [l1, l2], 170, 380, 90)
    b1 = 268 + round(0.714 * size)
    d.text((56, b1), l1, font=ft, fill=T["fg"], anchor="ls")
    if l2:
        _outline_text(im, (56, b1 + round(0.84 * size)), l2, ft, T["brand"] if theme == "light" else P.BRAND)
    d = ImageDraw.Draw(im)
    y = 640
    for t, label in ((home, None), (None, "VS"), (away, None)):
        if t:
            im.alpha_composite(P.shield(t, 86), (56, y))
            nm, fnm = P._wrap_fit(d, _team_name(t).upper(), "Bold", 30, 230)
            d.text((160, y + 62), nm, font=fnm, fill=T["fg"], anchor="ls")
            y += 110
        else:
            d.text((80, y + 52), label, font=P._bebas(64), fill=T["brand"] if theme == "light" else P.BRAND, anchor="ls")
            y += 70
    # franja del pick
    d.rectangle((0, 1080, W, 1236), fill=P.BRAND)
    d = ImageDraw.Draw(im)
    P._spaced(d, (56, 1118), "EL PICK", P._oswald(20), (11, 26, 6), 3)
    sel = m["selection"].upper()
    fsel, _s = _fit_bebas(d, [sel], 88, 700, 48)
    d.text((54, 1206), sel, font=fsel, fill=(11, 26, 6), anchor="ls")
    fo = P._bebas(80)
    ow = d.textlength(m["odds"], font=fo) + 60
    d.rounded_rectangle((W - 56 - ow, 1112, W - 56, 1206), 20, fill=(11, 26, 6))
    d.text((W - 56 - ow + 30, 1192), m["odds"], font=fo, fill=P.BRAND, anchor="ls")
    if m.get("stake"):
        st = f"STAKE {m['stake']}/10"
        fs_ = P._oswald(18)
        P._spaced(d, (W - 56 - P._spaced_len(d, st, fs_, 2), 1228), st, fs_, (11, 26, 6), 2)
    line = m["lines"][0] if m["lines"] else ""
    if line:
        t, f = P._wrap_fit(d, line, "Medium", 21, 960)
        P._ctext(d, 1272, t, f, T["sub"])
    _legal(d, T, 1316)
    _credit(im, T, m.get("credit"), x=1046, y=150)
    return P._jpeg(im)


# ---------------------------------------------------------------- despacho
def render_recap(m: dict, layout: str = "revista", theme: str = "dark") -> bytes:
    return {"marcador": recap_marcador, "poster": recap_poster}.get(layout, P.render_recap)(m, theme)


def render_pick(m: dict, layout: str = "revista", theme: str = "dark") -> bytes:
    return {"ticket": pick_ticket, "dividido": pick_dividido}.get(layout, P.render_pick_photo)(m, theme)


def next_layout(state: dict, kind: str) -> str:
    """Rota los diseños: cada publicación nueva usa el siguiente (nunca dos iguales seguidas)."""
    opts = RECAP_LAYOUTS if kind == "recap" else PICK_LAYOUTS
    seq = state.setdefault("design_seq", {})
    i = seq.get(kind, -1) + 1
    seq[kind] = i
    return opts[i % len(opts)]


def cycle(current: str | None, kind: str) -> str:
    opts = RECAP_LAYOUTS if kind == "recap" else PICK_LAYOUTS
    i = opts.index(current) if current in opts else 0
    return opts[(i + 1) % len(opts)]


# ---------------------------------------------------------------- entretiempo
def halftime(m: dict, theme: str = "dark") -> bytes:
    """Entretiempo: foto, marcador al descanso, goles, barras de estadísticas y cómo va el pick.
    m = {"report", "eyebrow", "photo", "credit", "stats": [(label, local, visita, unidad)],
         "pick_label", "odds", "status": (W|L|V|?, texto)}"""
    T = P._mag(theme)
    rep = m["report"]
    home, away = rep["home"], rep["away"]
    hacc, aacc = P._accents(home, away, theme)
    im = Image.new("RGBA", (W, H), T["bg"] + (255,))
    _photo_area(im, m, (0, 0, W, 660), T, side="center", fade=("bottom", "top"))
    d = ImageDraw.Draw(im)
    P._put_logo(im, 165, theme, 56, 40)
    if m.get("eyebrow"):
        f = P._oswald(22)
        tw = P._spaced_len(d, m["eyebrow"].upper(), f, 3) + 44
        _pill(d, (W - 40 - tw, 56), m["eyebrow"].upper(), f, T["brand"], (11, 26, 6) if theme == "dark" else (255, 255, 255))
    ft = P._bebas(84)
    title = "ENTRETIEMPO"
    tw = d.textlength(title, font=ft) + 60
    d.rounded_rectangle((40, 470, 40 + tw, 470 + 98), 14, fill=T["brand"])
    d.text((70, 470 + 80), title, font=ft, fill=(11, 26, 6) if theme == "dark" else (255, 255, 255), anchor="ls")
    # marcador
    P._mag_card(im, (40, 590, 1040, 770), T, r=28)
    d = ImageDraw.Draw(im)
    im.alpha_composite(P.shield(home, 104), (74, 612))
    im.alpha_composite(P.shield(away, 104), (W - 74 - 104, 612))
    fs = P._bebas(180)
    hs, as_ = str(home["score"]), str(away["score"])
    gap = 110
    total = d.textlength(hs, font=fs) + gap + d.textlength(as_, font=fs)
    x = (W - total) / 2
    lead = "home" if home["score"] > away["score"] else "away" if away["score"] > home["score"] else ""
    d.text((x, 748), hs, font=fs, fill=hacc if lead == "home" else T["fg"], anchor="ls")
    d.rectangle((x + d.textlength(hs, font=fs) + 30, 676, x + d.textlength(hs, font=fs) + gap - 30, 686), fill=T["brand"])
    d.text((x + d.textlength(hs, font=fs) + gap, 748), as_, font=fs, fill=aacc if lead == "away" else T["fg"], anchor="ls")
    fn = P._oswald(22)
    d.text((78, 806), _team_name(home).upper(), font=fn, fill=T["sub"], anchor="ls")
    an = _team_name(away).upper()
    d.text((W - 78 - d.textlength(an, font=fn), 806), an, font=fn, fill=T["sub"], anchor="ls")
    goals = " · ".join(f"{g['label']} {_goal_name(g)}" for g in rep["goals"]) or "Todavía sin goles"
    goals, fg = P._wrap_fit(d, "⚽ " + goals if rep["goals"] else goals, "Medium", 22, 620)
    P._ctext(d, 788, goals.replace("⚽ ", ""), fg, T["sub"])
    # estadísticas
    y = 880
    fl, fv = P._oswald(20), P._bebas(36)
    for label, hv, av, unit in (m.get("stats") or [])[:4]:
        tot = (hv + av) or 1
        P._ctext(d, y - 30, label.upper(), fl, T["muted"])
        hvs, avs = f"{hv:.0f}{unit}", f"{av:.0f}{unit}"
        d.text((70, y + 22), hvs, font=fv, fill=T["fg"], anchor="ls")
        d.text((W - 70 - d.textlength(avs, font=fv), y + 22), avs, font=fv, fill=T["fg"], anchor="ls")
        bx0, bx1, by = 170, W - 170, y + 6
        split = bx0 + (bx1 - bx0) * hv / tot
        d.rounded_rectangle((bx0, by, max(bx0 + 6, split - 3), by + 12), 6, fill=hacc)
        d.rounded_rectangle((min(bx1 - 6, split + 3), by, bx1, by + 12), 6, fill=aacc)
        y += 72
    # cómo va el pick
    res, txt = m["status"]
    col = {"W": P.BRAND, "L": (227, 38, 46), "V": (110, 116, 124)}.get(res, (230, 170, 30))
    ink = (11, 26, 6) if res == "W" else (255, 255, 255)
    by0 = max(y + 6, 1150)
    d.rounded_rectangle((40, by0, 1040, by0 + 120), 22, fill=col)
    head = f"NUESTRO PICK: {m['pick_label'].upper()} @ {m['odds']}"
    head, fh = P._wrap_fit(d, head, "Bold", 24, 920)
    d.text((70, by0 + 46), head, font=fh, fill=ink, anchor="ls")
    import re as _re
    txt = _re.sub(r"[\u2190-\u2BFF\U0001F000-\U0001FAFF\uFE0F]", "", txt).strip()
    t2, f2 = P._wrap_fit(d, txt, "Medium", 23, 920)
    d.text((70, by0 + 92), t2, font=f2, fill=ink, anchor="ls")
    _legal(d, T, 1318)
    _credit(im, T, m.get("credit"), x=1046, y=150)
    return P._jpeg(im)
