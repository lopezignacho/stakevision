"""Motor de valor: compara cada cuota de Betano con la cuota justa de Pinnacle.

Cuota justa = la de Pinnacle sin su margen (método multiplicativo).
Valor (edge) = probabilidad justa x cuota Betano - 1.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field, asdict

from . import config


@dataclass
class Selection:
    fixture_id: str
    home: str
    away: str
    league: str
    kickoff: str            # ISO UTC
    market_id: str
    market: str
    mtype: str
    outcome_id: str
    outcome: str
    handicap: float | None
    price: float            # cuota Betano
    fair_prob: float        # probabilidad justa (Pinnacle sin margen)
    ref_price: float        # cuota Pinnacle original

    @property
    def fair_odds(self) -> float:
        return 1 / self.fair_prob

    @property
    def edge(self) -> float:
        return self.fair_prob * self.price - 1


@dataclass
class Pick:
    kind: str                       # "simple" | "doble"
    legs: list[Selection] = field(default_factory=list)

    @property
    def price(self) -> float:
        p = 1.0
        for l in self.legs:
            p *= l.price
        return round(p, 2)

    @property
    def prob(self) -> float:
        p = 1.0
        for l in self.legs:
            p *= l.fair_prob
        return p

    @property
    def edge(self) -> float:
        return self.prob * self.price - 1

    @property
    def stake(self) -> int:
        """Cuarto de Kelly expresado como ~% del bankroll, de 1 a MAX_STAKE (escala /10)."""
        b = self.price - 1
        kelly = max(0.0, (self.prob * self.price - 1) / b) if b > 0 else 0
        return max(1, min(config.MAX_STAKE, round(kelly * 0.25 * 100)))

    @property
    def kickoff(self) -> str:
        return min(l.kickoff for l in self.legs)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "price": self.price,
            "prob": round(self.prob, 4),
            "edge": round(self.edge, 4),
            "stake": self.stake,
            "kickoff": self.kickoff,
            "legs": [{**asdict(l), "fair_odds": round(l.fair_odds, 3), "edge": round(l.edge, 4)}
                     for l in self.legs],
        }


def _price(book_odds: dict, market_id: str, outcome_id: str) -> float | None:
    try:
        players = book_odds["markets"][market_id]["outcomes"][outcome_id]["players"]
    except (KeyError, TypeError):
        return None
    pl = players.get("0") or next(iter(players.values()), None)
    if not pl or pl.get("active") is False:
        return None
    price = pl.get("price")
    return float(price) if price and price > 1 else None


def _market_ok(meta: dict | None) -> bool:
    if not meta or meta.get("playerProp"):
        return False
    if config.ONLY_FULLTIME and (meta.get("period") or "").lower() != "fulltime":
        return False
    if config.ALLOWED_MARKET_TYPES and meta.get("type") not in config.ALLOWED_MARKET_TYPES:
        return False
    h = meta.get("handicap")
    if h not in (None, 0) and abs((abs(float(h)) * 4) % 2 - 1) < 1e-9:
        return False  # líneas de cuarto (x.25 / x.75)
    return True


def selections_for_fixture(fx: dict, odds: dict, markets: dict) -> list[Selection]:
    """Todas las selecciones donde Betano y Pinnacle tienen el mercado completo."""
    books = odds.get("bookmakerOdds") or {}
    book, ref = books.get(config.BOOK), books.get(config.REFERENCE)
    if not book or not ref or book.get("suspended") or ref.get("suspended"):
        return []
    out = []
    for mid, rmkt in (ref.get("markets") or {}).items():
        meta = markets.get(str(mid))
        if not _market_ok(meta):
            continue
        if mid not in (book.get("markets") or {}):
            continue
        oids = list((rmkt.get("outcomes") or {}).keys())
        if meta.get("length") and len(oids) != meta["length"]:
            continue
        if len(oids) not in (2, 3):
            continue
        ref_prices = [_price(ref, mid, o) for o in oids]
        if any(p is None for p in ref_prices):
            continue
        implied = [1 / p for p in ref_prices]
        total = sum(implied)
        margin = total - 1
        if margin < -0.01 or margin > config.MAX_REF_MARGIN:
            continue
        for oid, imp, rp in zip(oids, implied, ref_prices):
            bp = _price(book, mid, oid)
            if bp is None:
                continue
            out.append(Selection(
                fixture_id=fx["fixtureId"],
                home=fx.get("participant1Name") or str(fx.get("participant1Id")),
                away=fx.get("participant2Name") or str(fx.get("participant2Id")),
                league=" · ".join(x for x in (fx.get("categoryName"), fx.get("tournamentName")) if x),
                kickoff=fx.get("startTime"),
                market_id=str(mid), market=meta.get("name") or str(mid), mtype=meta.get("type") or "",
                outcome_id=str(oid), outcome=meta["outcomes"].get(str(oid), str(oid)),
                handicap=meta.get("handicap"),
                price=bp, fair_prob=imp / total, ref_price=rp,
            ))
    return out


def build_picks(selections: list[Selection]) -> list[Pick]:
    """Simples con valor en 1.65-2.00 primero; dobles solo si cada selección tiene valor."""
    good = [s for s in selections if config.MIN_EDGE <= s.edge <= config.MAX_EDGE]
    singles = [Pick("simple", [s]) for s in good if config.ODDS_MIN <= s.price <= config.ODDS_MAX]

    legs = [s for s in good if config.LEG_ODDS_MIN <= s.price <= config.LEG_ODDS_MAX]
    legs.sort(key=lambda s: s.edge, reverse=True)
    legs = legs[:25]
    doubles = []
    for a, b in itertools.combinations(legs, 2):
        if a.fixture_id == b.fixture_id:
            continue  # mismo partido: resultados correlacionados
        p = Pick("doble", [a, b])
        if config.ODDS_MIN <= p.price <= config.ODDS_MAX and p.edge >= config.MIN_EDGE:
            doubles.append(p)

    singles.sort(key=lambda p: p.edge, reverse=True)
    doubles.sort(key=lambda p: p.edge, reverse=True)

    chosen, used = [], set()
    # Simples tienen prioridad; luego dobles. Nunca dos picks con el mismo partido.
    for p in singles + doubles:
        fids = {l.fixture_id for l in p.legs}
        if fids & used:
            continue
        chosen.append(p)
        used |= fids
        if len(chosen) >= config.MAX_CANDIDATES:
            break
    return chosen
