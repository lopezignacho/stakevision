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


def quota_text() -> str:
    """Resume solo los números de uso del plan (nunca la clave)."""
    found = {}

    def walk(d, prefix=""):
        if isinstance(d, dict):
            for k, v in d.items():
                if "key" in k.lower():
                    continue
                if isinstance(v, (dict, list)):
                    walk(v, f"{prefix}{k}.")
                elif any(w in k.lower() for w in ("limit", "count", "request", "reset")):
                    found[prefix + k] = v
        elif isinstance(d, list):
            for i, x in enumerate(d[:3]):
                walk(x, f"{prefix}{i}.")
    try:
        walk(account())
    except Exception as e:
        return f"No se pudo leer la cuenta: {type(e).__name__}"
    return ", ".join(f"{k}={v}" for k, v in found.items()) or "sin datos de uso"


def markets(force: bool = False, sport_id: int = 10) -> dict:
    """Mapa marketId -> info del mercado. Se descarga una vez y queda en caché (fútbol: data/markets.json)."""
    cache = config.MARKETS_CACHE if sport_id == 10 else os.path.join(config.ROOT, "data", "markets_basketball.json")
    if not force and os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            return json.load(f)
    raw = _get("/markets", language="es")
    out = {}
    for m in raw:
        if m.get("sportId") != sport_id:
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
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out


def tournaments() -> list[dict]:
    """Lista de torneos de fútbol (se guarda en data/tournaments.json)."""
    raw = _get("/tournaments", sportId=10)
    out = [{"id": t["tournamentId"], "category": t.get("categoryName"), "name": t.get("tournamentName"),
            "upcoming": t.get("upcomingFixtures", 0), "future": t.get("futureFixtures", 0)} for t in raw]
    path = os.path.join(config.ROOT, "data", "tournaments.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(out, key=lambda t: (t["category"] or "", t["name"] or "")), f, ensure_ascii=False, indent=0)
    return out


def upcoming_fixtures(frm: str, to: str, sport_id: int = 10) -> list[dict]:
    """Partidos con cuotas de Betano en la ventana (debe ser < 48 h). Fútbol = 10, básquetbol = 11."""
    return _get("/fixtures", sportId=sport_id, **{"from": frm, "to": to},
                statusId=0, hasOdds="true", bookmakers=config.BOOK)


def live_fixtures(frm: str, to: str, sport_id: int = 10) -> list[dict]:
    """Partidos que se están jugando (statusId=1) con cuotas de Betano."""
    return _get("/fixtures", sportId=sport_id, **{"from": frm, "to": to},
                statusId=1, hasOdds="true", bookmakers=config.BOOK)


def odds_by_tournaments(tournament_ids: list[int]) -> list[dict]:
    """Cuotas de Betano y Pinnacle. OddsPapi acepta 1 casa y hasta 5 ligas por consulta,
    así que se pide por grupos y se combinan por partido (bookmakerOdds por casa)."""
    merged: dict[str, dict] = {}
    step = config.MAX_TOURNAMENTS_PER_CALL
    for i in range(0, len(tournament_ids), step):
        ids = ",".join(str(t) for t in tournament_ids[i:i + step])
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
                elif books:
                    target["bookmakerOdds"][slug] = next(iter(books.values()))
    print(f"Cuotas recibidas: {len(merged)} partidos "
          f"({sum(1 for r in merged.values() if len(r['bookmakerOdds']) == 2)} con ambas casas)")
    return list(merged.values())


def scores(fixture_id: str) -> dict:
    return _get("/scores", fixtureId=fixture_id)
