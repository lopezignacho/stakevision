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
telegram.updates = lambda offset, wait=0: [u for u in updates_q if u["update_id"] >= offset]
config.AUTO_SCAN_FALLBACK = False
config.AUTO_FREE = False   # se prueba aparte, al final
_real_end_of_today = main._end_of_today
main._end_of_today = lambda: store.now_utc() + timedelta(hours=48)   # pruebas antiguas: partidos de cualquier hora
_real_is_today = main._is_today
main._is_today = lambda iso: True
_scan = main.scan


def _scan_any_day(*a, **k):   # en las pruebas el escaneo "diario" se lanza varias veces el mismo día
    st_ = store.load()
    st_.pop("auto_scan_date", None)
    store.save(st_)
    return _scan(*a, **k)


main.scan = _scan_any_day

fx = te.fixture("f1", "Colo-Colo", "U. de Chile", hours=5)
oddspapi.markets = lambda force=False: te.MARKETS
oddspapi.upcoming_fixtures = lambda frm, to: [fx]
oddspapi.odds_by_tournaments = lambda ids: [{"fixtureId": "f1", "bookmakerOdds": {
    "pinnacle": te.book({"104": {"104": 1.80, "105": 2.05}}),
    "betano": te.book({"104": {"104": 1.95, "105": 1.85}})}}]
apifootball.context = lambda *a: None
from sv import commons, espn  # noqa: E402
espn.match_report = lambda *a, **k: None   # sin internet: ESPN "todavía no tiene el final"
commons.photo = lambda name: None
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
chan = [(ch, c) for ch, c in photos if ch != OWNER]
assert len(chan) == 2 and all(c and "STAKEVISION" in c for _, c in chan)   # imagen con el texto como pie

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
# fútbol: se espera el post partido de ESPN; si no llega en 6 h, se ofrece la celebración de siempre
assert st["picks"][pid]["recap_pending"] and not any(c and "Para Instagram" in c for ch, c in photos)
st["picks"][pid]["settled_at"] = (datetime.now(timezone.utc) - timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
store.save(st)
main.poll()
st = store.load()
assert not st["picks"][pid].get("recap_pending")
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
telegram.edit_caption = lambda chat, mid, text: edited.append((chat, mid, text))
# el verde salió a los canales con imagen (celebración) como respuesta al pick
assert sum(1 for ch, c in photos if ch in (VIP, config.FREE_CHANNEL) and c and "VERDE" in c) == 2
n_before_fix = len(sent)
updates_q += [
    {"update_id": 6, "callback_query": {"id": "z", "data": f"c:{pid}",
                                        "message": {"chat": {"id": OWNER}, "message_id": 9}}},
    {"update_id": 61, "callback_query": {"id": "z2", "data": f"L:{pid}",
                                         "message": {"chat": {"id": OWNER}, "message_id": 9}}},
]
main.poll()
st = store.load()
assert st["picks"][pid]["result"] == "L" and len(edited) == 2 and "corregido" in edited[0][2]
# la roja corregida sale como texto nuevo en ambos canales
assert sum(1 for ch, t, *_ in sent[n_before_fix:] if ch in (VIP, config.FREE_CHANNEL) and "ROJA" in t) == 2
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

# 6) Instagram conectado: vista previa con botón -> se publica cuando la imagen ya está en la web
from sv import instagram  # noqa: E402
config.INSTAGRAM_TOKEN = "token-de-prueba"
config.ROOT = tmp
posted = []
instagram.image_live = lambda pid: True
instagram.publish = lambda state, pid, caption: posted.append((pid, caption)) or "https://instagram.com/p/x"
instagram.refresh_token = lambda state: None
st = store.load()
pw = next(p for p in st["picks"].values() if p["legs"][0]["fixture_id"] == "f3")
pw.update(status="published", result=None, ig_kit_sent=False)
store.save(st)
_sup = main._recap_supported
main._recap_supported = lambda p: False   # este bloque prueba la celebración (picks sin post partido)
main._settle(st, pw, "W")
main._recap_supported = _sup
store.save(st)
btn = sent[-1]
assert btn[2] and btn[2][0][0][1] == f"ig:{pw['id']}", btn
assert os.path.exists(os.path.join(tmp, "docs", "ig", f"pick-{pw['id']}.jpg"))
updates_q.append({"update_id": 90, "callback_query": {"id": "i", "data": f"ig:{pw['id']}",
                                                      "message": {"chat": {"id": OWNER}, "message_id": 50}}})
main.poll()
assert posted and posted[0][0] == pw["id"] and "#Stakevision" in posted[0][1]
assert store.load()["picks"][pw["id"]]["ig_status"] == "posted" and "Publicado en Instagram" in sent[-1][1]
print("OK Instagram")

# 7) flujo nuevo: Elegir -> imagen con destinos -> VIP -> agregar Gratis -> Instagram
config.MANUAL_SEARCHES_PER_DAY = 10
fx4 = te.fixture("f4", "Audax Italiano", "Ñublense", hours=8)
oddspapi.upcoming_fixtures = lambda frm, to: [fx4]
oddspapi.odds_by_tournaments = lambda ids: [{"fixtureId": "f4", "bookmakerOdds": {
    "pinnacle": te.book({"104": {"104": 1.80, "105": 2.05}}),
    "betano": te.book({"104": {"104": 1.95, "105": 1.85}})}}]
main.scan()
st = store.load()
p4 = next(p for p in st["picks"].values() if p["legs"][0]["fixture_id"] == "f4")
cand = [b for _, t, b, _ in sent if b and b[0][0][1] == f"s:{p4['id']}"]
assert cand, "el candidato debe traer el botón Elegir"
buttons_set = []
telegram.set_buttons = lambda chat, mid, rows: buttons_set.append(rows)
n_ph = len(photos)
updates_q.append({"update_id": 100, "callback_query": {"id": "s1", "data": f"s:{p4['id']}",
                                                       "message": {"chat": {"id": OWNER}, "message_id": 70}}})
main.poll()
assert store.load()["picks"][p4["id"]]["status"] == "selected"
assert any(ch == OWNER and c and "listo para compartir" in c for ch, c in photos[n_ph:])
assert buttons_set and buttons_set[-1][0][0][1] == f"pv:{p4['id']}"
updates_q.append({"update_id": 101, "callback_query": {"id": "s2", "data": f"pv:{p4['id']}",
                                                       "message": {"chat": {"id": OWNER}, "message_id": 71}}})
main.poll()
p4s = store.load()["picks"][p4["id"]]
assert p4s["status"] == "published" and set(p4s["channel_msgs"]) == {"vip"} and not p4s["free"]
assert buttons_set[-1][0][1][1] == f"pg:{p4['id']}"   # ahora ofrece agregar a Gratis
updates_q.append({"update_id": 102, "callback_query": {"id": "s3", "data": f"pf:{p4['id']}",
                                                       "message": {"chat": {"id": OWNER}, "message_id": 71}}})
main.poll()
p4s = store.load()["picks"][p4["id"]]
assert set(p4s["channel_msgs"]) == {"vip", "free"} and p4s["free"]
n_vip = sum(1 for ch, *_ in sent if ch == VIP)
updates_q.append({"update_id": 103, "callback_query": {"id": "s4", "data": f"pi:{p4['id']}",
                                                       "message": {"chat": {"id": OWNER}, "message_id": 71}}})
posted.clear()
main.poll()
p4s = store.load()["picks"][p4["id"]]
assert p4s["ig_pre_status"] == "posted" and posted[-1][0] == f"pre-{p4['id']}" and "STAKEVISION · PICK GRATIS" in posted[-1][1] and "Probabilidad estimada" in posted[-1][1]
assert sum(1 for ch, *_ in sent if ch == VIP) == n_vip   # no se duplicó en VIP
print("OK elegir + destinos")

# 8) /envivo: partidos jugándose; el candidato vence a los 20 min, no al inicio
fx5 = te.fixture("f5", "Toluca", "Santos", hours=-0.5)
oddspapi.live_fixtures = lambda frm, to: [fx5]
oddspapi.odds_by_tournaments = lambda ids: [{"fixtureId": "f5", "bookmakerOdds": {
    "pinnacle": te.book({"104": {"104": 1.80, "105": 2.05}}),
    "betano": te.book({"104": {"104": 1.95, "105": 1.85}})}}]
from sv import espn  # noqa: E402
espn.live_info = lambda *a, **k: {"score": "1-0", "clock": "32'", "state": "in"}
updates_q.append({"update_id": 104, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/envivo"}})
main.poll()
st = store.load()
p5 = next(p for p in st["picks"].values() if p["legs"][0]["fixture_id"] == "f5")
assert p5["live"] and p5["status"] == "candidate" and p5["live_info"] == "1-0 · 32'"
assert any("EN VIVO" in t for _, t, *_ in sent[-3:])
main.poll()
assert store.load()["picks"][p5["id"]]["status"] == "candidate"   # no vence por haber empezado
print("OK /envivo")

# 9) pick aprobado con el flujo antiguo -> se ofrece la imagen para compartir; /compartir N la reenvía
fx6 = te.fixture("f6", "Porto", "PSV", hours=10)
oddspapi.upcoming_fixtures = lambda frm, to: [fx6]
oddspapi.odds_by_tournaments = lambda ids: [{"fixtureId": "f6", "bookmakerOdds": {
    "pinnacle": te.book({"104": {"104": 1.80, "105": 2.05}}),
    "betano": te.book({"104": {"104": 1.95, "105": 1.85}})}}]
main.scan()
st = store.load()
p6 = next(p for p in st["picks"].values() if p["legs"][0]["fixture_id"] == "f6")
updates_q.append({"update_id": 110, "callback_query": {"id": "o1", "data": f"f:{p6['id']}",
                                                       "message": {"chat": {"id": OWNER}, "message_id": 80}}})
n_ph = len(photos)
main.poll()   # publica con el flujo antiguo
main.poll()   # y ofrece la imagen con destinos
p6s = store.load()["picks"][p6["id"]]
assert p6s["status"] == "published" and p6s.get("share_msg")
assert buttons_set[-1][0][0][1] == "noop" and buttons_set[-1][1][0][1] == f"pi:{p6['id']}"
n = len(photos)
updates_q.append({"update_id": 111, "message": {"chat": {"id": OWNER, "type": "private"}, "text": f"/compartir {p6['id']}"}})
main.poll()
assert len(photos) == n + 1 and "listo para compartir" in photos[-1][1]
print("OK /compartir")

# 10) asistente de Instagram: responde comentarios y mensajes; lo dudoso te lo avisa
from sv import ig_inbox  # noqa: E402
calls = []
def fake_ig(method, path, state, **params):
    calls.append((method, path, params))
    if path == "me":
        return {"user_id": "999", "username": "stakevision"}
    if path == "me/media":
        return {"data": [{"id": "m1"}]}
    if path == "m1/comments":
        return {"data": [
            {"id": "c1", "text": "cuánto cuesta el vip?", "username": "juan", "timestamp": "2099-01-01T00:00:00+0000"},
            {"id": "c2", "text": "tengo 15 años jaja", "username": "nico", "timestamp": "2099-01-01T00:00:00+0000"},
            {"id": "c0", "text": "viejo", "username": "ana", "timestamp": "2000-01-01T00:00:00+0000"}]}
    if path == "me/conversations":
        return {"data": [{"id": "conv1", "updated_time": "2099-01-01T00:00:00+0000"}]}
    if path == "conv1":
        return {"messages": {"data": [
            {"id": "d1", "created_time": "2099-01-01T00:00:00+0000", "from": {"id": "55", "username": "pedro"},
             "message": "hola, donde veo el pick gratis?"}]}}
    return {"id": "ok"}
instagram._call = fake_ig
n = len(sent)
main.poll()
posts = [(p, prm) for m, p, prm in calls if m == "POST"]
assert ("c1/replies" in [p for p, _ in posts]) and not any(p == "c2/replies" or p == "c0/replies" for p, _ in posts)
dm = [prm for p, prm in posts if p == "999/messages"]
assert dm and "t.me/stakevision" in dm[0]["message"] and "+18" in dm[0]["message"]
assert any("menor" in t.lower() for _, t, *_ in sent[n:]), "el posible menor se avisa por Telegram"
calls.clear()
main.poll()   # no repite respuestas
assert not [1 for m, p, _ in calls if m == "POST"]
print("OK asistente Instagram")

# 11) post partido: imagen revista con datos de ESPN -> VIP, Gratis, Instagram y /titular
import io as _io  # noqa: E402
import json as _json  # noqa: E402
from PIL import Image as _Image  # noqa: E402
from sv import recap  # noqa: E402
fxr = _json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "espn_boca_vasco.json")))
cr = fxr["competition"]
rep_ = espn.report_from_event(fxr["event"], cr, *[next(x for x in cr["competitors"] if x["homeAway"] == s_)
                                                  for s_ in ("home", "away")])
assert [g["label"] for g in rep_["goals"]] == ["4'", "34'", "66'", "88'"] and rep_["away"]["agg"] == 3
assert recap.headline(rep_) == "REMONTADA" and recap.hero(rep_)["full"] == "Leandro Paredes"
assert recap.subline(rep_, "2026-10-21T00:30:00Z") == ("Global", "2-3 · Boca es finalista")
buf = _io.BytesIO()
_Image.new("RGB", (800, 1100), (40, 90, 160)).save(buf, "JPEG")
espn.match_report = lambda *a, **k: rep_
commons.photo = lambda name: (buf.getvalue(), {"author": "Autor", "license": "CC BY-SA 4.0", "page": "x",
                                               "text": "Foto: Autor / Wikimedia Commons · CC BY-SA 4.0 · modificada"})
st = store.load()
pr = st["picks"][p6["id"]]
pr.update(status="published", result=None)
pr.pop("recap", None)
main._settle(st, pr, "W")
store.save(st)
assert "Post partido" in photos[-1][1] and "Foto: Autor" in photos[-1][1], photos[-1]
assert os.path.exists(os.path.join(tmp, "docs", "ig", f"pick-res-{pr['id']}.jpg"))
assert pr["ig_kit_sent"] and not pr.get("recap_pending") and "Paredes" in pr["recap"]["ig"]
assert "Wikimedia Commons (CC BY-SA 4.0)" in pr["recap"]["ig"] and "+18" in pr["recap"]["ig"]
assert buttons_set[-1][0][0][1] == f"xv:{pr['id']}" and buttons_set[-1][1][0][1] == f"xi:{pr['id']}"
n = len(photos)
posted.clear()
for i, act in enumerate(("xv", "xf", "xi")):
    updates_q.append({"update_id": 200 + i, "callback_query": {"id": f"r{i}", "data": f"{act}:{pr['id']}",
                                                               "message": {"chat": {"id": OWNER}, "message_id": 70}}})
main.poll()
chans = [ch for ch, c in photos[n:]]
assert VIP in chans and config.FREE_CHANNEL in chans, photos[n:]
prs = store.load()["picks"][pr["id"]]
assert set(prs["recap"]["msgs"]) == {"vip", "free"} and prs["ig_res_status"] == "posted"
assert posted and posted[-1][0] == f"res-{pr['id']}" and "¡VERDE!" in posted[-1][1] and "Paredes" in posted[-1][1]
updates_q.append({"update_id": 210, "message": {"chat": {"id": OWNER, "type": "private"},
                                                "text": f"/titular {pr['id']} MARACA-NAZO"}})
main.poll()
assert "MARACA-NAZO" in photos[-1][1] and store.load()["picks"][pr["id"]]["recap"]["title"] == "MARACA-NAZO"
print("OK post partido")

# 12) adjuntar tu propia imagen: dentro del diseño y tal cual
telegram.download = lambda file_id: buf.getvalue()
pid_ = pr["id"]
for i, upd in enumerate([
        {"callback_query": {"id": "a1", "data": f"xp:{pid_}", "message": {"chat": {"id": OWNER}, "message_id": 71}}},
        {"message": {"chat": {"id": OWNER, "type": "private"}, "photo": [{"file_id": "f-small", "file_size": 10},
                                                                          {"file_id": "f-big", "file_size": 99}]}}]):
    updates_q.append({"update_id": 300 + i, **upd})
main.poll()
assert "¿Cómo la uso?" in sent[-1][1] and sent[-1][2][0][0][1] == f"xd:{pid_}", sent[-1]
assert os.path.exists(os.path.join(tmp, "data", "uploads", f"{pid_}.jpg")) or os.path.exists(main._upload_file(pr))
n = len(photos)
updates_q.append({"update_id": 310, "callback_query": {"id": "a2", "data": f"xd:{pid_}",
                                                       "message": {"chat": {"id": OWNER}, "message_id": 72}}})
main.poll()
r_ = store.load()["picks"][pid_]["recap"]
assert len(photos) == n + 1 and "Post partido" in photos[-1][1] and r_["photo_src"] == "user" and not r_["credit"]
assert "Wikimedia" not in r_["ig"]
updates_q.append({"update_id": 311, "callback_query": {"id": "a3", "data": f"xr:{pid_}",
                                                       "message": {"chat": {"id": OWNER}, "message_id": 73}}})
main.poll()
r_ = store.load()["picks"][pid_]["recap"]
assert r_["mode"] == "raw" and len(photos) == n + 2
# sin haber tocado «Adjuntar», una foto suelta no se usa
updates_q.append({"update_id": 312, "message": {"chat": {"id": OWNER, "type": "private"}, "photo": [{"file_id": "x"}]}})
main.poll()
assert "primero toca" in sent[-1][1]
print("OK imagen propia")

# 13) /postpartido de un partido que no fue pick
espn.find_recent = lambda a, b, days=3: (rep_, "2026-10-21T00:30:00Z")
commons.photo = lambda name: None
n = len(photos)
updates_q.append({"update_id": 400, "message": {"chat": {"id": OWNER, "type": "private"},
                                                "text": "/postpartido Vasco vs Boca | CONMEBOL · Sudamericana"}})
main.poll()
st = store.load()
nw = st["picks"]["N1"]
assert nw["status"] == "news" and len(photos) == n + 1 and "Post partido · partido N1" in photos[-1][1]
assert "🎯" not in nw["recap"]["ig"] and "Boca" in nw["recap"]["ig"]
pub = json.load(open(config.PUBLIC_HISTORY))
assert all(str(x.get("id")) != "N1" for x in pub["picks"])
print("OK /postpartido")

# 14) adelanto para historias y versión del pick con foto
fx7 = te.fixture("f7", "Benfica", "Sporting", hours=12)
oddspapi.upcoming_fixtures = lambda frm, to: [fx7]
oddspapi.odds_by_tournaments = lambda ids: [{"fixtureId": "f7", "bookmakerOdds": {
    "pinnacle": te.book({"104": {"104": 1.80, "105": 2.05}}),
    "betano": te.book({"104": {"104": 1.95, "105": 1.85}})}}]
main.scan()
st = store.load()
p7 = next(p for p in st["picks"].values() if p["legs"][0].get("fixture_id") == "f7")
stories = []
instagram.publish_story = lambda state, url: stories.append(url) or "id"
espn.preview = lambda *a, **k: None
commons.photo = lambda name, team=False: (buf.getvalue(), {"text": "Foto: Autor / Wikimedia Commons · CC BY 4.0 · modificada"})
n = len(photos)
for i, act in enumerate(("s", "ad", "ia")):
    updates_q.append({"update_id": 500 + i, "callback_query": {"id": f"t{i}", "data": f"{act}:{p7['id']}",
                                                               "message": {"chat": {"id": OWNER}, "message_id": 90 + i}}})
main.poll()
assert any("Adelanto del pick" in (c or "") for ch, c in photos[n:]), photos[n:]
assert os.path.exists(os.path.join(tmp, "docs", "ig", f"pick-story-{p7['id']}.jpg"))
assert stories and stories[-1].endswith(f"pick-story-{p7['id']}.jpg")
assert store.load()["picks"][p7["id"]]["ig_story_status"] == "posted"
updates_q.append({"update_id": 510, "message": {"chat": {"id": OWNER, "type": "private"}, "text": f"/adelanto {p7['id']} 10:00"}})
main.poll()
assert "Se revela a las 10:00" in photos[-1][1]
updates_q.append({"update_id": 511, "callback_query": {"id": "t9", "data": f"st:{p7['id']}",
                                                       "message": {"chat": {"id": OWNER}, "message_id": 95}}})
main.poll()
p7s = store.load()["picks"][p7["id"]]
assert p7s["pick_style"] == "coupon" and "listo para compartir" in photos[-1][1]   # antes del partido: cupón
flat_ = [d for row in main.SHARE_BUTTONS(p7s) for _, d in row]
assert not any(d.startswith(("th:", "dl:")) for d in flat_) and f"yp:{p7['id']}" in flat_
print("OK adelanto + pick en cupón")

# 15) adjuntar tu imagen para el pick (antes del partido)
for i, upd in enumerate([
        {"callback_query": {"id": "u1", "data": f"yp:{p7['id']}", "message": {"chat": {"id": OWNER}, "message_id": 96}}},
        {"message": {"chat": {"id": OWNER, "type": "private"}, "photo": [{"file_id": "g", "file_size": 5}]}}]):
    updates_q.append({"update_id": 600 + i, **upd})
main.poll()
assert sent[-1][2][0][0][1] == f"yd:{p7['id']}", sent[-1]
n = len(photos)
updates_q.append({"update_id": 610, "callback_query": {"id": "u2", "data": f"yd:{p7['id']}",
                                                       "message": {"chat": {"id": OWNER}, "message_id": 97}}})
main.poll()
p7s = store.load()["picks"][p7["id"]]
assert len(photos) == n + 1 and p7s["pick_style"] == "photo" and p7s["pick_photo_credit"] is None
updates_q.append({"update_id": 611, "callback_query": {"id": "u3", "data": f"yr:{p7['id']}",
                                                       "message": {"chat": {"id": OWNER}, "message_id": 98}}})
main.poll()
assert len(photos) == n + 2
print("OK imagen propia en el pick")

# 16) deshacer un descarte y modo día / noche
updates_q.append({"update_id": 700, "callback_query": {"id": "v1", "data": f"th:{p7['id']}",
                                                       "message": {"chat": {"id": OWNER}, "message_id": 99}}})
main.poll()
assert store.load()["picks"][p7["id"]]["theme"] == "light" and "listo para compartir" in photos[-1][1]
updates_q.append({"update_id": 701, "callback_query": {"id": "v2", "data": "xh:N1",
                                                       "message": {"chat": {"id": OWNER}, "message_id": 98}}})
main.poll()
assert store.load()["picks"]["N1"]["recap"]["theme"] == "light"
buttons_set.clear()
for i, act in enumerate(("r", "u")):
    updates_q.append({"update_id": 710 + i, "callback_query": {"id": f"w{i}", "data": f"{act}:{p7['id']}",
                                                               "message": {"chat": {"id": OWNER}, "message_id": 100}}})
main.poll()
p7s = store.load()["picks"][p7["id"]]
assert p7s["status"] == "selected" and buttons_set[0][0][0][1] == f"u:{p7['id']}", buttons_set
assert buttons_set[-1][0][0][1] == f"pv:{p7['id']}"
print("OK deshacer + modo día")

# 17) diseños que rotan y «Otro diseño»
from sv import layouts  # noqa: E402
st = store.load()
seq_before = (st.get("design_seq") or {}).get("recap", -1)
updates_q.append({"update_id": 800, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/postpartido Vasco vs Boca"}})
updates_q.append({"update_id": 801, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/postpartido Vasco vs Boca"}})
main.poll()
st = store.load()
n2, n3 = st["picks"]["N2"]["recap"]["layout"], st["picks"]["N3"]["recap"]["layout"]
assert n2 != n3 and n2 in layouts.RECAP_LAYOUTS and n3 in layouts.RECAP_LAYOUTS, (n2, n3)
updates_q.append({"update_id": 802, "callback_query": {"id": "z1", "data": "xl:N3",
                                                       "message": {"chat": {"id": OWNER}, "message_id": 120}}})
main.poll()
assert store.load()["picks"]["N3"]["recap"]["layout"] == layouts.cycle(n3, "recap")
updates_q.append({"update_id": 803, "callback_query": {"id": "z2", "data": f"dl:{p7['id']}",
                                                       "message": {"chat": {"id": OWNER}, "message_id": 121}}})
main.poll()
assert store.load()["picks"][p7["id"]]["pick_layout"] in layouts.PICK_LAYOUTS
for lay in layouts.RECAP_LAYOUTS:
    for th in ("dark", "light"):
        assert layouts.render_recap(recap.build(pr, rep_, None), lay, th)[:2] == b"\xff\xd8"
print("OK diseños que rotan")

# 18) solo Gratis
fx8 = te.fixture("f8", "Betis", "Sevilla", hours=12)
oddspapi.upcoming_fixtures = lambda frm, to: [fx8]
oddspapi.odds_by_tournaments = lambda ids: [{"fixtureId": "f8", "bookmakerOdds": {
    "pinnacle": te.book({"104": {"104": 1.80, "105": 2.05}}),
    "betano": te.book({"104": {"104": 1.95, "105": 1.85}})}}]
main.scan()
p8 = next(p for p in store.load()["picks"].values() if p["legs"][0].get("fixture_id") == "f8")
n = len(photos)
for i, act in enumerate(("s", "pg")):
    updates_q.append({"update_id": 900 + i, "callback_query": {"id": f"g{i}", "data": f"{act}:{p8['id']}",
                                                               "message": {"chat": {"id": OWNER}, "message_id": 130}}})
main.poll()
p8s = store.load()["picks"][p8["id"]]
assert set(p8s["channel_msgs"]) == {"free"} and p8s["status"] == "published" and p8s["free"]
assert buttons_set[-1][0][0][1] == f"pv:{p8['id']}" and buttons_set[-1][0][1][1] == "noop"
print("OK solo Gratis")

# 19) /invitar retirado (redirige a /enlace) y /anular de un enlace personal sin usar
tg_calls = []
telegram._call = lambda method, **kw: tg_calls.append((method, kw)) or {"invite_link": "https://t.me/+abc", "username": "StakevisionBot"}
updates_q.append({"update_id": 950, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/invitar Juan Pérez 30"}})
updates_q.append({"update_id": 951, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/enlace Pedro 30"}})
updates_q.append({"update_id": 952, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/anular Pedro"}})
main.poll()
assert any("/enlace" in t for _, t, *_ in sent[-4:]) and "anulado" in sent[-1][1]
assert not any(m_ == "createChatInviteLink" for m_, _ in tg_calls)
st = store.load()
assert any(c["name"] == "Pedro" and c.get("revoked") and c.get("days") == 30 for c in st["guest_codes"].values())
telegram._call = lambda *a, **k: True
print("OK enlace + anular")

# 20) contactos: /enlace, /start con código, /mensaje
tg_calls = []
def _fake_call(method, **kw):
    tg_calls.append((method, kw))
    return {"username": "StakevisionBot"} if method == "getMe" else {"invite_link": "https://t.me/+vip1"}
telegram._call = _fake_call
updates_q.append({"update_id": 1000, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/enlace Juan"}})
main.poll()
link = next(t for _, t, *_ in reversed(sent) if "t.me/StakevisionBot?start=" in t)
code = link.split("start=")[1].split()[0]
updates_q.append({"update_id": 1001, "message": {"chat": {"id": 555, "type": "private"},
                                                 "from": {"first_name": "Juanito", "username": "juanito"},
                                                 "text": f"/start {code}"}})
main.poll()
welcome = next(t for ch, t, *_ in sent if ch == 555)
assert "Hola Juan" in welcome and "https://t.me/+vip1" in welcome and "18" in welcome
assert any(ch == OWNER and "Juan" in t and "VIP" in t for ch, t, *_ in sent[-2:])
updates_q.append({"update_id": 1002, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/mensaje Juan hoy hay pick especial"}})
main.poll()
assert any(ch == 555 and "pick especial" in t for ch, t, *_ in sent)
# otra persona con el mismo código no recibe VIP
updates_q.append({"update_id": 1003, "message": {"chat": {"id": 556, "type": "private"}, "from": {"first_name": "Otro"},
                                                 "text": f"/start {code}"}})
main.poll()
assert "t.me/+vip1" not in next(t for ch, t, *_ in sent if ch == 556)
telegram._call = lambda *a, **k: True
print("OK contactos")

# 21) entretiempo
from datetime import datetime as _dt, timezone as _tz  # noqa: E402
fxh = _json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "espn_halftime.json")))
ch_ = fxh["competition"]
rep_ht = espn.report_from_event(fxh["event"], ch_, *[next(x for x in ch_["competitors"] if x["homeAway"] == s_)
                                                     for s_ in ("home", "away")])
espn.live_report = lambda *a, **k: rep_ht
st = store.load()
ph_ = st["picks"][p8["id"]]
ph_["kickoff"] = (_dt.now(_tz.utc) - timedelta(minutes=50)).strftime("%Y-%m-%dT%H:%M:%SZ")
ph_["legs"][0]["kickoff"] = ph_["kickoff"]
ph_["next_check"] = (_dt.now(_tz.utc) + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
store.save(st)
n = len(photos)
main.poll()
new = photos[n:]
assert any(ch == config.FREE_CHANNEL and c and "ENTRETIEMPO" in c for ch, c in new), new
assert store.load()["picks"][p8["id"]]["ht_done"] == "sent"
main.poll()
assert not any(c and "ENTRETIEMPO" in c for ch, c in photos[n + len(new):])
print("OK entretiempo")

# 22) comandos retirados: avisan cuál usar
n = len(sent)
for i_, cmd in enumerate(["/entretiempo Vasco vs Boca", "/buscar nba", "/combinada Thunder"]):
    updates_q.append({"update_id": 1100 + i_, "message": {"chat": {"id": OWNER, "type": "private"}, "text": cmd}})
main.poll()
assert len([1 for c, *_ in sent[n:] if c == OWNER]) >= 3 and not photos[len(photos):]
assert (store.load().get("manual") or {}).get("n", 0) <= 4
print("OK comandos retirados")

# 23) NBA: escaneo con opción A y B, argumentos, elegir B, calificar y alertas en vivo
from sv import formatting, nba  # noqa: E402
NBA_MARKETS = {
    "111": {"name": "Ganador", "type": "moneyline", "period": "result", "handicap": 0, "playerProp": False,
            "length": 2, "outcomes": {"111": "1", "112": "2"}},
    "11358": {"name": "Hándicap", "type": "spreads", "period": "result", "handicap": -4.5, "playerProp": False,
              "length": 2, "outcomes": {"11358": "1", "11359": "2"}},
    "11278": {"name": "Total", "type": "totals", "period": "result", "handicap": 228.5, "playerProp": False,
              "length": 2, "outcomes": {"11278": "Más", "11279": "Menos"}},
}
fxn = te.fixture("n1", "Boston Celtics", "New York Knicks", hours=8)
fxn["tournamentId"] = 132
_orig_markets = oddspapi.markets
oddspapi.markets = lambda force=False, sport_id=10: NBA_MARKETS if sport_id == 11 else te.MARKETS
oddspapi.upcoming_fixtures = lambda frm, to, sport_id=10: [fxn] if sport_id == 11 else []
oddspapi.odds_by_tournaments = lambda ids: [{"fixtureId": "n1", "bookmakerOdds": {
    "pinnacle": te.book({"111": {"111": 1.55, "112": 2.55}, "11358": {"11358": 1.95, "11359": 1.91},
                         "11278": {"11278": 1.92, "11279": 1.94}}),
    "betano": te.book({"111": {"111": 1.62, "112": 2.40}, "11358": {"11358": 1.99, "11359": 1.80},
                       "11278": {"11278": 1.88, "11279": 1.90}})}}]
games = [{"date": f"2026-10-{20 - i:02d}T23:00Z", "pf": 118 - i, "pa": 108, "home": i % 2 == 0, "opp": "X", "season": 2027}
         for i in range(8)]
nba.context = lambda h, a, k: {"event": "e1", "inverted": False,
                               "home": {"name": "Boston Celtics", "id": "2", "record": "3-0", "home_rec": "2-0",
                                        "road_rec": "1-0", "games": games, "rest_days": 2.0,
                                        "injuries": [], "espn_prob": 0.64},
                               "away": {"name": "New York Knicks", "id": "18", "record": "1-2", "home_rec": "1-0",
                                        "road_rec": "0-2", "games": [dict(g, pf=105, pa=110) for g in games],
                                        "rest_days": 0.9,
                                        "injuries": [{"name": "Jalen Brunson", "status": "Out", "key": True, "type": "Ankle"}],
                                        "espn_prob": 0.36}}
n = len(sent)
main.scan_nba(manual=True)
cand = [(t, b) for _, t, b, _ in sent[n:] if b and "NBA · Candidato" in t]
assert cand, sent[n:]
txt, btns = cand[0]
assert "Opción A" in txt and "Opción B" in txt and "A favor" in txt and "Brunson" in txt, txt
assert "hándicap de puntos" in txt or "puntos" in txt
pidn = btns[0][0][1].split(":")[1]
assert btns[0][1][1] == f"sb:{pidn}"
updates_q.append({"update_id": 1200, "callback_query": {"id": "nb", "data": f"sb:{pidn}",
                                                        "message": {"chat": {"id": OWNER}, "message_id": 140}}})
main.poll()
pn = store.load()["picks"][pidn]
assert pn["status"] == "selected" and pn["chosen_option"] == "B" and pn["legs"][0]["sport"] == "basketball"
assert "Betano" not in formatting.channel_post(pn)
assert main.grade_leg({"mtype": "moneyline", "outcome": "2"}, 101, 108) == "W"
nba.final_score = lambda h, a, k: (112, 104)
assert main._grade(pn)[2]
# alertas en vivo: favorito pierde por 12 en el 3er cuarto
def _fake_get(path, **kw):
    if path == "/scoreboard":
        return {"events": [{"id": "77", "status": {"type": {"state": "in"}, "period": 3, "displayClock": "6:10"},
                            "competitions": [{"competitors": [
                                {"homeAway": "home", "score": "70", "team": {"displayName": "Boston Celtics"}},
                                {"homeAway": "away", "score": "82", "team": {"displayName": "Miami Heat"}}]}]}]}
    if path == "/summary":
        return {"predictor": {"homeTeam": {"gameProjection": "68.0"}}, "winprobability": [{"homeWinPercentage": 0.22}]}
    return {}
nba._get = _fake_get
st = store.load()
al = nba.live_alerts(st)
assert al and "Posible remontada" in al[0] and "4.55" in al[0], al
assert not nba.live_alerts(st)   # una sola vez por cuarto
print("OK NBA")

# 24) /partido: un partido específico (NBA detectado por nombre y fútbol)
nba._get = lambda path, **kw: ({"events": [{"competitions": [{"competitors": [
    {"team": {"displayName": "Boston Celtics"}}, {"team": {"displayName": "New York Knicks"}}]}]}]}
    if path == "/scoreboard" else {})
oddspapi.live_fixtures = lambda frm, to, sport_id=10: []
fxn2 = dict(fxn, fixtureId="n1")
oddspapi.upcoming_fixtures = lambda frm, to, sport_id=10: [fxn2] if sport_id == 11 else [te.fixture("f1", "Colo-Colo", "U. de Chile", hours=6)]
st = store.load()
for p_ in st["picks"].values():   # liberar el partido de prueba
    if p_["legs"][0].get("fixture_id") == "n1":
        p_["status"] = "settled"
store.save(st)
n = len(sent)
updates_q.append({"update_id": 1300, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/partido Celtics vs Knicks"}})
main.poll()
got = [t for _, t, b, _ in sent[n:] if b and "Candidato" in t]
assert got and "🏀" in got[0] and "Opción A" in got[0], sent[n:]
oddspapi.odds_by_tournaments = lambda ids: [{"fixtureId": "f1", "bookmakerOdds": {
    "pinnacle": te.book({"104": {"104": 1.80, "105": 2.05}}),
    "betano": te.book({"104": {"104": 1.95, "105": 1.85}})}}]
oddspapi.markets = lambda force=False, sport_id=10: NBA_MARKETS if sport_id == 11 else te.MARKETS
n = len(sent)
updates_q.append({"update_id": 1301, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/partido Colo-Colo"}})
main.poll()
got = [t for _, t, b, _ in sent[n:] if b and "Candidato" in t]
assert got and "⚽" in got[0] and "Ambos marcan" in got[0], sent[n:]
print("OK /partido")

# 25) pick gratis automático: elige el más probable, avisa, permite cambiar y publica solo
config.AUTO_FREE = True
st = store.load()
for p_ in st["picks"].values():   # dejar libre el día de pruebas
    if p_["status"] in ("candidate", "selected", "published"):
        p_["status"] = "settled"
    p_.get("channel_msgs", {}).pop("free", None)
st.pop("auto_free", None)
store.save(st)
commons.photo = lambda name, team=False: None
oddspapi.live_fixtures = lambda frm, to, sport_id=10: []
fxa = te.fixture("fa1", "Colo-Colo", "U. de Chile", hours=6)
fxb = te.fixture("fb1", "Boca Juniors", "River Plate", hours=8)
oddspapi.upcoming_fixtures = lambda frm, to, sport_id=10: [] if sport_id == 11 else [fxa, fxb]
oddspapi.odds_by_tournaments = lambda ids: [
    {"fixtureId": "fa1", "bookmakerOdds": {   # justa 1.85 -> prob ~0.54
        "pinnacle": te.book({"104": {"104": 1.80, "105": 2.05}}),
        "betano": te.book({"104": {"104": 1.95, "105": 1.85}})}},
    {"fixtureId": "fb1", "bookmakerOdds": {   # más probable: justa ~1.70
        "pinnacle": te.book({"104": {"104": 1.66, "105": 2.30}}),
        "betano": te.book({"104": {"104": 1.78, "105": 2.10}})}}]
n = len(sent)
main.scan()
st = store.load()
af = st["auto_free"]
assert af["status"] == "pending", af
first = st["picks"][af["pid"]]
assert first["status"] == "selected" and first["auto_free"]
probs = sorted((st["picks"][pid].get("prob") for pid, _ in af["pool"]), reverse=True)
assert first["prob"] == probs[0], (first["prob"], probs)
note = [t for _, t, _, _ in sent[n:] if "Pick gratis automático de hoy" in (t or "")]
assert note and "Se publica sola" in note[0] and "Betano" not in note[0], sent[n:]
# cambiar por la siguiente opción
assert len(af["pool"]) > 1, af["pool"]
if True:
    updates_q.append({"update_id": 1400, "callback_query": {"id": "fo", "data": f"fo:{af['pid']}",
                                                            "message": {"chat": {"id": OWNER}, "message_id": 150}}})
    main.poll()
    st = store.load()
    assert st["picks"][first["id"]]["status"] == "candidate"
    assert st["auto_free"]["pid"] != first["id"] and st["auto_free"]["status"] == "pending"
# /gratis prueba: solo al dueño, no cambia nada
before = {k: v["status"] for k, v in st["picks"].items()}
n = len(sent)
updates_q.append({"update_id": 1450, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/gratis prueba"}})
main.poll()
st = store.load()
assert all(c == OWNER for c, *_ in sent[n:]), sent[n:]
assert any("Ranking de opciones" in (t_ or "") for _, t_, _, _ in sent[n:])
assert {k: v["status"] for k, v in st["picks"].items()} == before
# vence el plazo: se publica solo en VIP + Gratis
st["auto_free"]["at"] = main._iso(store.now_utc() - timedelta(minutes=1))
store.save(st)
n = len(sent)
main.poll()
st = store.load()
pa = st["picks"][st["auto_free"]["pid"]]
assert st["auto_free"]["status"] == "published", st["auto_free"]
assert "free" in pa["channel_msgs"] and "vip" in pa["channel_msgs"]
assert any(c == config.FREE_CHANNEL for c, *_ in sent[n:])
# no se elige otro el mismo día
assert not main._auto_free_choose(st)
# /gratis muestra el estado
n = len(sent)
updates_q.append({"update_id": 1451, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/gratis"}})
main.poll()
assert any("publicado" in (t or "") for _, t, _, _ in sent[n:])
updates_q.append({"update_id": 1452, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/gratis apagar"}})
main.poll()
assert store.load().get("auto_free_off")
# /gratis 37: un pick elegido por ti sale ya como gratis (al día siguiente, para no chocar con el de hoy)
st = store.load()
st.pop("auto_free_off", None)
for p_ in st["picks"].values():
    p_.get("channel_msgs", {}).pop("free", None)
    if p_["status"] in ("selected", "published"):
        p_["status"] = "settled"
cid = next(k for k, v in st["picks"].items() if v["status"] == "candidate")
store.save(st)
n = len(sent)
updates_q.append({"update_id": 1453, "message": {"chat": {"id": OWNER, "type": "private"}, "text": f"/gratis {cid}"}})
main.poll()
st = store.load()
pc = st["picks"][cid]
assert "free" in pc.get("channel_msgs", {}) and "vip" in pc["channel_msgs"] and pc["auto_free"], pc.get("status")
assert st["auto_free"]["pid"] == cid and st["auto_free"]["status"] == "published"
print("OK pick gratis automático")

# 26) regla: NBA exclusiva del VIP, previa VIP y corrección de un pick publicado
from sv import nba  # noqa: E402
st = store.load()
pn = st["picks"][pidn]   # pick NBA de la sección 23
pn["status"] = "selected"
pn["kickoff"] = main._iso(store.now_utc() + timedelta(minutes=20))
pn.pop("channel_msgs", None)
store.save(st)
flat = [d for row in main.SHARE_BUTTONS(pn) for _, d in row]
assert f"pv:{pidn}" in flat and not any(d.startswith(("pg:", "pf:", "pi:", "ad:")) for d in flat), flat
for act in ("pg", "pf", "pv"):
    updates_q.append({"update_id": 1500 + len(act) + ord(act[1]), "callback_query": {
        "id": act, "data": f"{act}:{pidn}", "message": {"chat": {"id": OWNER}, "message_id": 160}}})
nba.pregame = lambda p, m, ctx=None: f"🏀 PREVIA VIP · faltan {m} min"
n = len(sent)
main.poll()
st = store.load()
pn = st["picks"][pidn]
assert set(pn["channel_msgs"]) == {"vip"}, pn["channel_msgs"]
assert not any(c == config.FREE_CHANNEL for c, *_ in sent[n:])
assert "exclusiva del VIP" in main._force_free(st, pidn)
# previa VIP 20 min antes (salió en la misma revisión en que se publicó)
pre = [(c, t) for c, t, _, _ in sent[n:] if "PREVIA VIP" in (t or "")]
assert pre and all(c == VIP for c, _ in pre), sent[n:]
main.poll()
assert len([1 for _, t, _, _ in sent[n:] if "PREVIA VIP" in (t or "")]) == 1   # una sola vez
# corrección: si un NBA quedó en Gratis, se borra de ahí y se cambia la imagen del VIP
deleted, edited = [], []
telegram.delete_message = lambda c, m: deleted.append((c, m)) or True
telegram.edit_photo = lambda c, m, ph, caption=None: edited.append((c, m)) or True
st = store.load()
st["picks"][pidn]["channel_msgs"]["free"] = 999
st["auto_free"] = {"date": main._local_today(), "status": "published", "pid": pidn}
store.save(st)
import json  # noqa: E402
os.makedirs(os.path.join(config.ROOT, "data"), exist_ok=True)
rp = os.path.join(tmp, "repair.json")
_root = config.ROOT
config.ROOT = tmp
os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
with open(os.path.join(tmp, "data", "repair.json"), "w") as f:
    json.dump({"id": "t1", "pid": pidn}, f)
main.poll()
config.ROOT = _root
st = store.load()
assert deleted == [(config.FREE_CHANNEL, 999)] and edited and "free" not in st["picks"][pidn]["channel_msgs"]
assert st["auto_free"] == {}
print("OK NBA solo VIP + previa + corrección")

# 27) NBA: entretiempo (solo VIP) y final (VIP + Instagram, sin Gratis)
from sv import matchphoto, nbagame  # noqa: E402
matchphoto.for_scorer = lambda name, teams, sport='soccer': None
matchphoto.referent = lambda names, sport='soccer', tries=8: None


def _play(per, team, who, typ, text, shoot=False, made=False, val=0, ast=None):
    parts = [{"athlete": {"id": who}}] + ([{"athlete": {"id": ast}}] if ast else [])
    return {"period": {"number": per}, "team": {"id": team}, "participants": parts, "type": {"text": typ},
            "text": text, "shootingPlay": shoot, "scoringPlay": made, "scoreValue": val}


plays = []
for per in (1, 2, 3, 4):
    plays += [_play(per, "7", "j", "Jump Shot", "Jokic makes jumper (Murray assists)", True, True, 2, "m"),
              _play(per, "7", "m", "Jump Shot", "Murray makes three point jumper", True, True, 3),
              _play(per, "25", "s", "Driving Layup", "SGA makes layup", True, True, 2),
              _play(per, "25", "s", "Jump Shot", "SGA misses jumper", True, False, 0),
              _play(per, "7", "j", "Defensive Rebound", "Jokic defensive rebound")]
summ = {"plays": plays, "boxscore": {"players": [
    {"team": {"id": "7"}, "statistics": [{"keys": ["points", "rebounds", "assists"], "athletes": [
        {"athlete": {"id": "j", "displayName": "Nikola Jokić", "shortName": "N. Jokić"}, "stats": ["28", "13", "9"]},
        {"athlete": {"id": "m", "displayName": "Jamal Murray", "shortName": "J. Murray"}, "stats": ["21", "4", "6"]}]}]},
    {"team": {"id": "25"}, "statistics": [{"keys": ["points", "rebounds", "assists"], "athletes": [
        {"athlete": {"id": "s", "displayName": "Shai Gilgeous-Alexander", "shortName": "S. Gilgeous-Alexander"},
         "stats": ["34", "5", "7"]}]}]}], "teams": []}}
status_now = {"v": {"period": 2, "displayClock": "0.0", "type": {"name": "STATUS_HALFTIME", "state": "in", "completed": False}}}


def _comp(lines_h, lines_a):
    return [{"homeAway": "home", "team": {"id": "7", "displayName": "Denver Nuggets", "shortDisplayName": "Nuggets",
                                          "abbreviation": "DEN", "color": "0e2240", "alternateColor": "fec524"},
             "score": str(sum(lines_h)), "linescores": [{"displayValue": str(x)} for x in lines_h]},
            {"homeAway": "away", "team": {"id": "25", "displayName": "Oklahoma City Thunder", "shortDisplayName": "Thunder",
                                          "abbreviation": "OKC", "color": "007ac1", "alternateColor": "ef3b24"},
             "score": str(sum(lines_a)), "linescores": [{"displayValue": str(x)} for x in lines_a]}]


game = {"lines": ([30, 28], [27, 34])}
nba.find_event = lambda h, a, k: ({"id": "g1", "competitions": [{"competitors": _comp(*game["lines"])}]}, False)
nba._get = lambda path, **kw: (dict(summ, header={"competitions": [{"competitors": _comp(*game["lines"]),
                                                                       "status": status_now["v"]}]})
                               if path == "/summary" else {})
rep = nbagame.report("Denver Nuggets", "Oklahoma City Thunder", "2026-10-24T01:00:00Z", half=True)
assert rep["home"]["score"] == 58 and rep["away"]["score"] == 61 and rep["home"]["box"]["tpm"] == 2
assert rep["home"]["leaders"][0]["name"] == "Jamal Murray" and rep["away"]["box"]["fga"] == 4
st = store.load()
pn = st["picks"][pidn]
pn.update(status="published", kickoff=main._iso(store.now_utc() - timedelta(minutes=70)), price=1.87)
pn["legs"][0].update(home="Denver Nuggets", away="Oklahoma City Thunder", mtype="totals", outcome="Más de",
                      handicap=228.5, kickoff=pn["kickoff"])
pn.pop("ht_done", None)
store.save(st)
n = len(sent)
main.poll()
ht = [(c, t) for c, t, _, _ in sent[n:] if "ENTRETIEMPO NBA" in (t or "")]
assert ht and all(c == VIP for c, _ in ht), sent[n:]
assert "58-61" in ht[0][1] and "Murray" in ht[0][1]
assert store.load()["picks"][pidn]["nba_half"] == {"home": 58, "away": 61}
# final
game["lines"] = ([30, 28, 25, 29], [27, 34, 30, 27])
status_now["v"] = {"period": 4, "displayClock": "0.0", "type": {"name": "STATUS_FINAL", "state": "post", "completed": True}}
st = store.load()
pn = st["picks"][pidn]
assert main._recap(st, pn)
assert pn["recap"]["title"] == "THUNDER SE LO LLEVA", pn["recap"]["title"]
flat = [d for row in main.RECAP_BUTTONS(pn) for _, d in row]
assert f"xv:{pidn}" in flat and f"xi:{pidn}" in flat and not any(d.startswith("xf:") for d in flat)
assert "Shai Gilgeous-Alexander" in pn["recap"]["ig"] and "#NBA" in pn["recap"]["ig"]
assert "Betano" not in pn["recap"]["ig"] + pn["recap"]["tg"]
pn["recap"]["theme"] = "light"
assert main._recap(st, pn, reuse=True)
store.save(st)
print("OK NBA entretiempo y final")

# 28) Bet Builder: sugerencia, cuota real, publicación solo en VIP y calificación
from sv import builder  # noqa: E402
fake_legs = [{"player": f"Jugador {i}", "pid": str(i), "team": "Thunder", "side": "home" if i < 2 else "away",
              "stat": st_, "line": ln, "word": w, "hits": 9, "n": 10, "avg": av, "p": builder._p(9, 10),
              "label": f"Jugador {i}: {ln}+ {w}"}
             for i, (st_, ln, w, av) in enumerate([("pts", 20, "puntos", 26.1), ("reb", 6, "rebotes", 8.2),
                                                     ("tpm", 2, "triples", 3.1), ("ast", 5, "asistencias", 7.0)])]
assert builder.choose(fake_legs)["legs"][0]["stat"] in ("pts", "reb", "tpm", "ast")
builder.suggest = lambda h, a, k, sp: dict(builder.choose(fake_legs), home=h, away=a, event="g9", sport=sp, kickoff=k)
st = store.load()
ko_bb = main._iso(store.now_utc() + timedelta(hours=8))
n = len(sent)
assert main._builder_send(st, "Oklahoma City Thunder", "Denver Nuggets", ko_bb, "USA · NBA", "basketball")
store.save(st)
bb = [(t, b) for _, t, b, _ in sent[n:] if b and "Bet Builder sugerido" in (t or "")]
assert bb and "cuota mínima" in bb[0][0], sent[n:]
bid = bb[0][1][0][0][1].split(":")[1]
updates_q.append({"update_id": 1700, "callback_query": {"id": "bq", "data": f"bq:{bid}",
                                                        "message": {"chat": {"id": OWNER}, "message_id": 170}}})
updates_q.append({"update_id": 1701, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "3,10"}})
main.poll()
st = store.load()
pb = st["picks"][bid]
assert pb["status"] == "selected" and pb["price"] == 3.1 and pb["edge"] > 0, pb
flat = [d for row in main.SHARE_BUTTONS(pb) for _, d in row]
assert f"pv:{bid}" in flat and not any(d.startswith(("pg:", "pf:", "pi:")) for d in flat), flat
n = len(sent)
updates_q.append({"update_id": 1702, "callback_query": {"id": "pv", "data": f"pv:{bid}",
                                                        "message": {"chat": {"id": OWNER}, "message_id": 171}}})
updates_q.append({"update_id": 1703, "callback_query": {"id": "pg", "data": f"pg:{bid}",
                                                        "message": {"chat": {"id": OWNER}, "message_id": 171}}})
main.poll()
vip_posts = [t for c, t, _, _ in sent[n:] if c == VIP]
assert vip_posts and "BET BUILDER" in vip_posts[0] and "Jugador 0" in vip_posts[0] and "Probabilidad estimada" in vip_posts[0]
assert not any(c == config.FREE_CHANNEL for c, *_ in sent[n:])
# calificación: las 3 patas cumplidas
builder.final_box = lambda b: {x["pid"]: {x["stat"]: x["line"] + 1} for x in b["legs"]}
st = store.load()
pb = st["picks"][bid]
res, _sc, fin = main._grade(pb)
assert res == "W" and fin
builder.final_box = lambda b: {b["legs"][0]["pid"]: {b["legs"][0]["stat"]: 0}}
assert main._grade(pb)[0] == "L"
assert "✅" in formatting.result_post(dict(pb, result="W")) or "VERDE" in formatting.result_post(dict(pb, result="W"))
print("OK Bet Builder")

# 29) Fútbol en vivo (señales al descanso) y Bet Builder NBA antes del partido
from sv import livebb  # noqa: E402
m_ht = {"home": {"name": "Arsenal", "goals": 0, "corners": 4, "yellow": 2, "red": 0, "fouls": 8, "sot": 4, "shots": 9,
                 "players": [{"name": "Bukayo Saka", "shots": 3, "sot": 0}]},
        "away": {"name": "Chelsea", "goals": 0, "corners": 2, "yellow": 1, "red": 0, "fouls": 7, "sot": 3, "shots": 5,
                 "players": []}}
sig = livebb.signals(m_ht)
labels = [s_["label"] for s_ in sig]
assert "Arsenal: más de 5.5 córners" in labels and "Más de 8.5 córners en el partido" in labels, labels
assert "Más de 4.5 tarjetas en el partido" in labels and "Más de 0.5 goles" in labels and any("Saka" in x for x in labels)
mk = {"m1": {"type": "teamtotals-corners-team1", "period": "fulltime", "handicap": 5.5,
             "outcomes": {"o1": "Más", "o2": "Menos"}}}
row = {"bookmakerOdds": {"betano": {"markets": {"m1": {"outcomes": {"o1": {"players": {"0": {"price": 1.95}}},
                                                                  "o2": {"players": {"0": {"price": 1.80}}}}}}},
                         "pinnacle": {"markets": {"m1": {"outcomes": {"o1": {"players": {"0": {"price": 1.90}}},
                                                                     "o2": {"players": {"0": {"price": 1.95}}}}}}}}}
got = livebb._find_market(row, mk, sig[[s_["label"] for s_ in sig].index("Arsenal: más de 5.5 córners")])
assert got and got[0] == 1.95 and 1.9 < got[1] < 2.0, got
# NBA: el builder sale solo entre 40 y 25 min antes
calls_bb = []
_orig_send = main._builder_send
main._builder_send = lambda st_, h, a, ko, lg, sp, quiet=False: calls_bb.append((h, a, sp)) or True
ko_soon = store.now_utc() + timedelta(minutes=30)
ko_late = store.now_utc() + timedelta(hours=3)
nba._get = lambda path, **kw: ({"events": [
    {"id": "e1", "date": main._iso(ko_soon), "competitions": [{"competitors": [
        {"homeAway": "home", "team": {"displayName": "Boston Celtics"}}, {"homeAway": "away", "team": {"displayName": "New York Knicks"}}]}]},
    {"id": "e2", "date": main._iso(ko_late), "competitions": [{"competitors": [
        {"homeAway": "home", "team": {"displayName": "Miami Heat"}}, {"homeAway": "away", "team": {"displayName": "Orlando Magic"}}]}]}]}
    if path == "/scoreboard" else {})
st = store.load()
main._nba_builders_pregame(st, store.now_utc())
main._nba_builders_pregame(st, store.now_utc())
assert calls_bb == [("Boston Celtics", "New York Knicks", "basketball")], calls_bb
main._builder_send = _orig_send
print("OK en vivo + builder NBA previo")


# 30) /estado y /hoy
n = len(sent)
updates_q.append({"update_id": 1800, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/estado"}})
updates_q.append({"update_id": 1801, "message": {"chat": {"id": OWNER, "type": "private"}, "text": "/hoy"}})
main.poll()
est = next(t for c, t, *_ in sent[n:] if "Búsquedas hoy" in (t or ""))
assert "Gratis automático" in est and "Publicados en juego" in est
hoy = next(t for c, t, *_ in sent[n:] if (t or "").startswith("📅"))
assert "#" in hoy or "Todavía" in hoy
print("OK estado + hoy")

# 31) gratis solo del día + cancelar un pick publicado y buscar otro
main._end_of_today, main._is_today = _real_end_of_today, _real_is_today
st = store.load()
tomorrow = [p_ for p_ in st["picks"].values() if p_["status"] == "candidate"]
for p_ in st["picks"].values():
    if p_["status"] in ("candidate", "selected", "published"):
        p_["status"] = "settled"
    (p_.get("channel_msgs") or {}).pop("free", None)
c1 = dict(next(iter(st["picks"].values())))
c1.update(id="901", status="candidate", kind="simple", live=False, created_at=main._iso(store.now_utc()),
          kickoff=main._iso(main._end_of_today() + timedelta(hours=10)), price=1.80, prob=0.6, edge=0.0)
c1["legs"] = [dict(c1["legs"][0], sport="soccer", kickoff=c1["kickoff"])]
c1.pop("alt", None)
st["picks"]["901"] = c1
st.pop("auto_free", None)
st.pop("auto_free_off", None)
store.save(st)
st = store.load()
assert all(pid_ != "901" for pid_, _ in main._auto_pool(st, store.now_utc()))   # mañana: no sirve para el gratis
assert "no se juega hoy" in main._force_free(st, "901")
pub = dict(c1, id="902", status="published", channel_msgs={"free": 5, "vip": 6}, free=True,
           published_at=main._iso(store.now_utc()))
st["picks"]["902"] = pub
st["auto_free"] = {"date": main._local_today(), "status": "published", "pid": "902"}
store.save(st)
st = store.load()
assert main._free_given_today(st)
main._cancel_pick(st, "902", refree=False)
assert st["picks"]["902"]["status"] == "cancelled" and not main._free_given_today(st)
store.save(st)
store.export_public(st)
import json as _j  # noqa: E402
assert all(r["id"] != "902" for r in _j.load(open(config.PUBLIC_HISTORY))["picks"])
print("OK gratis del día + cancelar")
