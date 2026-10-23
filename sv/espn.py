"""Marcador en vivo y resumen post partido desde ESPN (público, sin clave)."""
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


def _scoreboard(day: str, sport: str) -> list[dict]:
    try:
        return requests.get(f"https://site.api.espn.com/apis/site/v2/sports/{sport}/all/scoreboard",
                            params={"dates": day}, timeout=20).json().get("events") or []
    except Exception:  # noqa: BLE001
        return []


def _find(home: str, away: str, kickoff_iso: str, sport: str = "soccer"):
    """Busca el partido en el marcador de ESPN. Devuelve (evento, competición, local, visita) o None."""
    day = store.parse_ts(kickoff_iso).astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d")
    for e in _scoreboard(day, sport):
        c = (e.get("competitions") or [{}])[0]
        comp = c.get("competitors") or []
        h = next((x for x in comp if x.get("homeAway") == "home"), None)
        a = next((x for x in comp if x.get("homeAway") == "away"), None)
        if h and a and _match(home, h["team"]) and _match(away, a["team"]):
            return e, c, h, a
    return None


def live_info(home: str, away: str, kickoff_iso: str, sport: str = "soccer") -> dict | None:
    """{'score': '1-0', 'clock': "45'", 'state': 'in'|'pre'|'post'} o None."""
    found = _find(home, away, kickoff_iso, sport)
    if not found:
        return None
    e, _c, h, a = found
    st = e.get("status") or {}
    return {"score": f"{h.get('score', '0')}-{a.get('score', '0')}",
            "clock": (st.get("type") or {}).get("shortDetail") or st.get("displayClock") or "",
            "state": (st.get("type") or {}).get("state") or ""}


def _rgb(hexcolor: str | None, default: tuple) -> tuple:
    try:
        h = (hexcolor or "").strip().lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else default
    except ValueError:
        return default


def _minute(clock: dict) -> tuple[int, str]:
    """(minuto para la línea de tiempo, texto como lo muestra ESPN: 4', 90'+3')."""
    shown = (clock or {}).get("displayValue") or ""
    nums = [int(x) for x in re.findall(r"\d+", shown)]
    if nums:
        return sum(nums), shown
    secs = (clock or {}).get("value") or 0
    m = int(secs // 60) + 1
    return m, f"{m}'"


def _side(t: dict, x: dict, agg: dict) -> dict:
    team = x.get("team") or {}
    return {"id": str(team.get("id") or ""), "name": team.get("displayName") or "",
            "short": (team.get("shortDisplayName") or team.get("displayName") or "").strip(),
            "abbr": (team.get("abbreviation") or "")[:4].upper(),
            "color": _rgb(team.get("color"), (40, 44, 50)), "alt": _rgb(team.get("alternateColor"), (240, 240, 240)),
            "score": _int(x.get("score")) or 0, "winner": bool(x.get("winner")),
            "agg": _int(x.get("aggregateScore", agg.get(str(team.get("id"))))),
            "stats": {s.get("name"): s.get("displayValue") for s in x.get("statistics") or [] if s.get("name")}, **t}


def _int(v):
    try:
        return None if v is None else int(float(v))
    except (TypeError, ValueError):
        return None


def report_from_event(e: dict, c: dict, h: dict, a: dict) -> dict:
    """Resumen del partido terminado a partir del evento del marcador de ESPN."""
    series = c.get("series") or {}
    agg = {str(s.get("id")): s.get("aggregateScore") for s in series.get("competitors") or []}
    home, away = _side({"side": "home"}, h, agg), _side({"side": "away"}, a, agg)
    goals, reds = [], []
    for d in c.get("details") or []:
        if d.get("redCard"):
            who = (d.get("athletesInvolved") or [{}])[0]
            tid = str((d.get("team") or {}).get("id") or "")
            reds.append({"label": _minute(d.get("clock") or {})[1], "side": "home" if tid == home["id"] else "away",
                         "player": who.get("shortName") or who.get("displayName") or ""})
        if not d.get("scoringPlay") or d.get("shootout"):
            continue
        who = (d.get("athletesInvolved") or [{}])[0]
        tid = str((d.get("team") or {}).get("id") or "")
        minute, label = _minute(d.get("clock") or {})
        kind = ("own" if d.get("ownGoal") else "penalty" if d.get("penaltyKick")
                else "header" if "header" in ((d.get("type") or {}).get("text") or "").lower() else "")
        goals.append({"min": minute, "label": label, "kind": kind,
                      "side": "home" if tid == home["id"] else "away",
                      "player": who.get("shortName") or who.get("displayName") or "",
                      "full": who.get("fullName") or who.get("displayName") or ""})
    goals.sort(key=lambda g: g["min"])
    leg = (c.get("leg") or {}).get("value")
    st = e.get("status") or {}
    return {"id": e.get("id"), "home": home, "away": away, "goals": goals, "reds": reds,
            "state": (st.get("type") or {}).get("state") or "",
            "status_name": (st.get("type") or {}).get("name") or "", "period": st.get("period") or 0,
            "clock": st.get("displayClock") or "",
            "series": ({"title": series.get("title") or "", "leg": leg, "done": bool(series.get("completed"))}
                       if series else None),
            "stage": ((e.get("season") or {}).get("slug") or ""),
            "venue": ((c.get("venue") or {}).get("fullName") or "")}


def match_report(home: str, away: str, kickoff_iso: str, sport: str = "soccer") -> dict | None:
    """Datos para la imagen post partido (solo si ESPN lo da por terminado)."""
    found = _find(home, away, kickoff_iso, sport)
    if not found:
        return None
    r = report_from_event(*found)
    return r if r["state"] == "post" else None


def live_report(home: str, away: str, kickoff_iso: str, sport: str = "soccer") -> dict | None:
    """Datos del partido en cualquier momento (en vivo, entretiempo o terminado)."""
    found = _find(home, away, kickoff_iso, sport)
    return report_from_event(*found) if found else None


def find_recent(team_a: str, team_b: str, days: int = 3, sport: str = "soccer", finished_only: bool = True):
    """Busca un partido terminado entre dos equipos en los últimos días (en cualquier orden).
    Devuelve (resumen, inicio ISO) o None."""
    from datetime import datetime, timedelta
    now = datetime.now(ZoneInfo("America/New_York"))
    for back in range(days + 1):
        day = (now - timedelta(days=back)).strftime("%Y%m%d")
        for e in _scoreboard(day, sport):
            c = (e.get("competitions") or [{}])[0]
            comp = c.get("competitors") or []
            h = next((x for x in comp if x.get("homeAway") == "home"), None)
            a = next((x for x in comp if x.get("homeAway") == "away"), None)
            if not h or not a:
                continue
            if not ((_match(team_a, h["team"]) and _match(team_b, a["team"]))
                    or (_match(team_b, h["team"]) and _match(team_a, a["team"]))):
                continue
            r = report_from_event(e, c, h, a)
            if r["state"] == "post" or (not finished_only and r["state"] == "in"):
                ko = (e.get("date") or "").replace("Z", "")
                ko = (ko + ":00" if len(ko) == 16 else ko) + "Z"
                return r, ko
    return None


def preview(home: str, away: str, kickoff_iso: str, sport: str = "soccer") -> dict | None:
    """Equipos (nombre, sigla y colores) de un partido por jugarse."""
    found = _find(home, away, kickoff_iso, sport)
    if not found:
        return None
    _e, c, h, a = found
    return {"home": _side({"side": "home"}, h, {}), "away": _side({"side": "away"}, a, {}),
            "venue": ((c.get("venue") or {}).get("fullName") or "")}
