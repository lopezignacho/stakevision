"""Datos verificados de ESPN para el formato «Figura»: la planilla del jugador y el marcador del partido."""
from __future__ import annotations

from datetime import timedelta

from . import crest, nba, store


def _hex(x, d=(40, 50, 70)):
    try:
        return tuple(int(x[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:  # noqa: BLE001
        return d


def _main_color(t: dict):
    """Color principal para fondo oscuro: si el color de ESPN es muy claro (amarillo, blanco), el alternativo."""
    c = _hex(t.get("color"))
    if sum(c) > 450 and t.get("alternateColor"):
        alt = _hex(t["alternateColor"])
        if sum(alt) < sum(c):
            return alt
    return c


def _rec(c: dict) -> str:
    return next((r.get("summary") for r in c.get("records") or [] if r.get("type") == "total"), "")


def _side(c: dict) -> dict:
    t = c["team"]
    return {"name": t.get("displayName", ""), "short": t.get("name", ""), "abbr": t.get("abbreviation", ""),
            "color": _main_color(t), "score": int(c.get("score") or 0), "record": _rec(c),
            "logo": crest.get("", url=t.get("logo", ""))}


def nba_figura(player: str, days: int = 3) -> dict | None:
    """Último partido terminado del jugador (hasta `days` días atrás): su planilla, el marcador y los escudos."""
    key = nba._plain(player)
    surname = key.split()[-1] if key else ""
    now = store.now_utc()
    for back in range(days + 1):
        day = (now - timedelta(days=back)).strftime("%Y%m%d")
        for e in nba._get("/scoreboard", dates=day).get("events") or []:
            comp = e["competitions"][0]
            if not comp["status"]["type"].get("completed"):
                continue
            sm = nba._get("/summary", event=e["id"])
            for t in (sm.get("boxscore") or {}).get("players") or []:
                for st in t.get("statistics") or []:
                    keys = st.get("keys") or []
                    for a in st.get("athletes") or []:
                        nm = nba._plain((a.get("athlete") or {}).get("displayName", ""))
                        if not nm or (nm != key and not (surname and nm.endswith(surname) and nm[0] == key[0])):
                            continue
                        v = dict(zip(keys, a.get("stats") or []))
                        if not v or a.get("didNotPlay"):
                            continue
                        cs = {c["homeAway"]: c for c in comp["competitors"]}
                        side = "home" if str(cs["home"]["team"]["id"]) == str(t["team"]["id"]) else "away"
                        h, w = _side(cs["home"]), _side(cs["away"])
                        tpm = str(v.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted", "0-0")).split("-")[0]
                        stats = [(v.get("points"), "PTS"), (v.get("rebounds"), "REB"), (v.get("assists"), "AST")]
                        stats.append((tpm, "T3") if int(tpm or 0) >= 4 or not int(v.get("blocks") or 0) >= 3
                                     else (v.get("blocks"), "TAP"))
                        return {"player": a["athlete"]["displayName"], "stats": stats, "focus": side,
                                "color": (h if side == "home" else w)["color"], "home": h, "away": w,
                                "winner": "home" if h["score"] > w["score"] else "away", "competition": "NBA",
                                "team": (h if side == "home" else w)["name"], "game_id": e["id"]}
    return None
