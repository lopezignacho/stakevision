"""Números de Instagram para el diagnóstico de crecimiento (no imprime el token)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import instagram, store
st = store.load()
out = {}
def call(path, **kw):
    try:
        return instagram._call("GET", path, st, **kw)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}
out["profile"] = call("me", fields="username,name,biography,followers_count,follows_count,media_count,website")
media = (call("me/media", fields="id,timestamp,media_type,like_count,comments_count,caption,permalink", limit=40).get("data") or [])
rows = []
for m in media:
    ins = call(f"{m['id']}/insights", metric="reach,saved,shares,views,total_interactions")
    vals = {x["name"]: (x.get("values") or [{}])[0].get("value") for x in ins.get("data") or []} if "data" in ins else ins
    rows.append({"t": m["timestamp"], "type": m.get("media_type"), "likes": m.get("like_count"),
                 "comments": m.get("comments_count"), "first": (m.get("caption") or "").split("\n")[0][:90],
                 "hashtags": " ".join(w for w in (m.get("caption") or "").split() if w.startswith("#")), "ins": vals})
out["media"] = rows
out["account"] = call("me/insights", metric="reach,profile_views,follower_count,accounts_engaged,total_interactions",
                      period="day", metric_type="total_value", since=None)
out["account_days"] = call("me/insights", metric="reach,follower_count", period="day")
os.makedirs("data/probe", exist_ok=True)
json.dump(out, open("data/probe/igstats.json", "w"), ensure_ascii=False, indent=1)
print("ok")
