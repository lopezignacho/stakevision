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


SKIP = ("logo", "escudo", "crest", "badge", "emblem", "kit", "shirt", "camiseta", "map", "mapa", "flag", "bandera",
        "radio", "interview", "entrevista", "press", "prensa", "rueda", "conferencia", "conference", "presentacion",
        "store", "tienda", "museum", "museo", "bus", "signature", "firma", "office", "oficina", "studio")
GOOD = ("match", "partido", "vs", " v ", "players", "jugadores", "team", "equipo", "plantel", "celebr", "goal",
        "gol", "stadium", "estadio", "fans", "hinchas", "afici", "torcida", "derby", "clasico", "training", "entreno")


def candidates(name: str, limit: int = 30, team: bool = False) -> list[dict]:
    """Fotos de Commons que nombran al jugador (o al equipo), con licencia apta, de la más reciente a la más antigua."""
    if not name.strip():
        return []
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
              "gsrsearch": f'"{name}" filetype:bitmap', "gsrlimit": limit,
              "prop": "imageinfo", "iiprop": "url|extmetadata|size", "iiurlwidth": 1400}
    try:
        pages = (requests.get(API, params=params, headers=UA, timeout=25).json().get("query") or {}).get("pages") or {}
    except Exception:  # noqa: BLE001
        return []
    surname = _plain(name) if team else _plain(name.split()[-1])
    out = []
    for p in pages.values():
        title = p.get("title") or ""
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value") or ""
        if surname not in _plain(title) or not LICENSE_OK.match(lic):
            continue
        if team and any(w in _plain(title) for w in SKIP):
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
                    "cropped": "(cropped)" in title.lower(),
                    "good": team and any(w in f" {_plain(title)} " for w in GOOD)})
    # Preferir: (equipos) fotos de partido/hinchada; reciente; el jugador como protagonista; vertical y recortada
    out.sort(key=lambda c: (c["good"], c["year"], c["first"], c["portrait"], c["cropped"]), reverse=True)
    return out


def photo(name: str, team: bool = False) -> tuple[bytes, dict] | None:
    """(jpeg, crédito) de la mejor foto libre del jugador (o del equipo), o None."""
    for c in candidates(name, team=team)[:3]:
        try:
            r = requests.get(c["url"], headers=UA, timeout=40)
            if r.ok and len(r.content) > 20000:
                credit = {"author": c["author"], "license": c["license"], "page": c["page"],
                          "text": f"Foto: {c['author']} / Wikimedia Commons · {c['license']} · modificada"}
                return r.content, credit
        except Exception:  # noqa: BLE001
            continue
    return None


# ---------------------------------------------------------------- jugadores referentes, con la camiseta del club
BAD = ("ticket", "entrada", "poster", "afiche", "cartel", "card", "cromo", "stamp", "sello", "autograph", "autografo",
       "signature", "firma", "statue", "estatua", "mural", "grave", "tumba", "house", "casa ", "wedding", "boda",
       "logo", "escudo", "crest", "kit", "jersey", "shirt", "camiseta", "museum", "museo", "wax", "cera", "painting",
       "drawing", "dibujo", "cartoon", "programme", "program", "magazine", "revista", "newspaper", "trophy cabinet")
_BAD_RE = re.compile(r"\b(" + "|".join(re.escape(b.strip()) for b in BAD) + r")s?\b")


def _team_tokens(teams: list[str]) -> set[str]:
    stop = {"club", "the", "fc", "cf", "sc", "ac", "de", "del", "la", "los", "las", "city", "united", "real",
            "sporting", "deportivo", "atletico", "athletic", "football", "futbol", "calcio", "basketball", "angeles",
            "new", "san", "santa"}
    out = set()
    for t in teams:
        for w in re.split(r"[^a-z0-9]+", _plain(t)):
            if len(w) >= 3 and w not in stop:
                out.add(w)
    return out


def player_candidates(name: str, teams: list[str], min_year: int | None = None) -> list[dict]:
    """Fotos del jugador: primero las que nombran a su club (lo muestran con esa camiseta), luego recientes."""
    from datetime import date
    this_year = date.today().year
    min_year = min_year or this_year - 3
    toks = _team_tokens(teams)
    out = []
    for c in candidates(name, limit=40):
        t = f" {_plain(c['title'])} "
        if _BAD_RE.search(t):
            continue
        words = set(re.split(r"[^a-z0-9]+", t))
        hit = bool(toks & words)
        if c["year"] and c["year"] < (this_year - 6 if hit else min_year):
            continue    # muy antigua: puede ser de otro club o de otra época
        if not hit and not c["year"]:
            continue    # sin fecha ni club: no sabemos con qué camiseta sale
        c["team_hit"] = hit
        out.append(c)
    out.sort(key=lambda c: (c["team_hit"], c["year"], c["first"], c["portrait"], c["cropped"]), reverse=True)
    return out


def _download(c: dict) -> tuple[bytes, dict] | None:
    try:
        r = requests.get(c["url"], headers=UA, timeout=40)
        if r.ok and len(r.content) > 20000:
            return r.content, {"author": c["author"], "license": c["license"], "page": c["page"],
                               "text": f"Foto: {c['author']} / Wikimedia Commons · {c['license']} · modificada"}
    except Exception:  # noqa: BLE001
        pass
    return None


def player_photo(name: str, teams: list[str]) -> tuple[bytes, dict] | None:
    """(jpeg, crédito) del jugador, idealmente con la camiseta de su club; o None."""
    for c in player_candidates(name, teams)[:3]:
        got = _download(c)
        if got:
            got[1]["player"] = name
            got[1]["team_hit"] = c["team_hit"]
            return got
    return None


def file_photo(filename: str) -> tuple[bytes, dict] | None:
    """Una foto concreta de Commons (por ejemplo la imagen principal del jugador en Wikidata), si la licencia sirve."""
    title = filename if filename.lower().startswith("file:") else f"File:{filename}"
    params = {"action": "query", "format": "json", "titles": title, "prop": "imageinfo",
              "iiprop": "url|extmetadata|size", "iiurlwidth": 1400}
    try:
        pages = (requests.get(API, params=params, headers=UA, timeout=25).json().get("query") or {}).get("pages") or {}
    except Exception:  # noqa: BLE001
        return None
    for p in pages.values():
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value") or ""
        if not LICENSE_OK.match(lic) or min(info.get("width") or 0, info.get("height") or 0) < 600:
            return None
        author = _clean((meta.get("Artist") or {}).get("value") or "") or "Autor desconocido"
        return _download({"url": info.get("thumburl") or info.get("url"), "author": author[:60], "license": lic,
                          "page": info.get("descriptionurl")})
    return None
