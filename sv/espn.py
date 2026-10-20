"""Marcador en vivo desde ESPN (público, sin clave). Solo para mostrar contexto."""
from __future__ import annotations

import re
import unicodedata
from zoneinfo import ZoneInfo

import requests

from . import store

STOP = {"club", "calcio", "futbol", "football", "the", "and", "old", "boys", "city", "united", "real",
        "sporting", "atletico", "deportivo"}


def _toks(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    words = [w for w in re.split(r"[^a-z0-9]+", s) if len(w) >= 3]
    key = [w for w in words if w not in STOP]
    return key or words


def _match(name: str, team: dict) -> bool:
    a = set(_toks(name))
    b = set(_toks(" ".join(str(team.get(k) or "") for k in ("displayName", "shortDisplayName", "name", "location"))))
    return bool(a & b)


def live_info(home: str, away: str, kickoff_iso: str, sport: str = "soccer") -> dict | None:
    """{'score': '1-0', 'clock': "45'", 'state': 'in'|'pre'|'post'} o None."""
    day = store.parse_ts(kickoff_iso).astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d")
    try:
        data = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/{sport}/all/scoreboard",
                            params={"dates": day}, timeout=20).json()
    except Exception:  # noqa: BLE001
        return None
    for e in data.get("events") or []:
        c = (e.get("competitions") or [{}])[0]
        comp = c.get("competitors") or []
        h = next((x for x in comp if x.get("homeAway") == "home"), None)
        a = next((x for x in comp if x.get("homeAway") == "away"), None)
        if not h or not a:
            continue
        if _match(home, h["team"]) and _match(away, a["team"]):
            st = e.get("status") or {}
            return {"score": f"{h.get('score', '0')}-{a.get('score', '0')}",
                    "clock": (st.get("type") or {}).get("shortDetail") or st.get("displayClock") or "",
                    "state": (st.get("type") or {}).get("state") or ""}
    return None
