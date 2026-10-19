"""Cliente mínimo de OddsPapi v4 (https://oddspapi.io/en/docs).

Pensado para el plan gratis: cada llamada cuenta 1 consulta, así que el escaneo diario
usa solo 2 (partidos + cuotas en bloque) y los mercados se guardan en caché.
"""
import json
import os
import time

import requests

from . import config

BASE = "https://api.oddspapi.io/v4"


class OddsPapiError(RuntimeError):
    pass


def _get(path: str, **params):
    if not config.ODDSPAPI_KEY:
        raise OddsPapiError("Falta ODDSPAPI_KEY")
    params["apiKey"] = config.ODDSPAPI_KEY
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE}{path}", params=params, timeout=40)
        except requests.RequestException as e:
            # El mensaje original incluye la URL con la clave: no se muestra.
            raise OddsPapiError(f"{path}: error de conexión ({type(e).__name__})") from None
        if r.status_code == 429 and "LIMIT" in r.text.upper():
            raise OddsPapiError("Se agotó la cuota mensual de OddsPapi")
        if r.status_code == 429:  # cooldown entre llamadas
            time.sleep(2.5)
            continue
        if r.status_code >= 400:
            raise OddsPapiError(f"{path} respondió {r.status_code}: {r.text[:200]}")
        return r.json()
    raise OddsPapiError(f"{path}: demasiados reintentos")


def account():
    """No consume cuota. Sirve para ver consultas usadas."""
    return _get("/account")


def markets(force: bool = False) -> dict:
    """Mapa marketId -> info del mercado. Se descarga una vez y queda en data/markets.json."""
    if not force and os.path.exists(config.MARKETS_CACHE):
        with open(config.MARKETS_CACHE, encoding="utf-8") as f:
            return json.load(f)
    raw = _get("/markets", language="es")
    out = {}
    for m in raw:
        if m.get("sportId") != 10:
            continue
        out[str(m["marketId"])] = {
            "name": m.get("marketName"),
            "type": m.get("marketType"),
            "period": m.get("period"),
            "handicap": m.get("handicap"),
            "playerProp": m.get("playerProp", False),
            "length": m.get("marketLength"),
            "outcomes": {str(o["outcomeId"]): o.get("outcomeName") for o in m.get("outcomes", [])},
        }
    os.makedirs(os.path.dirname(config.MARKETS_CACHE), exist_ok=True)
    with open(config.MARKETS_CACHE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out


def upcoming_fixtures(frm: str, to: str) -> list[dict]:
    """Partidos de fútbol con cuotas de Betano en la ventana (debe ser < 48 h)."""
    return _get("/fixtures", sportId=10, **{"from": frm, "to": to},
                statusId=0, hasOdds="true", bookmakers=config.BOOK)


def odds_by_tournaments(tournament_ids: list[int]) -> list[dict]:
    """Cuotas de Betano y Pinnacle para varios torneos: una consulta por casa (2 en total),
    combinadas por partido en el mismo formato de /odds (bookmakerOdds por casa)."""
    ids = ",".join(str(t) for t in tournament_ids)
    merged: dict[str, dict] = {}
    for slug in (config.BOOK, config.REFERENCE):
        time.sleep(2.1)  # cooldown entre llamadas
        data = _get("/odds-by-tournaments", tournamentIds=ids, bookmaker=slug)
        rows = data if isinstance(data, list) else data.get("data", [])
        for row in rows:
            fid = row.get("fixtureId")
            if not fid:
                continue
            target = merged.setdefault(fid, {"fixtureId": fid, "bookmakerOdds": {}})
            books = row.get("bookmakerOdds") or {}
            if slug in books:
                target["bookmakerOdds"][slug] = books[slug]
            elif books:  # por si la respuesta no viene indexada por casa
                target["bookmakerOdds"][slug] = next(iter(books.values()))
    print(f"Cuotas recibidas: {len(merged)} partidos "
          f"({sum(1 for r in merged.values() if len(r['bookmakerOdds']) == 2)} con ambas casas)")
    return list(merged.values())


def scores(fixture_id: str) -> dict:
    return _get("/scores", fixtureId=fixture_id)
