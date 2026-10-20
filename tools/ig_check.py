"""Revisión de Instagram: qué comentarios y mensajes ve el bot y qué respondió (no imprime el token)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sv import instagram, store
st = store.load()
box = st.get("ig_inbox") or {}
print("asistente activo desde:", box.get("since"), "| comentarios procesados:", len(box.get("comments", [])),
      "| mensajes procesados:", len(box.get("dms", [])))
for m in instagram._call("GET", "me/media", st, fields="id,timestamp,comments_count,permalink", limit=15).get("data") or []:
    print("PUBLICACIÓN", m["timestamp"], m.get("permalink"), "comentarios:", m.get("comments_count"))
    if m.get("comments_count"):
        cs = instagram._call("GET", f"{m['id']}/comments", st,
                             fields="id,text,username,timestamp,replies{text,username}").get("data") or []
        for c in cs:
            print("   ", c.get("timestamp"), c.get("username"), ":", c.get("text"),
                  "| respuestas:", [(r.get("username"), r.get("text")) for r in (c.get("replies") or {}).get("data", [])])
try:
    convs = instagram._call("GET", "me/conversations", st, platform="instagram", fields="id,updated_time").get("data") or []
    print("conversaciones:", len(convs))
    for c in convs[:5]:
        msgs = (instagram._call("GET", c["id"], st, fields="messages{created_time,from,message}").get("messages") or {}).get("data") or []
        for x in msgs[:4]:
            print("   ", x.get("created_time"), (x.get("from") or {}).get("username"), ":", (x.get("message") or "")[:120])
except instagram.InstagramError as e:
    print("mensajes: error ->", e)
