"""Diagnóstico: partidos en vivo según OddsPapi (1 consulta)."""
from datetime import datetime, timedelta, timezone
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import oddspapi
now = datetime.now(timezone.utc)
f = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
rows = oddspapi.live_fixtures(f(now - timedelta(minutes=95)), f(now))
print("en vivo:", len(rows))
for r in rows[:15]:
    print(r.get("startTime"), r.get("statusId"), r.get("tournamentId"), r.get("participant1Name"), "vs", r.get("participant2Name"))
