"""Contexto estadístico opcional desde API-Football (plan gratis: 100 consultas/día).

Si la API no responde o el plan no cubre la temporada, el pick sale igual, sin este contexto.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

import requests

from . import config

BASE = "https://v3.football.api-sports.io"
_budget = {"left": 40}  # tope propio por ejecución, para no gastar el plan diario


def _get(path: str, **params):
    if not config.APIFOOTBALL_KEY or _budget["left"] <= 0:
        return None
    _budget["left"] -= 1
    try:
        r = requests.get(f"{BASE}{path}", params=params, timeout=30,
                         headers={"x-apisports-key": config.APIFOOTBALL_KEY})
        data = r.json()
    except Exception:
        return None
    if data.get("errors"):
        return None
    return data.get("response")


def _norm(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    name = re.sub(r"\b(fc|cf|sc|ac|cd|club|de|the|afc|ca|sd|ud|rc)\b", " ", name)
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


_day_cache: dict[str, list] = {}


def find_fixture(home: str, away: str, date: str):
    if date not in _day_cache:
        _day_cache[date] = _get("/fixtures", date=date, timezone="UTC") or []
    best, score = None, 0.0
    for f in _day_cache[date]:
        s = (_sim(home, f["teams"]["home"]["name"]) + _sim(away, f["teams"]["away"]["name"])) / 2
        if s > score:
            best, score = f, s
    return best if score >= 0.72 else None


def _form(team_id: int) -> dict | None:
    games = _get("/fixtures", team=team_id, last=5)
    if not games:
        return None
    letters, gf, ga = [], 0, 0
    for g in games:
        home = g["teams"]["home"]["id"] == team_id
        mine = g["goals"]["home"] if home else g["goals"]["away"]
        theirs = g["goals"]["away"] if home else g["goals"]["home"]
        if mine is None or theirs is None:
            continue
        gf += mine
        ga += theirs
        letters.append("G" if mine > theirs else "E" if mine == theirs else "P")
    n = len(letters) or 1
    return {"form": "".join(letters), "gf": round(gf / n, 1), "ga": round(ga / n, 1)}


def context(home: str, away: str, kickoff_iso: str) -> dict | None:
    fx = find_fixture(home, away, kickoff_iso[:10])
    if not fx:
        return None
    h = _form(fx["teams"]["home"]["id"])
    a = _form(fx["teams"]["away"]["id"])
    if not h and not a:
        return None
    return {"home": h, "away": a}
