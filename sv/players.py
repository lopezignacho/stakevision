"""Jugadores referentes de un equipo (plantel actual) desde Wikidata, para elegir fotos relacionadas al partido.

- Equipo: búsqueda en Wikidata filtrada por deporte (fútbol Q2736 / básquetbol Q5372), sin equipos femeninos,
  juveniles ni filiales (salvo que el nombre buscado lo diga).
- Plantel: jugadores con «miembro de equipo deportivo» (P54) sin fecha de término, ordenados por cuántas
  Wikipedias tienen artículo sobre ellos (una medida simple de qué tan referente es).
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote

import requests

from .commons import UA

WD = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
SPORT_Q = {"soccer": "Q2736", "basketball": "Q5372"}
NOT_MAIN = ("women", "femenin", "feminin", "frauen", "youth", "juvenil", "under-", "u-1", "u-2", "u19", "u20", "u21",
            "u23", "reserve", "reserva", "filial", " b team", "academy", "g league", "esports", "futsal", "beach")
_cache: dict = {}


def _plain(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def team_qid(name: str, sport: str = "soccer") -> str | None:
    key = ("team", _plain(name), sport)
    if key in _cache:
        return _cache[key]
    want = SPORT_Q.get(sport, "Q2736")
    asked = _plain(name)
    qid = None
    try:
        hits = []
        for lang in ("es", "en"):
            r = requests.get(WD, params={"action": "wbsearchentities", "search": name, "language": lang,
                                         "uselang": "en", "type": "item", "limit": 8, "format": "json"},
                             headers=UA, timeout=20).json()
            hits += [h for h in r.get("search") or [] if h["id"] not in {x["id"] for x in hits}]
        if hits:
            ents = requests.get(WD, params={"action": "wbgetentities", "ids": "|".join(h["id"] for h in hits[:15]),
                                            "props": "claims|descriptions", "languages": "en", "format": "json"},
                                headers=UA, timeout=20).json().get("entities") or {}
            for h in hits:
                e = ents.get(h["id"]) or {}
                sports = {((c.get("mainsnak") or {}).get("datavalue") or {}).get("value", {}).get("id")
                          for c in (e.get("claims") or {}).get("P641") or []}
                if want not in sports:
                    continue
                desc = _plain(((e.get("descriptions") or {}).get("en") or {}).get("value") or "")
                label = _plain(h.get("label") or "")
                if any(w in f" {desc} {label} " for w in NOT_MAIN) and not any(w in asked for w in NOT_MAIN):
                    continue
                qid = h["id"]
                break
    except Exception:  # noqa: BLE001
        qid = None
    _cache[key] = qid
    return qid


def squad(team: str, sport: str = "soccer", n: int = 8) -> list[dict]:
    """Referentes del plantel actual: [{'name', 'image', 'links', 'since' (año en que llegó)}], el más conocido primero.
    Se descartan los que después pasaron a otro club (datos viejos) y los mayores de 40 años."""
    key = ("squad", _plain(team), sport, n)
    if key in _cache:
        return _cache[key]
    qid = team_qid(team, sport)
    out: list[dict] = []
    if qid:
        q = f"""
        SELECT ?p ?pLabel ?img ?links (YEAR(?start) AS ?sy) WHERE {{
          ?p p:P54 ?st . ?st ps:P54 wd:{qid} .
          FILTER NOT EXISTS {{ ?st pq:P582 ?end }}
          ?st pq:P580 ?start .
          FILTER(YEAR(?start) >= YEAR(NOW()) - 10)
          ?p wdt:P31 wd:Q5 .
          FILTER NOT EXISTS {{ ?p wdt:P570 ?death }}
          OPTIONAL {{ ?p wdt:P569 ?birth }}
          FILTER(!BOUND(?birth) || YEAR(?birth) >= YEAR(NOW()) - 40)
          FILTER NOT EXISTS {{
            ?p p:P54 ?st2 . ?st2 ps:P54 ?t2 ; pq:P580 ?s2 .
            FILTER(?t2 != wd:{qid} && ?s2 > ?start)
            ?t2 rdfs:label ?l2 . FILTER(LANG(?l2) = "en")
            FILTER(!CONTAINS(LCASE(?l2), "national") && !CONTAINS(LCASE(?l2), "olympic"))
          }}
          OPTIONAL {{ ?p wdt:P18 ?img }}
          ?p wikibase:sitelinks ?links .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es,en". }}
        }} ORDER BY DESC(?links) LIMIT {n * 2}"""
        try:
            rows = requests.get(SPARQL, params={"query": q, "format": "json"}, headers=UA,
                                timeout=40).json()["results"]["bindings"]
        except Exception:  # noqa: BLE001
            rows = []
        seen = set()
        for r in rows:
            name = r.get("pLabel", {}).get("value", "")
            if not name or re.fullmatch(r"Q\d+", name) or name in seen:
                continue
            seen.add(name)
            img = r.get("img", {}).get("value", "")
            out.append({"name": name, "image": unquote(img.rsplit("/", 1)[-1]) if img else "",
                        "links": int(r.get("links", {}).get("value", 0)),
                        "since": int(r.get("sy", {}).get("value", 0) or 0)})
        out = out[:n]
    _cache[key] = out
    return out
