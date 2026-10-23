"""Lee estadísticas reales de ESPN de partidos de ayer y muestra qué señales saldrían (sin consultar cuotas)."""
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import espn, livebb  # noqa: E402

out = []
day = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")
evs = [e for e in espn._scoreboard(day, "soccer") if e["status"]["type"]["completed"]][:8]
for e in evs:
    sm = requests.get(livebb.ESPN_SUMMARY, params={"event": e["id"]}, timeout=25).json()
    m = livebb._stats(sm, e)
    if not m:
        out.append(f"{e['name']}: sin estadísticas")
        continue
    H, A = m["home"], m["away"]
    out.append(f"{e['name']} [{m['league']}] córners {H['corners']}-{A['corners']} tarjetas {H['yellow']}-{A['yellow']} "
               f"faltas {H['fouls']}-{A['fouls']} al arco {H['sot']}-{A['sot']} jugadores con remates {len(H['players']) + len(A['players'])}")
    for s in livebb.signals(m)[:4]:
        out.append(f"   → {s['label']} · {s['why']}")
os.makedirs("data/probe", exist_ok=True)
open("data/probe/livebb.txt", "w").write("\n".join(out))
print("\n".join(out))
