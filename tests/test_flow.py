"""Simula un día completo: escaneo -> aprobación -> publicación -> resultado. Sin internet."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("STATE_KEY", "clave-de-prueba-muy-larga")

import test_engine as te  # noqa: E402
from sv import apifootball, config, main, oddspapi, store, telegram  # noqa: E402

tmp = tempfile.mkdtemp()
config.STATE_FILE = os.path.join(tmp, "state.enc")
config.PUBLIC_HISTORY = os.path.join(tmp, "historial.json")
config.STATE_KEY = os.environ["STATE_KEY"]
config.LINK_CODE = "codigo123"

sent, updates_q = [], []


def fake_send(chat, text, buttons=None, reply_to=None):
    sent.append((chat, text, buttons, reply_to))
    return {"message_id": len(sent)}


telegram.send = fake_send
photos = []


def fake_photo(chat, photo, caption=None, reply_to=None):
    assert photo[:2] == b"\xff\xd8"  # JPEG real
    photos.append((chat, caption))
    sent.append((chat, caption or "[foto]", None, reply_to))
    return {"message_id": len(sent)}


telegram.send_photo = fake_photo
telegram.edit_buttons_off = lambda *a, **k: None
telegram.answer = lambda *a, **k: None
telegram._call = lambda *a, **k: True
telegram.updates = lambda offset: [u for u in updates_q if u["update_id"] >= offset]

fx = te.fixture("f1", "Colo-Colo", "U. de Chile", hours=5)
oddspapi.markets = lambda force=False: te.MARKETS
oddspapi.upcoming_fixtures = lambda frm, to: [fx]
oddspapi.odds_by_tournaments = lambda ids: [{"fixtureId": "f1", "bookmakerOdds": {
    "pinnacle": te.book({"104": {"104": 1.80, "105": 2.05}}),
    "betano": te.book({"104": {"104": 1.95, "105": 1.85}})}}]
apifootball.context = lambda *a: None
apifootball.final_score = lambda *a: (2, 1)

OWNER, VIP = 111, -100222

# 1) vincular dueño y VIP
updates_q += [
    {"update_id": 1, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/vincular codigo123"}},
    {"update_id": 2, "channel_post": {"chat": {"id": VIP, "type": "channel"}, "text": "/vincular_vip codigo123"}},
    {"update_id": 3, "message": {"chat": {"id": 999, "type": "private"}, "text": "/vincular malo"}},
]
main.poll()
st = store.load()
assert st["owner_chat"] == OWNER and st["vip_chat"] == VIP

# 2) escaneo
main.scan()
st = store.load()
cands = [p for p in st["picks"].values() if p["status"] == "candidate"]
assert len(cands) == 1, cands
pid = cands[0]["id"]

# 3) un extraño intenta aprobar: se ignora; el dueño aprueba VIP + Gratis
updates_q += [
    {"update_id": 4, "callback_query": {"id": "x", "data": f"f:{pid}",
                                         "message": {"chat": {"id": 999}, "message_id": 5}}},
    {"update_id": 5, "callback_query": {"id": "y", "data": f"f:{pid}",
                                         "message": {"chat": {"id": OWNER}, "message_id": 5}}},
]
main.poll()
st = store.load()
p = st["picks"][pid]
assert p["status"] == "published" and p["free"] is True
assert set(p["channel_msgs"]) == {"vip", "free"}
posted_chats = [c for c, *_ in sent]
assert VIP in posted_chats and config.FREE_CHANNEL in posted_chats
assert len(photos) == 2 and all(c and "STAKEVISION" in c for _, c in photos)   # imagen con el texto como pie

# 3b) aviso 30 min antes del partido, como respuesta al pick en ambos canales
st = store.load()
p = st["picks"][pid]
p["kickoff"] = (datetime.now(timezone.utc) + timedelta(minutes=28)).strftime("%Y-%m-%dT%H:%M:%SZ")
p["legs"][0]["kickoff"] = p["kickoff"]
p["published_at"] = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
store.save(st)
n = len(sent)
main.poll()
rem = sent[n:]
assert len(rem) == 2 and all("está por comenzar" in t and r for _, t, _, r in rem), rem
main.poll()
assert len(sent) == n + 2   # solo una vez

# 4) el partido termina -> pide resultado con sugerencia -> dueño confirma verde
p["kickoff"] = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
for l in p["legs"]:
    l["kickoff"] = p["kickoff"]
store.save(st)
main.poll()
req = sent[-1]
# 2-1: ambos marcan -> el bot lo califica solo como verde y lo publica
assert "Resultado automático" in req[1] and "VERDE" in req[1] and "2-1" in req[1], req[1]
st = store.load()
assert st["picks"][pid]["result"] == "W" and st["picks"][pid]["auto_result"]
assert set(st["picks"][pid]["result_msgs"]) == {"vip", "free"}
# kit de Instagram al dueño: imagen de celebración + texto para copiar
assert any(c and "Para Instagram" in c for ch, c in photos if ch == OWNER)
ig = [t for ch, t, *_ in sent if ch == OWNER and t.startswith("<pre>")]
assert len(ig) == 1 and "Stakevision" in ig[0] and "+18" in ig[0], ig
import json  # noqa: E402
pub = json.load(open(config.PUBLIC_HISTORY))
assert pub["summary"]["wins"] == 1 and pub["picks"][0]["result"] == "W"

# 4b) el dueño corrige: Corregir -> Roja
edited = []
telegram.edit_text = lambda chat, mid, text: edited.append((chat, mid, text))
updates_q += [
    {"update_id": 6, "callback_query": {"id": "z", "data": f"c:{pid}",
                                        "message": {"chat": {"id": OWNER}, "message_id": 9}}},
    {"update_id": 61, "callback_query": {"id": "z2", "data": f"L:{pid}",
                                         "message": {"chat": {"id": OWNER}, "message_id": 9}}},
]
main.poll()
st = store.load()
assert st["picks"][pid]["result"] == "L" and len(edited) == 2 and "corregido" in edited[0][2]
pub = json.load(open(config.PUBLIC_HISTORY))
assert pub["summary"]["losses"] == 1 and pub["summary"]["wins"] == 0
print("OK flujo completo:", len(sent), "mensajes simulados")

# 4c) marcador aún no disponible -> reintenta más tarde, sin preguntar
fx3 = te.fixture("f3", "Palestino", "Huachipato", hours=5)
oddspapi.upcoming_fixtures = lambda frm, to: [fx3]
oddspapi.odds_by_tournaments = lambda ids: [{"fixtureId": "f3", "bookmakerOdds": {
    "pinnacle": te.book({"104": {"104": 1.80, "105": 2.05}}),
    "betano": te.book({"104": {"104": 1.95, "105": 1.85}})}}]
main.scan()
st = store.load()
pid3 = next(p["id"] for p in st["picks"].values() if p["legs"][0]["fixture_id"] == "f3")
updates_q.append({"update_id": 62, "callback_query": {"id": "q", "data": f"a:{pid3}",
                                                      "message": {"chat": {"id": OWNER}, "message_id": 20}}})
main.poll()
st = store.load()
p3 = st["picks"][pid3]
p3["kickoff"] = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
p3["legs"][0]["kickoff"] = p3["kickoff"]
store.save(st)
apifootball.final_score = lambda *a: None
n = len(sent)
main.poll()
st = store.load()
assert st["picks"][pid3]["status"] == "published" and st["picks"][pid3].get("next_check") and len(sent) == n
apifootball.final_score = lambda *a: (0, 0)   # 0-0: "Ambos marcan: Sí" pierde
st["picks"][pid3]["next_check"] = None
store.save(st)
main.poll()
assert store.load()["picks"][pid3]["result"] == "L" and "ROJA" in sent[-1][1]
print("OK resultado automático")

# 5) /buscar: el dueño pide una búsqueda manual -> top 3 (aquí 1 partido disponible)
fx2 = te.fixture("f2", "Cobreloa", "Everton", hours=6)
oddspapi.upcoming_fixtures = lambda frm, to: [fx2]
oddspapi.odds_by_tournaments = lambda ids: [{"fixtureId": "f2", "bookmakerOdds": {
    "pinnacle": te.book({"104": {"104": 1.80, "105": 2.05}}),
    "betano": te.book({"104": {"104": 1.95, "105": 1.85}})}}]
n_before = len(sent)
updates_q.append({"update_id": 70, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/buscar 40"}})
main.poll()
texts = [t for _, t, *_ in sent[n_before:]]
assert any("Buscando" in t for t in texts) and any("Búsqueda manual (40 h)" in t for t in texts), texts
st = store.load()
assert any(p["legs"][0]["fixture_id"] == "f2" and p["status"] == "candidate" for p in st["picks"].values())
assert "scan_request" not in st and st["manual"]["n"] == 1
# tope diario
config.MANUAL_SEARCHES_PER_DAY = 1
updates_q.append({"update_id": 80, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/buscar"}})
main.poll()
assert "Ya hiciste" in sent[-1][1]
print("OK /buscar")
