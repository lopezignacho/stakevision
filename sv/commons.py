"""Fotos de jugadores con licencia libre desde Wikimedia Commons.

Solo se aceptan licencias que permiten uso comercial (CC0, CC BY, CC BY-SA, dominio público).
Cada foto viene con su crédito, que se imprime en la imagen y va en el texto de Instagram.
"""
from __future__ import annotations

import re
import unicodedata

import requests

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "StakevisionBot/1.0 (https://lopezignacho.github.io/stakevision)"}
LICENSE_OK = re.compile(r"^(CC0|CC BY(-SA)? [\d.]+|Public domain)", re.I)


def _plain(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _clean(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


def candidates(name: str, limit: int = 30) -> list[dict]:
    """Fotos de Commons que nombran al jugador, con licencia apta, de la más reciente a la más antigua."""
    if not name.strip():
        return []
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
              "gsrsearch": f'"{name}" filetype:bitmap', "gsrlimit": limit,
              "prop": "imageinfo", "iiprop": "url|extmetadata|size", "iiurlwidth": 1400}
    try:
        pages = (requests.get(API, params=params, headers=UA, timeout=25).json().get("query") or {}).get("pages") or {}
    except Exception:  # noqa: BLE001
        return []
    surname = _plain(name.split()[-1])
    out = []
    for p in pages.values():
        title = p.get("title") or ""
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value") or ""
        if surname not in _plain(title) or not LICENSE_OK.match(lic):
            continue
        if not title.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        w, h = info.get("width") or 0, info.get("height") or 0
        if min(w, h) < 700:
            continue
        date = (meta.get("DateTimeOriginal") or {}).get("value") or (meta.get("DateTime") or {}).get("value") or ""
        year = int(m.group()) if (m := re.search(r"(19|20)\d\d", date)) else 0
        author = _clean((meta.get("Artist") or {}).get("value") or "") or "Autor desconocido"
        out.append({"title": title, "url": info.get("thumburl") or info.get("url"), "page": info.get("descriptionurl"),
                    "license": lic, "author": author[:60], "year": year, "portrait": h >= w,
                    "first": _plain(title).removeprefix("file:").startswith(_plain(name)),
                    "cropped": "(cropped)" in title.lower()})
    # Preferir: reciente, con el jugador como protagonista (su nombre primero), vertical y recortada
    out.sort(key=lambda c: (c["year"], c["first"], c["portrait"], c["cropped"]), reverse=True)
    return out


def photo(name: str) -> tuple[bytes, dict] | None:
    """(jpeg, crédito) de la mejor foto libre del jugador, o None."""
    for c in candidates(name)[:3]:
        try:
            r = requests.get(c["url"], headers=UA, timeout=40)
            if r.ok and len(r.content) > 20000:
                credit = {"author": c["author"], "license": c["license"], "page": c["page"],
                          "text": f"Foto: {c['author']} / Wikimedia Commons · {c['license']} · modificada"}
                return r.content, credit
        except Exception:  # noqa: BLE001
            continue
    return None
