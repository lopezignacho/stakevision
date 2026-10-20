"""Diagnóstico de API-Football (no imprime la clave)."""
import os, requests
K = os.environ["APIFOOTBALL_KEY"]
B = "https://v3.football.api-sports.io"
def g(path, **p):
    r = requests.get(B + path, params=p, headers={"x-apisports-key": K}, timeout=30).json()
    resp = r.get("response")
    print(path, p, "| errors:", r.get("errors"), "| results:", r.get("results"),
          "| sample:", (str(resp[0])[:300] if isinstance(resp, list) and resp else resp if not isinstance(resp, list) else ""))
    return r
g("/status")
d = g("/fixtures", date="2026-10-19", timezone="UTC")
tid = None
for f in d.get("response") or []:
    if "Parma" in f["teams"]["home"]["name"]:
        tid = f["teams"]["home"]["id"]; lid = f["league"]["id"]; season = f["league"]["season"]
print("Parma id", tid)
if tid:
    g("/fixtures", team=tid, last=5)
    g("/fixtures", team=tid, season=season)
    g("/fixtures", team=tid, season=season, **{"from": "2026-08-01", "to": "2026-10-18"})
    g("/teams/statistics", team=tid, league=lid, season=season)
