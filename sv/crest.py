"""Escudos oficiales de los equipos (los que publica ESPN), para los formatos Cartel, Figura, Versus y Resultado.
Se prefiere la versión para fondo oscuro. Si no se encuentra, las plantillas usan la sigla en un círculo."""
from __future__ import annotations

import io
import unicodedata

import requests
from PIL import Image

BASE = "https://site.api.espn.com/apis/site/v2/sports"
SOCCER_LEAGUES = ("chi.1", "eng.1", "esp.1", "ita.1", "ger.1", "fra.1", "por.1", "ned.1", "arg.1", "bra.1", "mex.1",
                  "usa.1", "uefa.champions", "conmebol.libertadores", "conmebol.sudamericana")
_TEAMS: dict[str, list[dict]] = {}
_IMG: dict[str, bytes | None] = {}


def _plain(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()


def _logo_url(team: dict) -> str:
    logos = team.get("logos") or []
    for want in ("dark", "default"):
        for lg in logos:
            if want in (lg.get("rel") or []) and lg.get("href"):
                return lg["href"]
    return team.get("logo") or (logos[0].get("href") if logos else "")


def _teams(path: str) -> list[dict]:
    if path not in _TEAMS:
        try:
            r = requests.get(f"{BASE}/{path}/teams", params={"limit": 400}, timeout=25).json()
            rows = [t.get("team") or {} for lg in r.get("sports", [{}])[0].get("leagues", [{}]) for t in lg.get("teams") or []]
        except Exception:  # noqa: BLE001
            rows = []
        _TEAMS[path] = rows
    return _TEAMS[path]


def url_for(name: str, sport: str = "soccer", abbr: str = "") -> str:
    """URL del escudo del equipo por su nombre (o sigla)."""
    key, ab = _plain(name), (abbr or "").upper()
    paths = ["basketball/nba"] if sport == "basketball" else [f"soccer/{lg}" for lg in SOCCER_LEAGUES]
    for path in paths:
        for t in _teams(path):
            names = {_plain(t.get(k, "")) for k in ("displayName", "shortDisplayName", "name", "location", "nickname")}
            if key in names or (ab and ab == (t.get("abbreviation") or "").upper() and sport == "basketball"):
                return _logo_url(t)
        for t in _teams(path):   # «Colo-Colo» vs «Colo Colo», «Real Madrid CF»…
            dn = _plain(t.get("displayName", ""))
            if key and dn and (key in dn or dn in key) and min(len(key), len(dn)) >= 5:
                return _logo_url(t)
    return ""


def image(url: str) -> bytes | None:
    """PNG del escudo (con transparencia)."""
    if not url:
        return None
    if url not in _IMG:
        try:
            r = requests.get(url, timeout=25)
            _IMG[url] = r.content if r.ok and len(r.content) > 500 else None
        except Exception:  # noqa: BLE001
            _IMG[url] = None
    return _IMG[url]


def get(name: str, sport: str = "soccer", abbr: str = "", url: str = "") -> bytes | None:
    return image(url or url_for(name, sport, abbr))


def fitted(png: bytes, size: int) -> Image.Image | None:
    """Escudo recortado a su contenido y escalado a size x size (sin deformar), con una sombra suave."""
    from PIL import ImageFilter
    try:
        im = Image.open(io.BytesIO(png)).convert("RGBA")
    except Exception:  # noqa: BLE001
        return None
    bb = im.getchannel("A").getbbox()
    if bb:
        im = im.crop(bb)
    im.thumbnail((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size + 24, size + 24), (0, 0, 0, 0))
    shadow = Image.new("RGBA", out.size, (0, 0, 0, 0))
    a = im.getchannel("A").point(lambda v: int(v * 0.55))
    blk = Image.new("RGBA", im.size, (0, 0, 0, 255))
    blk.putalpha(a)
    shadow.alpha_composite(blk, ((out.width - im.width) // 2, (out.height - im.height) // 2 + 6))
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))
    out.alpha_composite(shadow)
    out.alpha_composite(im, ((out.width - im.width) // 2, (out.height - im.height) // 2))
    return out
