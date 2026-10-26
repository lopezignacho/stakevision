"""Demo real: lo que te llega ~30 min antes de un partido NBA (pronóstico sugerido A/B + Bet Builder).
Usa un partido real de mañana (hora Chile), cuotas reales y el reporte de lesiones de hoy. No envía nada."""
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import builder, config, formatting, main, nba, oddspapi, postimage, store  # noqa: E402

OUT = "data/probe/nbapre"
os.makedirs(OUT, exist_ok=True)
log = []
now = datetime.now(timezone.utc)
tz = ZoneInfo(config.TIMEZONE)
tomorrow = (now.astimezone(tz) + timedelta(days=1)).date()
try:
    frm, to = now, now + timedelta(hours=48)
    markets = oddspapi.markets(sport_id=config.NBA_SPORT_ID)
    fixtures = [f for f in oddspapi.upcoming_fixtures(main._iso(frm), main._iso(to), sport_id=config.NBA_SPORT_ID)
                if f.get("tournamentId") == config.NBA_TOURNAMENT]
    fx_t = [f for f in fixtures if store.parse_ts(f["startTime"]).astimezone(tz).date() == tomorrow] or fixtures
    log.append(f"Partidos NBA con cuotas: {len(fixtures)} · mañana: {len(fx_t)}")
    by_id = {f["fixtureId"]: f for f in fx_t}
    chosen = None
    for row in oddspapi.odds_by_tournaments([config.NBA_TOURNAMENT]):
        fx = by_id.get(row.get("fixtureId"))
        if not fx or len(row.get("bookmakerOdds") or {}) < 2:
            continue
        opt = nba.options_for_game(main.selections_for_fixture(fx, row, markets, "basketball"))
        if opt and (not chosen or opt[0].edge > chosen[1][0].edge):
            chosen = (fx, opt)
    if not chosen:
        log.append("Ningún partido de mañana con opción en rango.")
    else:
        fx, opt = chosen
        d = main._nba_pick_dict(fx, *opt)
        l = d["legs"][0]
        ctx = nba.context(l["home"], l["away"], l["kickoff"])
        for x in (d, d.get("alt")):
            if x:
                x["legs"][0]["nba_ctx"] = ctx
                x["analysis"] = formatting.analysis(x)
        d.update(id="123", status="candidate", stake_v=2, sport="basketball")
        log.append("==== 1) PRONÓSTICO SUGERIDO (te llega a ti)\n" + main.nba_candidate_text(d))
        log.append("==== Si eliges la opción A, así sale en el VIP\n" + formatting.channel_post(d, "vip"))
        open(f"{OUT}/pick_vip.jpg", "wb").write(postimage.render(d, "vip"))
        b = builder.suggest(l["home"], l["away"], l["kickoff"], "basketball")
        if b:
            legs = [{"home": l["home"], "away": l["away"], "kickoff": l["kickoff"], "league": "USA · NBA",
                     "sport": "basketball", "label": x["label"], "price": None} for x in b["legs"]]
            p = {"id": "124", "kind": "builder", "legs": legs, "bb": b, "price": None, "prob": b["prob"], "stake": 2}
            log.append("==== 2) BET BUILDER (te llega a ti)\n" + formatting.builder_owner(p))
        else:
            log.append("==== 2) BET BUILDER: sin 3 líneas seguras para este partido")
except Exception:
    log.append(traceback.format_exc())
open(f"{OUT}/demo.txt", "w").write("\n".join(log))
print("\n".join(log))
