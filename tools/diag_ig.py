"""Diagnóstico: comentarios recientes y respuestas (no imprime el token)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import instagram, store
st = store.load()
print("inbox:", {k: (v if not isinstance(v, list) else len(v)) for k, v in (st.get("ig_inbox") or {}).items()})
for m in instagram._call("GET", "me/media", st, fields="id,timestamp,comments_count", limit=14).get("data") or []:
    if not m.get("comments_count"):
        continue
    cs = instagram._call("GET", f"{m['id']}/comments", st, fields="id,text,username,timestamp,replies{text,username}").get("data") or []
    for c in cs:
        print(m["timestamp"], "|", c.get("username"), ":", c.get("text"), "| ts", c.get("timestamp"),
              "| replies:", [(r.get("username"), r.get("text")) for r in (c.get("replies") or {}).get("data", [])])
