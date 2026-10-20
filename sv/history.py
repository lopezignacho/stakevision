"""Historial propio de resultados (API-Football, plan gratis).

El plan gratis no deja pedir "los últimos partidos de un equipo", pero sí "todos los
partidos de un día". Así que guardamos cada día terminado (1 consulta por día) y con
eso calculamos la forma de cualquier equipo sin gastar más consultas.
Archivo: data/history/AAAA-MM.json.gz  ->  {"AAAA-MM-DD": [[liga, local_id, local, visita_id, visita, gl, gv], ...]}
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import timedelta

from . import apifootball, config, store

DIR = os.path.join(config.ROOT, "data", "history")
DAYS_BACK = 60          # cuánta historia mantenemos
_cache: dict[str, dict] = {}


def _path(month: str) -> str:
    return os.path.join(DIR, f"{month}.json.gz")


def _load(month: str) -> dict:
    if month not in _cache:
        p = _path(month)
        if os.path.exists(p):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                _cache[month] = json.load(f)
        else:
            _cache[month] = {}
    return _cache[month]


def _save(month: str) -> None:
    os.makedirs(DIR, exist_ok=True)
    with gzip.open(_path(month), "wt", encoding="utf-8") as f:
        json.dump(_cache[month], f, ensure_ascii=False, separators=(",", ":"))


def missing_days(days_back: int = DAYS_BACK) -> list[str]:
    today = store.now_utc().date()
    out = []
    for k in range(1, days_back + 1):
        d = (today - timedelta(days=k)).isoformat()
        if d not in _load(d[:7]):
            out.append(d)
    return out


def update(max_fetch: int = 1) -> int:
    """Descarga hasta `max_fetch` días que falten (los más recientes primero)."""
    done = 0
    for d in missing_days()[:max_fetch]:
        games = apifootball._get("/fixtures", date=d, timezone="UTC")
        if games is None:
            break   # sin cupo o la API falló: se reintenta en otra ejecución
        rows = []
        for g in games:
            if (g.get("fixture", {}).get("status", {}).get("short")) not in ("FT", "AET", "PEN"):
                continue
            ft = (g.get("score") or {}).get("fulltime") or {}
            hg, ag = ft.get("home"), ft.get("away")
            if hg is None or ag is None:
                hg, ag = g["goals"]["home"], g["goals"]["away"]
            if hg is None or ag is None:
                continue
            rows.append([g["league"]["id"], g["teams"]["home"]["id"], g["teams"]["home"]["name"],
                         g["teams"]["away"]["id"], g["teams"]["away"]["name"], hg, ag])
        _load(d[:7])[d] = rows
        _save(d[:7])
        done += 1
    return done


def team_matches(team_id: int, before: str, n: int = 10) -> list[dict]:
    """Últimos `n` partidos del equipo antes de la fecha `before` (AAAA-MM-DD), del más reciente al más antiguo."""
    out = []
    day = store.parse_ts(before[:10] + "T00:00:00Z").date()
    for k in range(1, DAYS_BACK + 1):
        d = (day - timedelta(days=k)).isoformat()
        for r in _load(d[:7]).get(d, []):
            if r[1] == team_id:
                out.append({"date": d, "venue": "L", "gf": r[5], "ga": r[6], "rival": r[4]})
            elif r[3] == team_id:
                out.append({"date": d, "venue": "V", "gf": r[6], "ga": r[5], "rival": r[2]})
        if len(out) >= n:
            break
    return out[:n]
