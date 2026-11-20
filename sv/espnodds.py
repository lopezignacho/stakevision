"""Cuotas gratis y sin límite: las que publica ESPN (DraftKings) en su marcador.

Se usan cuando OddsPapi no responde (por ejemplo, cuota mensual agotada). Dan, por partido:
ganador (1X2 en fútbol, ganador en NBA), total de goles/puntos y hándicap, con la cuota de cierre (o la de
apertura si aún no hay cierre). La probabilidad justa sale de quitarle el margen a esa misma casa, así que
aquí no se mide «valor» contra otra casa: el filtro es el rango de cuota y nuestros datos (forma y cara a cara).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .value import Selection

SRC = "espn"


def american(odds) -> float | None:
    """'-210' → 1.48 · '+350' → 4.50 · 'EVEN' → 2.00."""
    if odds is None:
        return None
    s = str(odds).strip().upper()
    if s in ("EVEN", "EV"):
        return 2.0
    try:
        v = float(s.replace("+", ""))
    except ValueError:
        return None
    if v == 0:
        return None
    return round(1 + (v / 100 if v > 0 else 100 / -v), 2)


def _pick(node: dict | None) -> tuple[float | None, str | None]:
    """(cuota decimal, línea) de cierre; si no hay cierre, la de apertura."""
    node = node or {}
    for k in ("close", "current", "open"):
        x = node.get(k) or {}
        price = american(x.get("odds"))
        if price:
            return price, x.get("line")
    return None, None


def _num(line: str | None) -> float | None:
    if not line:
        return None
    try:
        return float(str(line).lstrip("ouOU+"))
    except ValueError:
        return None


def _devig(prices: list[float]) -> list[float] | None:
    imp = [1 / p for p in prices]
    tot = sum(imp)
    if not (1.0 <= tot <= 1.15):   # margen raro: mejor no usar ese mercado
        return None
    return [x / tot for x in imp]


def from_event(e: dict, league: str, sport: str = "soccer") -> list[Selection]:
    c = (e.get("competitions") or [{}])[0]
    comp = c.get("competitors") or []
    h = next((x for x in comp if x.get("homeAway") == "home"), None)
    a = next((x for x in comp if x.get("homeAway") == "away"), None)
    o = ((c.get("odds") or [None])[0]) or {}
    if not h or not a or not o:
        return []
    home, away = h["team"]["displayName"], a["team"]["displayName"]
    ko = e["date"].replace("Z", ":00Z") if len(e["date"]) == 17 else e["date"]
    fid = f"espn-{e.get('id')}"
    out: list[Selection] = []

    def add(mid, market, mtype, outs, handicap):
        prices = [p for _o, p in outs]
        if any(p is None or p <= 1.01 for p in prices):
            return
        fair = _devig(prices)
        if not fair:
            return
        for (name, price), fp in zip(outs, fair):
            out.append(Selection(fixture_id=fid, home=home, away=away, league=league, kickoff=ko,
                                 market_id=mid, market=market, mtype=mtype, outcome_id=f"{mid}-{name}",
                                 outcome=name, handicap=handicap, price=price, fair_prob=fp, ref_price=price,
                                 sport=sport))

    ml = o.get("moneyline") or {}
    ph, _ = _pick(ml.get("home"))
    pa, _ = _pick(ml.get("away"))
    if sport == "soccer":
        pd, _ = _pick(ml.get("draw"))
        if pd is None and (o.get("drawOdds") or {}).get("moneyLine") is not None:
            pd = american((o.get("drawOdds") or {}).get("moneyLine"))
        add("espn-1x2", "Resultado del partido", "1x2", [("1", ph), ("X", pd), ("2", pa)], 0.0)
    else:
        add("espn-ml", "Ganador del partido", "moneyline", [("1", ph), ("2", pa)], None)

    tot = o.get("total") or {}
    po, lo = _pick(tot.get("over"))
    pu, lu = _pick(tot.get("under"))
    line = _num(lo) if lo else o.get("overUnder")
    if line is not None and (_num(lu) in (None, line)):
        add(f"espn-tot-{line}", "Total de goles" if sport == "soccer" else "Total de puntos", "totals",
            [("Más", po), ("Menos", pu)], float(line))

    sp = o.get("pointSpread") or {}
    psh, lh = _pick(sp.get("home"))
    psa, la = _pick(sp.get("away"))
    hl, al = _num(lh), _num(la)
    if hl is not None and al is not None and abs(hl + al) < 1e-9:
        add(f"espn-sp-{hl}", "Hándicap", "spreads", [("1", psh), ("2", psa)], float(hl))
    return out


def soccer_selections(frm: datetime, to: datetime) -> tuple[list[Selection], int, int]:
    """Selecciones de fútbol de las ligas conocidas con partido entre frm y to.
    Devuelve (selecciones, ligas con partidos, partidos con cuotas)."""
    from . import builder, espn
    from .crest import SOCCER_LEAGUES
    days = sorted({(frm + timedelta(hours=k)).astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d")
                   for k in range(0, int((to - frm).total_seconds() // 3600) + 1, 6)} |
                  {to.astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d")})
    sels, leagues, games, seen = [], set(), 0, set()
    for lg in SOCCER_LEAGUES:
        for day in days:
            for e in espn._league_board(day, lg):
                if e.get("id") in seen:
                    continue
                seen.add(e.get("id"))
                state = (((e.get("status") or {}).get("type") or {}).get("state") or "")
                if state != "pre":
                    continue
                ko = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
                if not (frm <= ko <= to):
                    continue
                name = builder.league_name(((e.get("season") or {}).get("slug")) or lg)
                got = from_event(e, name, "soccer")
                if got:
                    games += 1
                    leagues.add(lg)
                    sels += got
    return sels, len(leagues), games


def nba_selections(frm: datetime, to: datetime) -> list[Selection]:
    from . import nba
    sels, seen = [], set()
    for k in (0, 1):
        day = (frm + timedelta(days=k)).astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d")
        for e in nba._get("/scoreboard", dates=day).get("events") or []:
            if e.get("id") in seen:
                continue
            seen.add(e.get("id"))
            ko = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
            if frm <= ko <= to:
                sels += from_event(e, "USA · NBA", "basketball")
    return sels


def best_singles(sels: list[Selection], n: int, odds_min: float, odds_max: float) -> list[Selection]:
    """Una por partido, dentro del rango de cuota, de la más probable a la menos (sin cuartos de línea)."""
    ok = [s for s in sels if odds_min <= s.price <= odds_max
          and not (s.handicap is not None and float(s.handicap) % 0.5)]
    ok.sort(key=lambda s: s.fair_prob, reverse=True)
    out, used = [], set()
    for s in ok:
        if s.fixture_id in used:
            continue
        out.append(s)
        used.add(s.fixture_id)
        if len(out) >= n:
            break
    return out
