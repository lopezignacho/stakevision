"""Pruebas del motor con datos simulados (no usan internet ni claves)."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STATE_KEY", "clave-de-prueba-muy-larga")

from sv import config, formatting, store  # noqa: E402
from sv.value import build_picks, selections_for_fixture  # noqa: E402

config.STATE_KEY = os.environ["STATE_KEY"]

MARKETS = {
    "101": {"name": "Resultado final", "type": "1x2", "period": "fulltime", "handicap": 0,
            "playerProp": False, "length": 3, "outcomes": {"101": "1", "102": "X", "103": "2"}},
    "104": {"name": "Ambos marcan", "type": "bothteamsscore", "period": "fulltime", "handicap": 0,
            "playerProp": False, "length": 2, "outcomes": {"104": "Sí", "105": "No"}},
    "1010": {"name": "Más/Menos 2.5", "type": "totals", "period": "fulltime", "handicap": 2.5,
             "playerProp": False, "length": 2, "outcomes": {"1010": "Más", "1011": "Menos"}},
    "2000": {"name": "Hándicap asiático -0.25", "type": "spreads", "period": "fulltime",
             "handicap": -0.25, "playerProp": False, "length": 2, "outcomes": {"2000": "1", "2001": "2"}},
    "3000": {"name": "Resultado 1ª mitad", "type": "1x2", "period": "p1", "handicap": 0,
             "playerProp": False, "length": 3, "outcomes": {"3000": "1", "3001": "X", "3002": "2"}},
}


def book(prices: dict) -> dict:
    return {"markets": {m: {"outcomes": {o: {"players": {"0": {"price": p, "active": True}}}
                                         for o, p in outs.items()}}
                        for m, outs in prices.items()}}


def fixture(fid, home, away, hours=5):
    ko = (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"fixtureId": fid, "participant1Name": home, "participant2Name": away,
            "tournamentName": "Primera División", "categoryName": "Chile", "startTime": ko,
            "tournamentId": 1}


def test_value_and_filters():
    fx = fixture("f1", "Colo-Colo", "U. de Chile")
    odds = {"bookmakerOdds": {
        "pinnacle": book({"101": {"101": 1.95, "102": 3.50, "103": 4.20},      # margen ~4,6%
                          "104": {"104": 1.80, "105": 2.05},
                          "2000": {"2000": 1.90, "2001": 1.98},
                          "3000": {"3000": 2.60, "3001": 2.10, "3002": 4.50}}),
        "betano": book({"101": {"101": 2.00, "102": 3.40, "103": 4.00},
                        "104": {"104": 1.95, "105": 1.85},
                        "2000": {"2000": 2.20, "2001": 1.70},
                        "3000": {"3000": 3.50, "3001": 2.0, "3002": 4.0}}),
    }}
    sels = selections_for_fixture(fx, odds, MARKETS)
    names = {(s.market_id, s.outcome_id) for s in sels}
    assert ("2000", "2000") not in names, "las líneas de cuarto deben excluirse"
    assert ("3000", "3000") not in names, "los mercados de primer tiempo deben excluirse"
    fair_sum = sum(s.fair_prob for s in sels if s.market_id == "101")
    assert abs(fair_sum - 1) < 1e-9

    picks = build_picks(sels)
    # 1 de 2.00 vs justa ~2.04 => sin valor. Ambos marcan Sí 1.95 vs justa ~1.88 => +3,6% => válido.
    valor = [p for p in picks if p.tier == "valor"]
    assert len(valor) == 1, picks
    assert all(p.tier == "justa" and p.stake == 1 for p in picks if p not in valor)
    p = valor[0]
    assert p.kind == "simple" and p.legs[0].market_id == "104"
    assert 1.65 <= p.price <= 2.0 and p.edge >= config.MIN_EDGE
    assert 1 <= p.stake <= config.MAX_STAKE


def test_fallback_fills_daily_minimum():
    fxs = [fixture(f"x{i}", f"L{i}", f"V{i}") for i in range(4)]
    sels = []
    for i, fx in enumerate(fxs):
        odds = {"bookmakerOdds": {
            "pinnacle": book({"104": {"104": 1.80, "105": 2.05}}),
            "betano": book({"104": {"104": 1.86 - i * 0.02, "105": 1.95}})}}   # -1% ... -4%
        sels += selections_for_fixture(fx, odds, MARKETS)
    picks = build_picks(sels)
    assert len(picks) == 1  # solo la de -1% está dentro del piso de -2%
    assert all(p.tier == "justa" and p.edge >= config.FALLBACK_MIN_EDGE for p in picks)
    assert len({p.legs[0].fixture_id for p in picks}) == len(picks)


def test_doubles_only_when_each_leg_has_value():
    fxa, fxb, fxc = fixture("a", "A", "B"), fixture("b", "C", "D"), fixture("c", "E", "F")
    mk = lambda ref, bet: {"bookmakerOdds": {  # noqa: E731
        "pinnacle": book({"101": dict(zip(("101", "102", "103"), ref))}),
        "betano": book({"101": dict(zip(("101", "102", "103"), bet))})}}
    sels = []
    sels += selections_for_fixture(fxa, mk((1.36, 5.00, 9.50), (1.47, 4.6, 8.5)), MARKETS)   # pierna con valor
    sels += selections_for_fixture(fxb, mk((1.26, 6.20, 12.0), (1.36, 5.6, 11.0)), MARKETS)   # pierna con valor
    sels += selections_for_fixture(fxc, mk((1.30, 5.50, 10.0), (1.25, 5.0, 9.0)), MARKETS)   # sin valor
    picks = build_picks(sels)
    doubles = [p for p in picks if p.kind == "doble"]
    assert len(doubles) == 1
    d = doubles[0]
    assert {l.fixture_id for l in d.legs} == {"a", "b"}
    assert 1.65 <= d.price <= 2.0 and all(l.edge > 0 for l in d.legs)


def test_state_roundtrip_and_public_export():
    tmp = tempfile.mkdtemp()
    config.STATE_FILE = os.path.join(tmp, "state.enc")
    config.PUBLIC_HISTORY = os.path.join(tmp, "historial.json")
    st = store.empty_state()
    past = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    future = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    leg = {"home": "A", "away": "B", "league": "L", "market": "M", "outcome": "1", "price": 1.8}
    st["picks"] = {
        "1": {"id": "1", "status": "settled", "kickoff": past, "kind": "simple", "price": 1.8,
              "stake": 2, "free": False, "result": "W", "legs": [leg]},
        "2": {"id": "2", "status": "published", "kickoff": future, "kind": "simple", "price": 1.9,
              "stake": 2, "free": False, "result": None, "legs": [leg]},   # VIP futuro: oculto
        "3": {"id": "3", "status": "published", "kickoff": future, "kind": "simple", "price": 1.7,
              "stake": 1, "free": True, "result": None, "legs": [leg], "analysis": "x"},
    }
    store.save(st)
    raw = open(config.STATE_FILE, "rb").read()
    assert b"settled" not in raw, "el estado debe quedar cifrado"
    assert store.load()["picks"]["1"]["result"] == "W"
    import json
    pub = json.load(open(config.PUBLIC_HISTORY))
    ids = {r["id"] for r in pub["picks"]}
    assert ids == {"1", "3"}
    assert pub["summary"]["yield"] == 0.8 and pub["summary"]["hit_rate"] == 1.0


def test_messages_render():
    leg = {"home": "Colo-Colo", "away": "U. de Chile", "league": "Chile · Primera", "kickoff":
           "2026-10-20T23:00:00Z", "market": "Resultado final", "outcome": "1", "price": 1.85, "mtype": "1x2", "handicap": 0,
           "fair_odds": 1.74, "edge": 0.063, "context": {"home": {"form": "GGEPG", "gf": 1.8, "ga": 0.8}}}
    p = {"id": "7", "kind": "simple", "price": 1.85, "prob": 0.574, "edge": 0.063, "stake": 2, "legs": [leg]}
    p["analysis"] = formatting.analysis(p)
    txt = formatting.channel_post(p)
    assert "Gana Colo-Colo" in txt and "Betano" not in txt and "23/10" not in txt
    assert "20/10 20:00" in txt  # hora de Chile (UTC-3)
    assert "Candidato #7" in formatting.owner_candidate(p)
    L = formatting.outcome_label
    assert L({"outcome": "Más", "mtype": "totals", "handicap": 2.5, "home": "A", "away": "B"}) == "Más de 2.5 goles"
    assert L({"outcome": "Más", "mtype": "totals", "handicap": 2.0, "home": "A", "away": "B"}) == "Más de 2 goles (con 2 exactos se devuelve)"
    assert L({"outcome": "2", "mtype": "spreads", "handicap": -0.5, "home": "A", "away": "B"}) == "B +0.5 (hándicap asiático)"
    assert L({"outcome": "1", "mtype": "spreads", "handicap": -1.0, "home": "A", "away": "B"}) == "A -1 (hándicap asiático; si empata en la línea, se devuelve)"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
