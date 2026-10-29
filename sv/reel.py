"""Reels automáticos (MP4 vertical 1080x1920, ~10 s) para noticias y postpartidos.

Misma estética que las imágenes: foto libre (con zoom lento) o colores del equipo, titular en Bebas Neue,
datos que entran uno a uno y cierre con «Síguenos». Pillow arma cada cuadro y ffmpeg los codifica
(H.264 + pista de audio silenciosa, formato que Instagram acepta para Reels).
"""
from __future__ import annotations

import io
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFilter

from . import newsimage as NI
from . import postimage as P

W, H, FPS = 1080, 1920, 30
WHITE = (255, 255, 255)
GOLD = (255, 196, 0)


# ---------------------------------------------------------------- utilidades
def _ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


class Layer:
    """Capa (imagen RGBA) que entra subiendo y aparece en t0, con duración d."""

    def __init__(self, img: Image.Image, x: int, y: int, t0: float, d: float = 0.45, dy: int = 50):
        self.img, self.x, self.y, self.t0, self.d, self.dy = img, x, y, t0, d, dy

    def draw(self, frame: Image.Image, t: float) -> None:
        k = _ease((t - self.t0) / self.d)
        if k <= 0:
            return
        im = self.img
        if k < 1:
            im = im.copy()
            im.putalpha(im.getchannel("A").point(lambda v: int(v * k)))
        frame.alpha_composite(im, (self.x, int(self.y + (1 - k) * self.dy)))


def _text_layer(text: str, font, fill, max_w: int | None = None) -> Image.Image:
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w = int(d.textlength(text, font=font)) + 8
    bb = font.getbbox("ÁÉgjpqy")
    h = bb[3] + 12
    im = Image.new("RGBA", (min(w, max_w or w), h), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((0, 0), text, font=font, fill=fill)
    return im


def _chip_layer(text: str, fill, ink, size: int = 34, pad: int = 26) -> Image.Image:
    f = P._font("Bold", size)
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w = int(d.textlength(text, font=f)) + pad * 2
    h = size + 30
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(im)
    dd.rounded_rectangle((0, 0, w - 1, h - 1), h // 2, fill=fill)
    dd.text((pad, h / 2), text, font=f, fill=ink, anchor="lm")
    return im


def _panel_layer(lines_by_item: list[list[str]], font, lh: int, title: str | None = None) -> tuple[Image.Image, list[int]]:
    """Tarjeta oscura con viñetas. Devuelve la tarjeta vacía y la altura (y) de cada ítem dentro de ella."""
    top = 92 if title else 40
    h = top + sum(lh * len(l) + 30 for l in lines_by_item) + 10
    im = Image.new("RGBA", (W - 96, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, W - 97, h - 1), 32, fill=(10, 12, 18, 190))
    if title:
        d.text((36, 34), title, font=P._font("Bold", 30), fill=GOLD)
    ys, y = [], top
    for l in lines_by_item:
        ys.append(y)
        y += lh * len(l) + 30
    return im, ys


def _item_layer(lines: list[str], font, lh: int, dot=GOLD) -> Image.Image:
    im = Image.new("RGBA", (W - 160, lh * len(lines) + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((0, 14, 16, 30), fill=dot)
    for i, ln in enumerate(lines):
        d.text((38, i * lh), ln, font=font, fill=WHITE)
    return im


def _background(colors, photo: bytes | None, zoom_t: float, photo_h: int = 1180) -> Image.Image:
    """Fondo del cuadro: colores del equipo y, si hay, la foto arriba con zoom lento (Ken Burns)."""
    key = ("bg", tuple(map(tuple, colors)))
    if key not in _PHOTO_CACHE:
        _PHOTO_CACHE[key] = NI._backdrop(*colors).resize((W, H)).convert("RGBA")
    base = _PHOTO_CACHE[key].copy()
    if photo:
        ph = _PHOTO_CACHE.get(id(photo))
        if ph is None:
            ph = P._enhance(P._cover(photo, (int(W * 1.12), int(photo_h * 1.12)))).convert("RGBA")
            _PHOTO_CACHE[id(photo)] = ph
        z = 1.12 - 0.12 * zoom_t   # de cerca (1.12) a abierto (1.0)
        cw, chh = min(ph.width, int(ph.width / z)), min(ph.height, int(ph.height / z))
        cx, cy = (ph.width - cw) // 2, int((ph.height - chh) * 0.3)
        crop = ph.crop((cx, cy, cx + cw, cy + chh)).resize((W, photo_h))
        mask = _MASKS.get(photo_h)
        if mask is None:
            mask = Image.linear_gradient("L").resize((W, photo_h)).point(lambda v: int(255 - max(0, v - 90) * 255 / 165))
            _MASKS[photo_h] = mask
        base.paste(crop, (0, 0), mask)
        top = Image.linear_gradient("L").resize((W, 320)).point(lambda v: int((255 - v) * 0.55))
        shade = Image.new("RGBA", (W, 320), (0, 0, 0, 255))
        shade.putalpha(top)
        base.alpha_composite(shade)
    return base


_PHOTO_CACHE: dict = {}
_MASKS: dict = {}


def _end_card(frame: Image.Image, k: float) -> None:
    """Cierre: fundido a oscuro con el logo y la invitación a seguir la cuenta."""
    if k <= 0:
        return
    ov = Image.new("RGBA", (W, H), (6, 8, 12, int(235 * k)))
    frame.alpha_composite(ov)
    if k < 0.4:
        return
    a = _ease((k - 0.4) / 0.6)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    lg = P._logo_t(560, "dark")
    layer.alpha_composite(lg, ((W - lg.width) // 2, 560))
    d = ImageDraw.Draw(layer)
    for y, txt, f, c in ((1040, "SÍGUENOS PARA MÁS", NI._bebas(110), WHITE),
                         (1170, "@" + P.INSTAGRAM, P._font("Bold", 56), GOLD),
                         (1290, "Noticias, datos y 1 pick gratis diario", P._font("Medium", 38), (220, 225, 232)),
                         (1345, "en nuestro Telegram · link en la bio", P._font("Medium", 38), (220, 225, 232))):
        d.text((W / 2, y), txt, font=f, fill=c, anchor="mt")
    layer.putalpha(layer.getchannel("A").point(lambda v: int(v * a)))
    frame.alpha_composite(layer)


def _ffmpeg() -> str:
    """ffmpeg del sistema o, si no está, el que trae el paquete imageio-ffmpeg."""
    import shutil
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _encode(make_frame, duration: float, path: str) -> None:
    n = int(duration * FPS)
    cmd = [_ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-level", "4.1", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(n):
            proc.stdin.write(make_frame(i / FPS).convert("RGB").tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg no pudo crear el video")


def _mp4(make_frame, duration: float) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "reel.mp4")
        _encode(make_frame, duration, path)
        with open(path, "rb") as f:
            return f.read()


SAFE_BOTTOM = 1560   # bajo esto Instagram pone el texto y los botones del Reel


def _footer_layers(credit: str | None, source: str) -> list[Layer]:
    out = []
    if credit:
        out.append(Layer(_text_layer(credit, P._font("Regular", 22), (190, 196, 206), W - 120), 60, SAFE_BOTTOM - 72, 1.0))
    out.append(Layer(_text_layer(source, P._font("Regular", 26), (205, 210, 220), W - 420), 60, SAFE_BOTTOM - 34, 1.0))
    ig = _text_layer("@" + P.INSTAGRAM, P._font("Medium", 32), WHITE)
    out.append(Layer(ig, W - 60 - ig.width, SAFE_BOTTOM - 38, 1.0))
    return out


# ---------------------------------------------------------------- noticia
def news(n: dict, duration: float = 11.0) -> tuple[bytes, bytes]:
    """Reel de una noticia (mismos campos que newsimage.render_news). Devuelve (mp4, portada jpg)."""
    colors = [tuple(c) for c in n["colors"]]
    photo = n.get("photo")
    _PHOTO_CACHE.clear()
    layers: list[Layer] = []
    d0 = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lg = P._logo_t(330, "dark")
    layers.append(Layer(lg, 60 - lg.info.get("pad", 0), 70 - lg.info.get("pad", 0), 0.0, 0.5, 0))
    tag = _chip_layer(n["tag"], (255, 77, 64), WHITE, 36)
    layers.append(Layer(tag, W - 60 - tag.width, 96, 0.25, 0.4, -30))
    if n.get("status"):
        stt = _chip_layer(n["status"], GOLD, (20, 16, 4), 28, 22)
        layers.append(Layer(stt, W - 60 - stt.width, 178, 0.45, 0.4, -30))
    y = 700 if photo else 420
    k = _text_layer(n["kicker"], P._font("Bold", 34), GOLD)
    layers.append(Layer(k, 60, y, 0.6))
    y += 62
    hf = NI._bebas(150)
    t = 0.8
    for line in NI._wrap(d0, n["headline"], hf, W - 120)[:3]:
        layers.append(Layer(_text_layer(line, hf, WHITE), 60, y, t, 0.5, 70))
        y += 140
        t += 0.22
    if n.get("sub"):
        sf = P._font("Medium", 38)
        for line in NI._wrap(d0, n["sub"], sf, W - 120)[:2]:
            layers.append(Layer(_text_layer(line, sf, (225, 230, 238)), 60, y + 8, t + 0.2))
            y += 52
    y += 40
    ff = P._font("Medium", 36)
    lh = 46
    items = [NI._wrap(d0, f, ff, W - 220)[:2] for f in n["facts"][:2 if photo else 3]]
    panel, ys = _panel_layer(items, ff, lh)
    t_panel = t + 0.9
    layers.append(Layer(panel, 48, y, t_panel, 0.5, 40))
    for i, (it, yy) in enumerate(zip(items, ys)):
        layers.append(Layer(_item_layer(it, ff, lh), 48 + 36, y + yy, t_panel + 0.5 + i * 1.1))
    layers += _footer_layers(n.get("credit"), n.get("source", ""))
    end_at = duration - 2.4

    def frame(tt: float) -> Image.Image:
        im = _background(colors, photo, min(1.0, tt / duration), 900)
        for L in layers:
            L.draw(im, tt)
        _end_card(im, (tt - end_at) / 0.8)
        return im

    cover = frame(end_at - 0.05)
    return _mp4(frame, duration), P._jpeg(cover)


# ---------------------------------------------------------------- postpartido
def postgame(g: dict, duration: float = 11.0) -> tuple[bytes, bytes]:
    """g = {colors, kicker, home:{name, short, score, color}, away:{...}, winner, when, notes:[...],
    note_title, pick:{text, result} | None, source, photo, credit}"""
    colors = [tuple(c) for c in g["colors"]]
    photo = g.get("photo")
    _PHOTO_CACHE.clear()
    d0 = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    layers: list[Layer] = []
    lg = P._logo_t(330, "dark")
    layers.append(Layer(lg, 60 - lg.info.get("pad", 0), 70 - lg.info.get("pad", 0), 0.0, 0.5, 0))
    fin = _chip_layer("FINAL", WHITE, (12, 14, 20), 36)
    layers.append(Layer(fin, W - 60 - fin.width, 96, 0.25, 0.4, -30))
    y0 = 640 if photo else 400
    layers.append(Layer(_text_layer(g["kicker"], P._font("Bold", 34), GOLD), 60, y0, 0.5))
    rows = []
    y = y0 + 80
    for i, side in enumerate(("home", "away")):
        tm = g[side]
        win = g.get("winner") == side
        col = WHITE if win or g.get("winner") is None else (175, 182, 194)
        name = Image.new("RGBA", (W - 380, 190), (0, 0, 0, 0))
        dn = ImageDraw.Draw(name)
        dn.rounded_rectangle((0, 8, 12, 170), 6, fill=tuple(tm["color"]))
        nm = tm["short"].upper()
        bf = NI._bebas(132)
        while dn.textlength(nm, font=bf) > W - 440 and bf.size > 70:
            bf = NI._bebas(bf.size - 6)
        dn.text((40, 0), nm, font=bf, fill=col)
        if tm["name"].upper() != tm["short"].upper():
            dn.text((40, 140), tm["name"], font=P._font("Medium", 30), fill=(205, 210, 220))
        layers.append(Layer(name, 60, y, 0.8 + i * 0.25, 0.5, 60))
        rows.append((y, int(tm["score"]), col, 1.1 + i * 0.25))
        y += 210
    when = _text_layer(g.get("when", ""), P._font("Regular", 30), (205, 210, 220))
    layers.append(Layer(when, 60, y - 10, 1.6))
    y += 60
    ff = P._font("Medium", 36)
    lh = 46
    items = [NI._wrap(d0, x, ff, W - 220)[:2] for x in g["notes"][:3 if photo else 4]]
    if items:
        panel, ys = _panel_layer(items, ff, lh, g.get("note_title", "LO QUE DEJÓ EL PARTIDO"))
        tp = 2.2
        layers.append(Layer(panel, 48, y, tp, 0.5, 40))
        for i, (it, yy) in enumerate(zip(items, ys)):
            layers.append(Layer(_item_layer(it, ff, lh), 48 + 36, y + yy, tp + 0.5 + i * 0.7))
        y += panel.height + 30
        last_t = tp + 0.5 + len(items) * 0.7
    else:
        last_t = 2.2
    if g.get("pick"):   # nuestro pick: arriba a la derecha, bajo «FINAL»
        pk = g["pick"]
        fill = (46, 170, 70) if pk["result"] == "W" else (150, 156, 166)
        chip = _chip_layer(pk["text"], fill, WHITE, 26, 22)
        if chip.width <= W - 60 - 440:   # cabe a la derecha sin tapar el logo
            layers.append(Layer(chip, W - 60 - chip.width, 178, last_t + 0.3, 0.4, -30))
        else:                            # si es largo, va bajo los goles
            layers.append(Layer(chip, 60, min(y, SAFE_BOTTOM - 150), last_t + 0.3))
    layers += _footer_layers(g.get("credit"), g.get("source", ""))
    sf = NI._bebas(190)
    end_at = duration - 2.4

    def frame(tt: float) -> Image.Image:
        im = _background(colors, photo, min(1.0, tt / duration), 760)
        for L in layers:
            L.draw(im, tt)
        d = ImageDraw.Draw(im)
        for yy, score, col, t0 in rows:   # el marcador sube contando
            k = _ease((tt - t0) / 0.9)
            if k <= 0:
                continue
            txt = str(round(score * k))
            d.text((W - 60 - d.textlength(txt, font=sf), yy - 14), txt, font=sf, fill=col)
        _end_card(im, (tt - end_at) / 0.8)
        return im

    cover = frame(end_at - 0.05)
    return _mp4(frame, duration), P._jpeg(cover)


def from_report(p: dict, rep: dict, photo: tuple[bytes, dict] | None = None) -> tuple[bytes, bytes]:
    """Reel del postpartido de un pick (o de /postpartido) a partir del resumen de ESPN."""
    from . import formatting, recap
    h, a = rep["home"], rep["away"]
    winner = "home" if h["score"] > a["score"] else "away" if a["score"] > h["score"] else None
    notes = []
    for gl in rep.get("goals") or []:
        extra = " (penal)" if gl["kind"] == "penalty" else " (en contra)" if gl["kind"] == "own" else ""
        notes.append(f"{gl['label']} {gl['player']}{extra} · {formatting.team(rep[gl['side']]['short'])}")
    if len(notes) > 4:
        notes = notes[:3] + [f"… y {len(rep['goals']) - 3} goles más"]
    if not notes:
        notes = ["Partido cerrado: el arco quedó en cero."]
    pick = None
    if p.get("result") in ("W", "V") and not p.get("news"):
        pick = {"text": f"Nuestro pick: {recap.pick_label(p)} · {'VERDE' if p['result'] == 'W' else 'NULA'}",
                "result": p["result"]}
    league = (p["legs"][0].get("league") or "") if p.get("legs") else ""
    g = {"colors": [h["color"], a["color"]], "kicker": formatting.league_name({"league": league}).upper() or "FÚTBOL",
         "home": {"name": formatting.team(h["name"]), "short": formatting.team(h["short"]), "score": h["score"], "color": h["color"]},
         "away": {"name": formatting.team(a["name"]), "short": formatting.team(a["short"]), "score": a["score"], "color": a["color"]},
         "winner": winner, "when": rep.get("venue") or "", "notes": notes, "note_title": "LOS GOLES",
         "pick": pick, "source": "Datos: ESPN"}
    if photo:
        g["photo"] = photo[0]
        cr = photo[1] or {}
        if cr.get("author"):
            g["credit"] = f"Foto: {cr['author']} / Wikimedia Commons ({cr.get('license')}), modificada"
    return postgame(g)


# ---------------------------------------------------------------- Reels visuales: foto protagonista, poco texto
def _photo_frame_maker(photo: bytes, colors, dark_from: float = 0.40):
    """Fondo a pantalla completa con zoom lento y degradado abajo (con el color del equipo)."""
    big = P._enhance(P._cover(photo, (int(W * 1.12), int(H * 1.12)), side="center")).convert("RGBA")
    c = tuple(colors[0]) if colors else (10, 12, 18)
    tint = tuple(int(v * 0.35) for v in c)
    over = Image.new("RGBA", (W, H), tint + (0,))
    over.putalpha(Image.linear_gradient("L").resize((W, H)).point(
        lambda v: 0 if v < 255 * dark_from else int(min(235, (v - 255 * dark_from) / (255 * (1 - dark_from)) * 290))))
    top = Image.new("RGBA", (W, 360), (0, 0, 0, 255))
    top.putalpha(Image.linear_gradient("L").resize((W, 360)).point(lambda v: int((255 - v) * 0.6)))
    over.alpha_composite(top, (0, 0))

    def bg(t: float) -> Image.Image:
        z = 1.12 - 0.12 * t
        cw, chh = int(big.width / z), int(big.height / z)
        cx, cy = (big.width - cw) // 2, int((big.height - chh) * 0.35)
        im = big.crop((cx, cy, cx + cw, cy + chh)).resize((W, H))
        im.alpha_composite(over)
        return im
    return bg


def hero(n: dict, duration: float = 9.5) -> tuple[bytes, bytes]:
    """Reel «héroe»: foto del protagonista, la cifra contando («0 → 44 PUNTOS») y su nombre."""
    bg = _photo_frame_maker(n["photo"], n.get("colors"))
    layers: list[Layer] = []
    lg = P._logo_t(300, "dark")
    layers.append(Layer(lg, 56 - lg.info.get("pad", 0), 70 - lg.info.get("pad", 0), 0.0, 0.5, 0))
    tag = _chip_layer(n.get("tag", "NOTICIA"), (255, 77, 64), WHITE, 34)
    layers.append(Layer(tag, W - 60 - tag.width, 92, 0.3, 0.4, -30))
    d0 = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lf = P._font("Medium", 40)
    lines = NI._wrap(d0, n["line"], lf, W - 120)[:2] if n.get("line") else []
    name = str(n.get("name") or n.get("headline") or "").upper()
    nf = NI._fit_line(d0, name, NI._bebas, 160, W - 110)
    bottom = SAFE_BOTTOM - 90
    y_line = bottom - 54 * len(lines)
    y_name = y_line - nf.size - 6
    for i, ln in enumerate(lines):
        layers.append(Layer(_text_layer(ln, lf, (232, 236, 242)), 58, y_line + 54 * i, 2.4 + 0.2 * i))
    layers.append(Layer(_text_layer(name, nf, WHITE), 52, y_name, 1.7, 0.5, 70))
    st = n.get("stat") or {}
    val = str(st.get("value") or "")
    num = int(val) if val.isdigit() else None
    vf = NI._bebas(360)
    y_stat = y_name - 330
    label = _text_layer(str(st.get("label", "")).upper(), NI._bebas(120), WHITE) if val else None
    layers += _footer_layers(n.get("credit"), n.get("source", ""))
    end_at = duration - 2.3

    def frame(tt: float) -> Image.Image:
        im = bg(min(1.0, tt / duration))
        if val:
            k = _ease((tt - 0.6) / 1.1)
            if k > 0:
                txt = str(round(num * k)) if num is not None else val
                d = ImageDraw.Draw(im)
                d.text((52, y_stat), txt, font=vf, fill=GOLD)
                vw = d.textlength(val, font=vf)
                if k >= 1 and label:
                    Layer(label, int(52 + vw + 26), y_stat + 190, 1.6, 0.4, 0).draw(im, tt)
        for L in layers:
            L.draw(im, tt)
        _end_card(im, (tt - end_at) / 0.8)
        return im

    cover = frame(end_at - 0.05)
    return _mp4(frame, duration), P._jpeg(cover)


def impact(n: dict, duration: float = 9.0) -> tuple[bytes, bytes]:
    """Reel «impacto»: foto grande y el titular entrando línea por línea."""
    bg = _photo_frame_maker(n["photo"], n.get("colors"), 0.36)
    layers: list[Layer] = []
    lg = P._logo_t(300, "dark")
    layers.append(Layer(lg, 56 - lg.info.get("pad", 0), 70 - lg.info.get("pad", 0), 0.0, 0.5, 0))
    tag = _chip_layer(n.get("tag", "NOTICIA"), (255, 77, 64), WHITE, 34)
    layers.append(Layer(tag, W - 60 - tag.width, 92, 0.3, 0.4, -30))
    d0 = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    hf = NI._bebas(170)
    lines = NI._wrap(d0, str(n.get("headline", "")).upper(), hf, W - 110)[:3]
    lf = P._font("Medium", 38)
    line2 = NI._wrap(d0, n["line"], lf, W - 120)[:1] if n.get("line") else []
    y = SAFE_BOTTOM - 110 - 150 * len(lines) - (56 if line2 else 0)
    if n.get("kicker"):
        layers.append(Layer(_text_layer(n["kicker"], P._font("Bold", 32), GOLD), 56, y - 60, 0.6))
    for i, ln in enumerate(lines):
        layers.append(Layer(_text_layer(ln, hf, WHITE), 52, y, 0.9 + 0.35 * i, 0.5, 80))
        y += 150
    if line2:
        layers.append(Layer(_text_layer(line2[0], lf, (232, 236, 242)), 58, y + 6, 2.2))
    layers += _footer_layers(n.get("credit"), n.get("source", ""))
    end_at = duration - 2.3

    def frame(tt: float) -> Image.Image:
        im = bg(min(1.0, tt / duration))
        for L in layers:
            L.draw(im, tt)
        _end_card(im, (tt - end_at) / 0.8)
        return im

    cover = frame(end_at - 0.05)
    return _mp4(frame, duration), P._jpeg(cover)


def versus(v: dict, duration: float = 9.0) -> tuple[bytes, bytes]:
    """Reel «versus»: las dos mitades entran desde los costados, aparece el VS y luego los equipos y la hora."""
    base = NI.versus_base(v, (W, H))
    hw = W // 2 + 60
    left_half = base.crop((0, 0, hw, H))
    right_half = base.crop((W - hw, 0, W, H))
    badge = NI._vs_badge(230)
    layers: list[Layer] = []
    lg = P._logo_t(300, "dark")
    layers.append(Layer(lg, 56 - lg.info.get("pad", 0), 70 - lg.info.get("pad", 0), 0.2, 0.5, 0))
    tag = _chip_layer(v.get("tag", "PARTIDO"), (255, 77, 64), WHITE, 34)
    layers.append(Layer(tag, W - 60 - tag.width, 92, 0.5, 0.4, -30))
    d0 = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    y = SAFE_BOTTOM - 520
    for i, side in enumerate(("home", "away")):
        t = v[side]
        nm = str(t.get("short") or t.get("name") or "").upper()
        nf = NI._fit_line(d0, nm, NI._bebas, 140, W // 2 - 80)
        img = _text_layer(nm, nf, WHITE)
        x = 56 if side == "home" else W - 56 - img.width
        layers.append(Layer(img, x, y, 1.4 + 0.2 * i, 0.5, 60))
        if t.get("player"):
            pl = _text_layer(str(t["player"]), P._font("Medium", 32), (225, 230, 238))
            layers.append(Layer(pl, 58 if side == "home" else W - 58 - pl.width, y + nf.size + 6, 1.8 + 0.2 * i))
    if v.get("kicker"):
        k = _text_layer(v["kicker"], P._font("Bold", 34), GOLD)
        layers.append(Layer(k, (W - k.width) // 2, y + 210, 2.3))
    if v.get("when"):
        wl = _text_layer(v["when"], P._font("Medium", 36), WHITE)
        layers.append(Layer(wl, (W - wl.width) // 2, y + 262, 2.5))
    layers += _footer_layers(v.get("credit"), v.get("source", ""))
    end_at = duration - 2.3
    by = SAFE_BOTTOM - 800

    def frame(tt: float) -> Image.Image:
        im = Image.new("RGBA", (W, H), (6, 8, 12, 255))
        k = _ease(tt / 0.8)
        im.alpha_composite(left_half, (int(-hw * (1 - k)), 0))
        rh = right_half.copy()
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).polygon([(int(W * 0.58), 0), (W, 0), (W, H), (int(W * 0.42), H)], fill=255)
        rl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        rl.paste(rh, (W - hw + int(hw * (1 - k)), 0))
        im.paste(rl, (0, 0), Image.composite(mask, Image.new("L", (W, H), 0), rl.getchannel("A")))
        kb = _ease((tt - 0.9) / 0.35)
        if kb > 0:
            s_ = max(1, int(badge.width * (0.6 + 0.4 * kb)))
            b = badge.resize((s_, s_))
            b.putalpha(b.getchannel("A").point(lambda a: int(a * kb)))
            im.alpha_composite(b, ((W - s_) // 2, by + (badge.width - s_) // 2))
        for L in layers:
            L.draw(im, tt)
        _end_card(im, (tt - end_at) / 0.8)
        return im

    cover = frame(end_at - 0.05)
    return _mp4(frame, duration), P._jpeg(cover)


def still(img: bytes, duration: float = 8.0) -> tuple[bytes, bytes]:
    """Reel a partir de una imagen ya armada (4:5): fondo desenfocado, la imagen con un acercamiento lento y el cierre."""
    src = Image.open(io.BytesIO(img)).convert("RGBA")
    scale = W / src.width
    fg = src.resize((W, int(src.height * scale)), Image.LANCZOS)
    bg = src.resize((int(src.width * H / src.height), H), Image.LANCZOS)
    bg = bg.crop(((bg.width - W) // 2, 0, (bg.width - W) // 2 + W, H)).filter(ImageFilter.GaussianBlur(30))
    bg.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, 120)))
    y0 = max(0, (SAFE_BOTTOM - fg.height) // 2 + 40)
    end_at = duration - 2.2

    def frame(tt: float) -> Image.Image:
        im = bg.copy()
        z = 1.0 + 0.05 * min(1.0, tt / end_at)
        f = fg.resize((int(W * z), int(fg.height * z)), Image.BILINEAR)
        im.alpha_composite(f, ((W - f.width) // 2, y0 - (f.height - fg.height) // 2))
        _end_card(im, (tt - end_at) / 0.8)
        return im

    return _mp4(frame, duration), P._jpeg(frame(0.5))
