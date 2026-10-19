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
telegram.edit_buttons_off = lambda *a, **k: None
telegram.answer = lambda *a, **k: None
telegram.updates = lambda offset: [u for u in updates_q if u["update_id"] >= offset]

fx = te.fixture("f1", "Colo-Colo", "U. de Chile", hours=5)
oddspapi.markets = lambda force=False: te.MARKETS
oddspapi.upcoming_fixtures = lambda frm, to: [fx]
oddspapi.odds_by_tournaments = lambda ids: [{"fixtureId": "f1", "bookmakerOdds": {
    "pinnacle": te.book({"104": {"104": 1.80, "105": 2.05}}),
    "betano": te.book({"104": {"104": 1.95, "105": 1.85}})}}]
oddspapi.scores = lambda fid: {"scores": {"0": {"participant1Score": 2, "participant2Score": 1}}}
apifootball.context = lambda *a: None

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

# 4) el partido termina -> pide resultado con sugerencia -> dueño confirma verde
p["kickoff"] = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
for l in p["legs"]:
    l["kickoff"] = p["kickoff"]
store.save(st)
main.poll()
req = sent[-1]
assert "Resultado del pick" in req[1] and "VERDE" in req[1]   # 2-1: ambos marcan -> verde
updates_q.append({"update_id": 6, "callback_query": {"id": "z", "data": f"W:{pid}",
                                                     "message": {"chat": {"id": OWNER}, "message_id": 9}}})
main.poll()
st = store.load()
assert st["picks"][pid]["result"] == "W"
import json  # noqa: E402
pub = json.load(open(config.PUBLIC_HISTORY))
assert pub["summary"]["wins"] == 1 and pub["picks"][0]["result"] == "W"
print("OK flujo completo:", len(sent), "mensajes simulados")
