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


def candidates(name: str, limit: int = 30, team: bool = False, query: str | None = None) -> list[dict]:
    """Fotos de Commons que nombran al jugador (o al equipo), con licencia apta, de la más reciente a la más antigua."""
    if not name.strip():
        return []
    from . import config
    min_year = getattr(config, "PHOTO_MIN_YEAR", 0)
    rows = _candidates(name, limit, team, query)
    if min_year:   # primero buscar directo fotos de este año (la búsqueda general trae muchas antiguas)
        seen = {c["title"] for c in rows}
        rows += [c for c in _candidates(name, limit, team, (query or f'"{name}" filetype:bitmap') + f" {min_year}")
                 if c["title"] not in seen]
        rows = [c for c in rows if c["year"] >= min_year]
    rows.sort(key=lambda c: (c["good"], c["year"], c["first"], c["portrait"], c["cropped"]), reverse=True)
    return rows


def _candidates(name: str, limit: int, team: bool, query: str | None) -> list[dict]:
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
              "gsrsearch": query or f'"{name}" filetype:bitmap', "gsrlimit": limit,
              "prop": "imageinfo|categories", "iiprop": "url|extmetadata|size", "iiurlwidth": 1400,
              "clshow": "!hidden", "cllimit": "max"}
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
        date = (meta.get("DateTimeOriginal") or {}).get("value") or ""   # fecha en que se TOMÓ la foto (no la de subida)
        year = int(m.group()) if (m := re.search(r"(19|20)\d\d", date)) else 0
        author = _clean((meta.get("Artist") or {}).get("value") or "") or "Autor desconocido"
        out.append({"title": title, "url": info.get("thumburl") or info.get("url"), "page": info.get("descriptionurl"),
                    "license": lic, "author": author[:60], "year": year, "portrait": h >= w,
                    "first": _plain(title).removeprefix("file:").startswith(_plain(name)),
                    "cropped": "(cropped)" in title.lower(),
                    "good": team and any(w in f" {_plain(title)} " for w in GOOD),
                    "cats": " | ".join(_plain(c.get("title", "")) for c in p.get("categories") or []),
                    "desc": _plain(_clean((meta.get("ImageDescription") or {}).get("value") or ""))[:400]})
    # Preferir: (equipos) fotos de partido/hinchada; reciente; el jugador como protagonista; vertical y recortada
    out.sort(key=lambda c: (c["good"], c["year"], c["first"], c["portrait"], c["cropped"]), reverse=True)
    return out


def photo(name: str, team: bool = False, sport: str = "soccer") -> tuple[bytes, dict] | None:
    """(jpeg, crédito) de la mejor foto libre del jugador (o del equipo), o None."""
    for c in [c for c in candidates(name, team=team) if sport_ok(c, sport, need_word=team)][:3]:
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
       "drawing", "dibujo", "cartoon", "programme", "program", "magazine", "revista", "newspaper", "trophy cabinet",
       "parade", "desfile", "rally", "ceremony", "ceremonia", "white house", "visit", "visita", "gala", "award",
       "premio", "premiere", "concert", "red carpet", "meeting", "reunion", "school", "colegio", "hospital")
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


NATIONAL = ("national", "seleccion", "selección", "world cup", "copa mundial", "mundial", "copa america", "eurocopa",
            "euro 20", "qualif", "eliminatoria", "friendly", "amistoso", "olympic", "olimpic", "fiba", "nations league",
            "argentina", "brazil", "brasil", "chile", "uruguay", "colombia", "ecuador", "peru", "paraguay", "bolivia",
            "venezuela", "mexico", "usa", "france", "francia", "spain", "espana", "portugal", "england", "inglaterra",
            "germany", "alemania", "italy", "italia", "netherlands", "belgium", "croatia", "serbia", "slovenia",
            "canada", "japan", "cote", "ivoire", "morocco", "senegal", "nigeria", "cameroon", "ghana", "australia")


def player_candidates(name: str, teams: list[str], since: int = 0, sport: str = "soccer", years: int = 3) -> list[dict]:
    """Fotos del jugador con la camiseta de SU club: que el club aparezca en el título, la descripción o
    las categorías, que sea de cuando ya jugaba ahí y que no sea con su selección."""
    from datetime import date
    this_year = date.today().year
    since = max(since or 0, this_year - years)   # reciente: así no aparece alguien que ya se fue del club
    toks = _team_tokens(teams)
    pool: dict[str, dict] = {}
    nick = sorted(toks, key=len, reverse=True)[0] if toks else ""
    for q in ([f'"{name}" {nick} filetype:bitmap'] if nick else []) + [None]:
        for c in candidates(name, limit=40, query=q):
            pool.setdefault(c["title"], c)
    out = []
    for c in pool.values():
        title = f" {_plain(c['title'])} "
        if _BAD_RE.search(title) or c["author"] in ("Autor desconocido", "") or "unknown author" in _plain(c["author"]):
            continue
        words_t = set(re.split(r"[^a-z0-9]+", title))
        words_all = set(re.split(r"[^a-z0-9]+", f"{title} {c['desc']} {c['cats']}"))
        if any((n in words_t) if " " not in n else (n in title) for n in NATIONAL) and not (toks & words_t):
            continue   # con la selección
        blob = f" {title} {c['desc']} {c['cats']} "
        c["national"] = (any(w in blob for w in ("national", "selección", "seleccion", "world cup", "olympic",
                                                 "eurobasket", "fiba", "copa america", "copa américa", "team usa",
                                                 "usa basketball", "nations league", "mundial"))
)   # los países sueltos no: «Santiago, Chile» o «San Francisco, USA» son el lugar, no la camiseta
        if not c["year"] or c["year"] < since:
            continue   # de antes de llegar al club: puede tener otra camiseta
        if not sport_ok(c, sport):
            continue   # otro deporte, o un equipo femenino/juvenil del mismo club
        c["team_hit"] = bool(toks & words_t) or bool(toks & words_all)
        c["title_hit"] = bool(toks & words_t)
        out.append(c)
    out.sort(key=lambda c: (c["title_hit"], not c["national"], c["team_hit"], c["year"], c["first"], c["portrait"]), reverse=True)
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


JERSEY_LOG: list = []   # qué se revisó (para las pruebas y para entender por qué no hubo foto)


def jersey_ok(photo: bytes, name: str, teams: list[str], sport: str, c: dict | None = None) -> bool:
    """Revisión visual (Gemini) de la camiseta: tiene que ser la del equipo del partido. Sin Gemini, solo se
    acepta si el título de la foto nombra al club y no hay rastro de selección."""
    from . import llm
    team = (teams or [""])[0]
    if not team:
        return False
    if llm.enabled():
        try:
            r = llm.check_jersey(photo, name, team, sport)
            JERSEY_LOG.append({"player": name, "team": team, "title": (c or {}).get("title"), **r})
            return r["ok"]
        except Exception as e:  # noqa: BLE001
            JERSEY_LOG.append({"player": name, "team": team, "title": (c or {}).get("title"), "error": str(e)[:120]})
    return bool(c and c.get("title_hit") and not c.get("national"))


def player_photo(name: str, teams: list[str], since: int = 0, need_team: bool = True,
                 sport: str = "soccer", years: int = 3) -> tuple[bytes, dict] | None:
    """(jpeg, crédito) del jugador con la camiseta de su club; o None.
    years: antigüedad máxima de la foto (más años solo si la foto nombra al club actual: need_team)."""
    for c in player_candidates(name, teams, since, sport, years if need_team else 3)[:6]:
        if need_team and not c["team_hit"]:
            continue
        if c.get("national") and not c.get("title_hit"):
            continue   # con la selección (aunque la categoría nombre al club): camiseta equivocada
        got = _download(c)
        if got and not jersey_ok(got[0], name, teams, sport, c):
            continue
        if got:
            got[1]["player"] = name
            got[1]["team_hit"] = c["team_hit"]
            return got
    return None


# ---------------------------------------------------------------- deporte correcto (nunca una foto de otro deporte)
OTHER_SPORTS = {
    "soccer": ("basketball", "baloncesto", "basquetbol", "basquet", "basket", "volleyball", "voleibol", "volley",
               "handball", "balonmano", "futsal", "futbol sala", "rugby", "hockey", "tennis", "tenis", "waterpolo",
               "water polo", "baseball", "beisbol", "esports", "e-sports", "boxing", "boxeo", "athletics", "atletismo",
               "swimming", "natacion", "cycling", "ciclismo", "nba", "fiba", "liga nacional de basquetbol"),
    "basketball": ("football", "futbol", "soccer", "fussball", "calcio", "volleyball", "voleibol", "handball",
                   "rugby", "hockey", "tennis", "baseball", "wnba"),
}
# Nuestros picks son de competencias masculinas: fotos de equipos femeninos o juveniles, no.
NOT_MEN = ("women", "woman", "womens", "femenin", "femenil", "feminin", "ladies", "mujeres", "girls", "u17", "u-17",
           "u19", "u-19", "u20", "u-20", "u21", "u-21", "u23", "sub 17", "sub-17", "sub 20", "sub-20", "sub 21",
           "sub-21", "youth", "juvenil", "juveniles", "academy", "academia", "cadete")
SPORT_WORDS = {"soccer": ("football", "futbol", "soccer", "fussball", "calcio", "futebol", "voetbal"),
               "basketball": ("basketball", "baloncesto", "basquetbol", "nba")}


def _blob(c: dict) -> str:
    return f" {_plain(c.get('title', ''))} {c.get('desc', '')} {c.get('cats', '')} "


def sport_ok(c: dict, sport: str | None, need_word: bool = False) -> bool:
    """¿La foto es del deporte del pick (y no de un equipo femenino o juvenil)? need_word: además debe
    nombrar el deporte (para fotos de club, donde el nombre del club solo no basta: la U tiene básquetbol)."""
    if not sport:
        return True
    blob = _blob(c)
    words = set(re.split(r"[^a-z0-9]+", blob))
    def has(term):
        return (term in words) if " " not in term and "-" not in term else (term in blob)
    if any(has(w) or (len(w) > 5 and w in blob) for w in OTHER_SPORTS.get(sport, ())):
        return False
    if any(has(w) or (len(w) > 5 and w in blob) for w in NOT_MEN):
        return False
    if need_word and not any(w in blob for w in SPORT_WORDS.get(sport, ())):
        return False
    return True


def team_photo(team: str, sport: str = "soccer") -> tuple[bytes, dict] | None:
    """Foto reciente de un partido, el estadio o la hinchada del club (nunca entradas, afiches ni escudos)."""
    from datetime import date
    this_year = date.today().year
    for c in candidates(team, limit=40, team=True):
        t = f" {_plain(c['title'])} "
        if _BAD_RE.search(t) or not c["year"] or c["year"] < this_year - 4 or "unknown author" in _plain(c["author"]):
            continue
        if not sport_ok(c, sport, need_word=True):
            continue   # p. ej. «Universidad de Chile» también es básquetbol y fútbol femenino
        got = _download(c)
        if got:
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
