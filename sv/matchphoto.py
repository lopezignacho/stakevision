"""Foto para cada momento del partido, siempre ligada a lo que pasa:

- Antes (pick): un referente del equipo de nuestro pick (o de los dos), idealmente con la camiseta del club.
- Entretiempo: quien marcó; si no hubo goles, un referente de cualquiera de los dos.
- Post partido: la figura (lo decide recap.hero) con la camiseta de su club.
Si no hay foto de jugadores, una foto de partido o hinchada del club. Nunca entradas, afiches, cromos ni escudos.
"""
from __future__ import annotations

import traceback

from . import commons, players


def _names(team: dict | None, fallback: str) -> list[str]:
    t = team or {}
    return [x for x in dict.fromkeys([t.get("name"), t.get("short"), fallback]) if x]


def referent(team_names: list[str], sport: str = "soccer", tries: int = 4):
    """(jpeg, crédito) de un referente del equipo, o None."""
    for name in team_names[:2]:
        try:
            sq = players.squad(name, sport)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            sq = []
        if not sq:
            continue
        for pl in sq[:tries]:   # primero con la camiseta del club
            got = commons.player_photo(pl["name"], team_names)
            if got and got[1].get("team_hit"):
                return got
        for pl in sq[:tries]:   # luego su foto principal o una reciente
            got = (commons.file_photo(pl["image"]) if pl.get("image") else None) or \
                commons.player_photo(pl["name"], team_names)
            if got:
                got[1]["player"] = pl["name"]
                return got
        return None
    return None


def for_pick(leg: dict, teams: dict | None):
    """Antes del partido: referente del equipo elegido (o local), luego del rival, luego foto de club."""
    sport = leg.get("sport") or "soccer"
    side = {"1": "home", "2": "away"}.get(str(leg.get("outcome")), "home")
    other = "away" if side == "home" else "home"
    order = [_names((teams or {}).get(side), leg[side]), _names((teams or {}).get(other), leg[other])]
    for names in order:
        got = referent(names, sport)
        if got:
            return got
    for names in order:
        got = commons.photo(names[0], team=True)
        if got:
            return got
    return None


def for_scorer(full_name: str, team_names: list[str]):
    return commons.player_photo(full_name, team_names) if full_name else None


def for_halftime(rep: dict):
    scorers = [g for g in reversed(rep.get("goals") or []) if g["kind"] != "own" and g.get("full")]
    for g in scorers[:2]:
        got = for_scorer(g["full"], _names(rep.get(g["side"]), ""))
        if got:
            return got
    for side in ("home", "away"):
        got = referent(_names(rep.get(side), ""), "soccer")
        if got:
            return got
    return None
