"""Punto de entrada.

    python -m sv.main scan    # busca valor y te manda candidatos (1 vez al día)
    python -m sv.main poll    # procesa tus botones, publica y pide resultados (cada ~10 min)
    python -m sv.main setup   # descarga la lista de mercados (1 vez)
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import timedelta

from . import apifootball, config, formatting, oddspapi, store, telegram
from .value import build_picks, selections_for_fixture

CANDIDATE_BUTTONS = lambda pid: [  # noqa: E731
    [("🖼 Elegir y generar imagen", f"s:{pid}")],
    [("❌ Descartar", f"r:{pid}")],
]


def SHARE_BUTTONS(p: dict) -> list:
    """Destinos para un pick elegido. Cada uno se puede usar; lo ya hecho queda marcado."""
    pid, msgs = p["id"], p.get("channel_msgs") or {}
    rows = []
    vip_done, free_done = "vip" in msgs, "free" in msgs
    if not vip_done:
        rows.append([("👑 Enviar a VIP", f"pv:{pid}"), ("👑🎁 VIP + Gratis", f"pf:{pid}")])
    elif not free_done:
        rows.append([("✅ En VIP", "noop"), ("🎁 Agregar a Gratis", f"pf:{pid}")])
    else:
        rows.append([("✅ En VIP + Gratis", "noop")])
    st = p.get("ig_pre_status")
    rows.append([("✅ Instagram" if st == "posted" else "⏳ Instagram en cola" if st == "queued"
                  else "📸 Compartir en Instagram", "noop" if st in ("queued", "posted") else f"pi:{pid}")])
    photo = p.get("pick_style") == "photo"
    rows.append([("🧾 Volver al cupón" if photo else "📰 Versión con foto", f"st:{pid}"),
                 ("🖼 Adjuntar mi imagen", f"yp:{pid}")])
    if photo:
        rows.append([("🌙 Modo noche" if p.get("theme") == "light" else "☀️ Modo día", f"th:{pid}"),
                     ("📲 Adelanto (historia)", f"ad:{pid}")])
    else:
        rows.append([("📲 Adelanto (historia)", f"ad:{pid}")])
    if not msgs and not st:
        rows.append([("❌ Descartar", f"r:{pid}")])
    return rows


def _share_panel(state: dict, p: dict) -> None:
    """Te manda la imagen del pick con los botones de destino (VIP, VIP + Gratis, Instagram)."""
    owner = state.get("owner_chat")
    if not owner:
        return
    image = _pick_image(p)
    head = (f"🖼 <b>Pick #{p['id']} listo para compartir</b>\n"
            "Elige dónde publicarlo (puedes usar varios botones). Este es el texto que sale con la imagen:")
    text = formatting.channel_post(p)
    full = f"{head}\n\n{text}"
    together = bool(image) and formatting.caption_fits(full)
    caption = full if together else head
    msg = telegram.send_photo(owner, image, caption=caption) if image else telegram.send(owner, caption)
    p["share_msg"] = msg["message_id"]
    telegram.set_buttons(owner, p["share_msg"], SHARE_BUTTONS(p))
    if not together:
        telegram.send(owner, text)


def _share_command(state: dict, text: str) -> None:
    owner = state["owner_chat"]
    parts = text.split()
    pid = parts[1].lstrip("#") if len(parts) > 1 else ""
    p = state["picks"].get(pid)
    if not p:
        recent = [x for x in state["picks"].values() if x["status"] in ("selected", "published", "settled")]
        recent.sort(key=lambda x: int(x["id"]), reverse=True)
        lista = "\n".join(f"#{x['id']} · {formatting.escape(x['legs'][0]['home'])} vs "
                           f"{formatting.escape(x['legs'][0]['away'])}" for x in recent[:6])
        telegram.send(owner, "Usa /compartir y el número del pick, por ejemplo /compartir 8"
                      + (f"\n\nÚltimos picks:\n{lista}" if lista else ""))
        return
    if p["status"] == "rejected" and _expires(p) > store.now_utc():   # recuperar un descarte
        p["status"] = "selected"
        p.pop("prev_status", None)
        telegram.send(owner, f"↩️ Recuperé el pick #{p['id']}.")
    if p["status"] in ("selected", "published"):
        _share_panel(state, p)
    elif p["status"] in ("settled", "news") and p.get("recap") and os.path.exists(_recap_file(p)):
        _recap_panel(state, p)
    elif p["status"] == "settled" and p.get("result") == "W":
        p["ig_kit_sent"] = False
        if p.get("ig_status") not in ("queued", "posted"):
            p.pop("ig_status", None)
        _instagram_kit(state, p)
    else:
        telegram.send(owner, f"El pick #{pid} no se puede compartir ({p['status']}"
                      + (f", resultado {p.get('result')}" if p.get("result") else "") + ").")


def _expires(p: dict):
    """Un candidato en vivo vence a los 20 minutos (las cuotas cambian); uno normal, al empezar el partido."""
    if p.get("live"):
        return store.parse_ts(p["created_at"]) + timedelta(minutes=config.LIVE_CANDIDATE_MIN)
    return store.parse_ts(p["kickoff"])
RESULT_BUTTONS = lambda pid: [  # noqa: E731
    [("✅ Verde", f"W:{pid}"), ("❌ Roja", f"L:{pid}"), ("↩️ Nula", f"V:{pid}")],
]


def _local_today() -> str:
    from zoneinfo import ZoneInfo
    return store.now_utc().astimezone(ZoneInfo(config.TIMEZONE)).date().isoformat()


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- escaneo diario
def scan(hours: int | None = None, top: int | None = None, manual: bool = False, live: bool = False) -> None:
    state = store.load()
    if not state["owner_chat"]:
        print("Aún no está vinculado tu chat. Escribe al bot: /vincular <tu código>")
        return
    if not manual and not live:   # el escaneo diario sale una sola vez (lo pueden lanzar dos caminos)
        today = _local_today()
        if state.get("auto_scan_date") == today:
            print("El escaneo de hoy ya salió.")
            return
        state["auto_scan_date"] = today
        store.save(state)
    now = store.now_utc()
    hours = min(hours or config.WINDOW_END_H, 47)
    if live:
        title = "🔴 Búsqueda en vivo"
        frm, to = now - timedelta(minutes=config.LIVE_MAX_MINUTE + 20), now
    else:
        title = f"🔎 Búsqueda manual ({hours} h)" if manual else "🔎 Escaneo de hoy"
        frm, to = now + timedelta(hours=config.WINDOW_START_H), now + timedelta(hours=hours)

    markets = oddspapi.markets()
    fixtures = (oddspapi.live_fixtures if live else oddspapi.upcoming_fixtures)(_iso(frm), _iso(to))
    fixtures = [f for f in fixtures if frm <= store.parse_ts(f["startTime"]) <= to]
    by_id = {f["fixtureId"]: f for f in fixtures}
    print(f"Partidos con cuotas de Betano en la ventana: {len(by_id)}")

    counts: dict[int, int] = {}
    for f in fixtures:
        t = f["tournamentId"]
        if t in config.TOURNAMENTS:
            counts[t] = counts.get(t, 0) + 1
    order = list(config.TOURNAMENTS)
    tournaments = sorted(counts, key=order.index)[:config.MAX_TOURNAMENTS_PER_CALL * config.ODDS_BATCHES]
    names = {t: config.TOURNAMENTS[t] for t in tournaments}
    print("Ligas analizadas hoy: " + "; ".join(f"{names[t]} ({counts[t]})" for t in tournaments))
    if not tournaments:
        telegram.send(state["owner_chat"], f"{title}: ninguna de tus ligas tiene partidos "
                      + ("jugándose ahora." if live else f"en las próximas {hours} horas."))
        return

    odds_rows = oddspapi.odds_by_tournaments(tournaments)
    selections, analyzed = [], 0
    for row in odds_rows:
        fx = by_id.get(row.get("fixtureId"))
        if fx and len(row.get("bookmakerOdds") or {}) == 2:
            analyzed += 1
            selections += selections_for_fixture(fx, row, markets)

    # No repetir partidos que ya tienen un candidato pendiente o un pick publicado.
    busy = {l["fixture_id"] for p in state["picks"].values()
            if p["status"] in ("candidate", "published") for l in p["legs"]}
    selections = [x for x in selections if x.fixture_id not in busy]
    picks = build_picks(selections, max_n=top, min_n=top)

    in_range = sorted((x for x in selections if config.ODDS_MIN <= x.price <= config.ODDS_MAX),
                      key=lambda x: x.edge, reverse=True)[:3]
    best = "\n".join(f"• {formatting.outcome_label({**x.__dict__})} ({x.home} vs {x.away}) @ {x.price:.2f}: "
                     f"{'+' if x.edge >= 0 else ''}{formatting.pct(x.edge)}" for x in in_range)
    if not picks:
        if best:
            best = "\n\nLo más cercano dentro del rango (valor frente a la cuota justa):\n" + best
        telegram.send(state["owner_chat"],
                      f"{title}: {len(tournaments)} ligas, {analyzed} partidos con cuotas de ambas casas, "
                      f"{len(selections)} cuotas comparadas. "
                      f"Ninguna cumple valor ≥ {formatting.pct(config.MIN_EDGE)} dentro de "
                      f"{config.ODDS_MIN:.2f}–{config.ODDS_MAX:.2f}. No hay picks para proponer." + best)
        store.save(state)
        return

    n_val = sum(1 for p in picks if p.tier == "valor")
    telegram.send(state["owner_chat"],
                  f"{title}: {len(tournaments)} ligas, {analyzed} partidos, {len(selections)} cuotas comparadas.\n"
                  f"{'Tu top ' + str(len(picks)) if manual else 'Te envío ' + str(len(picks)) + ' candidatos'}: "
                  f"{n_val} 🟢 con valor y {len(picks) - n_val} ⚖️ de cuota justa.\n"
                  f"Sugerencia: 1 para el canal gratis (✅ VIP + Gratis) y de 2 a 4 para el VIP. "
                  f"Revisa cada cuota en tu app antes de aprobar.")
    try:
        from . import history
        history.update(max_fetch=5)   # completar el historial antes de calcular la forma de los equipos
    except Exception:
        traceback.print_exc()
    for p in picks:
        d = p.to_dict()
        for leg in d["legs"]:
            leg["label"] = formatting.outcome_label(leg)
            leg["context"] = apifootball.context(leg["home"], leg["away"], leg["kickoff"])
        state["seq"] += 1
        pid = str(state["seq"])
        d.update(id=pid, status="candidate", created_at=_iso(now), stake_v=2)
        if live:
            d["live"] = True
            try:
                from . import espn
                info = espn.live_info(d["legs"][0]["home"], d["legs"][0]["away"], d["legs"][0]["kickoff"])
            except Exception:
                info = None
            if info:
                d["live_info"] = f"{info['score']} · {info['clock']}"
        d["analysis"] = formatting.analysis(d)
        msg = telegram.send(state["owner_chat"], formatting.owner_candidate(d), CANDIDATE_BUTTONS(pid))
        d["owner_msg"] = msg["message_id"]
        state["picks"][pid] = d
        store.save(state)  # guardar tras cada envío por si algo falla a mitad


# ---------------------------------------------------------------- resultados
def grade_leg(l: dict, h: int, a: int) -> str | None:
    """Compara la apuesta con el marcador de 90': 'W' verde, 'L' roja, 'V' nula, None si no sé leerla."""
    t, o, line = l.get("mtype", ""), str(l.get("outcome", "")).strip().lower(), l.get("handicap")
    if t == "1x2":
        won = {"1": h > a, "x": h == a, "2": h < a}.get(o)
    elif t == "bothteamsscore":
        won = (h > 0 and a > 0) == o.startswith(("s", "y"))
    elif t in ("totals", "teamtotals-team1", "teamtotals-team2") and line is not None:
        goals = h + a if t == "totals" else (h if t.endswith("1") else a)
        diff = goals - float(line)
        if diff == 0:
            return "V"
        won = diff > 0 if o.startswith(("más", "mas", "over")) else diff < 0
    elif t in ("toscore-team1", "toscore-team2"):
        goals = h if t.endswith("1") else a
        won = (goals > 0) == o.startswith(("s", "y"))
    elif t == "drawnobet" and o in ("1", "2"):
        if h == a:
            return "V"
        won = (h > a) if o == "1" else (a > h)
    elif t == "spreads" and line is not None and o in ("1", "2"):
        # la línea viene expresada para el local; las de cuarto (x.25/x.75) no se usan
        diff = (h - a + float(line)) if o == "1" else (a - h - float(line))
        if diff == 0:
            return "V"
        won = diff > 0
    else:
        won = None
    if won is None:
        return None
    return "W" if won else "L"


def _grade(pick: dict) -> tuple[str | None, list, bool]:
    """Busca el marcador final de cada partido y califica el pick.
    Devuelve (resultado, marcadores, todos_terminados). Una doble es roja si falla
    una selección; nula si ambas se devuelven; verde en otro caso."""
    scores, results = [], []
    for l in pick["legs"]:
        sc = apifootball.final_score(l["home"], l["away"], l["kickoff"])
        scores.append(sc)
        results.append(grade_leg(l, *sc) if sc else None)
    finished = all(scores)
    if not finished or None in results:
        return None, scores, finished
    if "L" in results:
        return "L", scores, True
    if all(r == "V" for r in results):
        return "V", scores, True
    return "W", scores, True


def _post(chat, text: str, image: bytes | None) -> int:
    """Publica el pick con su imagen. Si el texto cabe, va como pie de foto; si no,
    foto y luego el texto. Si la imagen falla, sale solo el texto."""
    if image:
        try:
            if formatting.caption_fits(text):
                return telegram.send_photo(chat, image, caption=text)["message_id"]
            telegram.send_photo(chat, image)
        except Exception as e:
            print(f"No se pudo enviar la imagen: {e}")
    return telegram.send(chat, text)["message_id"]


def _pick_photo_file(p: dict) -> str:
    return os.path.join(config.ROOT, "data", "pickimg", f"{p['id']}.jpg")


def _make_pick_photo(p: dict, user_photo: bytes | None = None, reuse: bool = False) -> bool:
    """Versión del pick con foto real del equipo (Commons, o la tuya) y colores de ESPN. Se guarda para reutilizarla."""
    from . import commons, espn, postimage, teaser
    l = p["legs"][0]
    teams = espn.preview(l["home"], l["away"], l["kickoff"])
    side = {"1": "home", "2": "away"}.get(str(l.get("outcome")), "home")
    names = [l[side], l["away" if side == "home" else "home"]]
    if teams:
        names = [teams[side]["name"], teams["away" if side == "home" else "home"]["name"]] + names
    cache = _upload_file(p, "pickphoto")
    photo = (user_photo, None) if user_photo else None
    if not photo and reuse and os.path.exists(cache):
        with open(cache, "rb") as f:
            photo = (f.read(), p.get("pick_photo_credit"))
    for n in ([] if photo or reuse else dict.fromkeys(names)):
        photo = commons.photo(n, team=True)
        if photo:
            break
    if photo:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "wb") as f:
            f.write(photo[0])
    image = postimage.render_pick_photo(teaser.pick_photo_data(p, teams, photo), p.get("theme") or "dark")
    path = _pick_photo_file(p)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(image)
    p["pick_photo_credit"] = photo[1] if photo else None
    return True


def _pick_image(p: dict) -> bytes | None:
    if p.get("pick_style") == "photo" and os.path.exists(_pick_photo_file(p)):
        with open(_pick_photo_file(p), "rb") as f:
            return f.read()
    try:
        from . import postimage
        return postimage.render(p)
    except Exception:
        traceback.print_exc()
        return None


def _publish(state: dict, p: dict, free: bool) -> None:
    """Publica en VIP (y en Gratis si free). Si ya estaba en un canal, no lo repite."""
    text = formatting.channel_post(p)
    image = _pick_image(p)
    msgs = p.setdefault("channel_msgs", {})
    vip = state.get("vip_chat")
    if vip and "vip" not in msgs:
        msgs["vip"] = _post(vip, text, image)
    if free and "free" not in msgs:
        msgs["free"] = _post(config.FREE_CHANNEL, text, image)
    if p["status"] != "published":
        p.update(status="published", published_at=_iso(store.now_utc()), has_photo=bool(image))
    p["free"] = "free" in msgs


def _result_image(state: dict, p: dict) -> bytes | None:
    """Imagen de resultado para los canales: verde (celebración) o nula. Las rojas van solo en texto."""
    if p.get("result") not in ("W", "V"):
        return None
    try:
        from . import postimage
        return postimage.render_win(p, _streak(state, p) if p["result"] == "W" else 1, p["result"])
    except Exception:
        traceback.print_exc()
        return None


def _post_result(state: dict, p: dict, text: str) -> None:
    image = _result_image(state, p)
    p["result_msgs"], p["result_is_photo"] = {}, {}
    for where, mid in (p.get("channel_msgs") or {}).items():
        chat = state["vip_chat"] if where == "vip" else config.FREE_CHANNEL
        try:
            if image:
                try:
                    p["result_msgs"][where] = telegram.send_photo(chat, image, caption=text, reply_to=mid)["message_id"]
                    p["result_is_photo"][where] = True
                    continue
                except Exception as e:  # noqa: BLE001
                    print(f"No se pudo enviar la imagen del resultado en {where}: {e}")
            p["result_msgs"][where] = telegram.send(chat, text, reply_to=mid)["message_id"]
        except telegram.TelegramError as e:
            print(f"No se pudo publicar resultado en {where}: {e}")


def _settle(state: dict, p: dict, result: str) -> None:
    p.update(result=result, status="settled", settled_at=_iso(store.now_utc()))
    _post_result(state, p, formatting.result_post(p))
    _after_result(state, p)


def _remind(state: dict, p: dict, now) -> None:
    """Aviso en los canales cuando faltan ~30 minutos para el partido."""
    if p["status"] != "published" or p.get("reminded"):
        return
    kick = store.parse_ts(p["kickoff"])
    start = kick - timedelta(minutes=config.REMINDER_BEFORE_MIN)
    if not (start <= now < kick):
        return
    p["reminded"] = True
    pub = p.get("published_at")
    if pub and store.parse_ts(pub) > start - timedelta(minutes=5):
        return  # se publicó a última hora: el pick recién salió, no hace falta recordarlo
    text = formatting.pre_kickoff(p, int((kick - now).total_seconds() // 60))
    for where, mid in (p.get("channel_msgs") or {}).items():
        chat = state["vip_chat"] if where == "vip" else config.FREE_CHANNEL
        try:
            telegram.send(chat, text, reply_to=mid)
        except telegram.TelegramError as e:
            print(f"No se pudo enviar el aviso en {where}: {e}")


def _auto_result(state: dict, p: dict, owner, now, last_kick) -> None:
    """Califica solo el pick con el marcador final y lo publica. Si el marcador aún no
    está, reintenta cada RESULT_RETRY_MIN; si no se puede leer, te lo pregunta."""
    try:
        res, scores, finished = _grade(p)
    except Exception:
        traceback.print_exc()
        res, scores, finished = None, [], False
    for l, sc in zip(p["legs"], scores):
        if sc:
            l["score"] = list(sc)   # marcador final para la web
    if res:
        _settle(state, p, res)
        p["auto_result"] = True
        telegram.send(owner, formatting.owner_auto_result(p, scores), [[("✏️ Corregir", f"c:{p['id']}")]])
        return
    gave_up = now >= last_kick + timedelta(minutes=config.RESULT_GIVE_UP_MIN)
    if finished or gave_up:  # terminó pero el mercado no se sabe leer, o nunca apareció el marcador
        telegram.send(owner, formatting.owner_result_request(p, None, scores), RESULT_BUTTONS(p["id"]))
        p["result_asked"] = True
    else:
        p["next_check"] = _iso(now + timedelta(minutes=config.RESULT_RETRY_MIN))


def _streak(state: dict, p: dict) -> int:
    """Verdes seguidos terminando en este pick (las nulas no cortan la racha)."""
    done = sorted((x for x in state["picks"].values() if x.get("status") == "settled"),
                  key=lambda x: (x.get("settled_at") or "", x["kickoff"]))
    n = 0
    for x in reversed(done[:done.index(p) + 1] if p in done else done):
        if x.get("result") == "V":
            continue
        if x.get("result") != "W":
            break
        n += 1
    return max(n, 1)


def _instagram_kit(state: dict, p: dict) -> None:
    """Pick verde: imagen de celebración + texto para Instagram.
    Con Instagram conectado, te llega la vista previa con un botón para publicar;
    sin conexión, te llega el material para subirlo a mano."""
    owner = state.get("owner_chat")
    if not owner or p.get("ig_kit_sent") or p.get("result") != "W":
        return
    p["ig_kit_sent"] = True
    try:
        from . import instagram, postimage
        streak = _streak(state, p)
        image = postimage.render_win(p, streak)
        caption = formatting.instagram_caption(p, streak)
        p["ig_caption"] = caption
        p["ig_kit_mode"] = "api" if instagram.enabled(state) else "manual"
        if instagram.enabled(state):
            instagram.save_image(p["id"], image)   # la web la sirve para que Instagram la descargue
            telegram.send_photo(owner, image, caption=(
                f"📸 <b>Celebración para Instagram</b> · pick #{p['id']} ✅\n"
                "Este es el texto que se publicará (abajo). ¿Lo subo a Instagram?"))
            telegram.send(owner, f"<pre>{formatting.escape(caption)}</pre>",
                          [[("📸 Publicar en Instagram", f"ig:{p['id']}"), ("No publicar", f"ign:{p['id']}")]])
        else:
            telegram.send_photo(owner, image, caption=(
                f"📸 <b>Para Instagram</b> · pick #{p['id']} ✅\n"
                "Guarda la imagen y copia el texto de abajo (tócalo para copiarlo)."))
            telegram.send(owner, f"<pre>{formatting.escape(caption)}</pre>")
    except Exception:
        traceback.print_exc()


def _instagram_queue(state: dict, now) -> None:
    """Publica en Instagram los verdes que aprobaste, cuando la imagen ya está en la web."""
    from . import instagram
    owner = state.get("owner_chat")
    jobs = []
    for p in state["picks"].values():
        if p.get("ig_status") == "queued":
            jobs.append((p, "ig_status", p["id"], p.get("ig_caption") or ""))
        if p.get("ig_pre_status") == "queued":
            jobs.append((p, "ig_pre_status", f"pre-{p['id']}", p.get("ig_pre_caption") or ""))
        if p.get("ig_res_status") == "queued":
            jobs.append((p, "ig_res_status", f"res-{p['id']}", p.get("ig_res_caption") or ""))
        if p.get("ig_story_status") == "queued":
            jobs.append((p, "ig_story_status", f"story-{p['id']}", None))
    for p, field, key, caption in jobs:
        if not instagram.image_live(key):
            continue   # la web aún no la publica; se reintenta en la próxima revisión
        try:
            if field == "ig_story_status":
                instagram.publish_story(state, instagram.image_url(key))
                link = ""
            else:
                link = instagram.publish(state, key, caption)
            p[field] = "posted"
            if field == "ig_story_status" and (p.get("teaser") or {}).get("msg") and owner:
                telegram.set_buttons(owner, p["teaser"]["msg"], TEASER_BUTTONS(p))
            if field == "ig_pre_status" and p.get("share_msg") and owner:
                telegram.set_buttons(owner, p["share_msg"], SHARE_BUTTONS(p))
            if field == "ig_res_status" and (p.get("recap") or {}).get("panel") and owner:
                telegram.set_buttons(owner, p["recap"]["panel"], RECAP_BUTTONS(p))
            if owner:
                what = "Historia publicada" if field == "ig_story_status" else "Publicado"
                telegram.send(owner, f"✅ {what} en Instagram (pick #{p['id']})" + (f"\n{link}" if link else ""))
        except instagram.InstagramError as e:
            tries = field.replace("status", "tries")
            p[tries] = p.get(tries, 0) + 1
            print(f"Instagram falló (pick {p['id']}): {e}")
            if p[tries] >= 3:
                p[field] = "failed"
                if owner:
                    telegram.send(owner, f"⚠️ No pude publicar en Instagram el pick #{p['id']}: "
                                         f"{formatting.escape(str(e))}\nPuedes subirlo a mano con la imagen que te mandé.")


def _correct(state: dict, p: dict, result: str) -> None:
    """Cambia el resultado de un pick ya cerrado: tacha el mensaje anterior y publica el correcto."""
    old_msgs, old_photo = p.get("result_msgs") or {}, p.get("result_is_photo") or {}
    note = "✏️ <i>Resultado corregido: ver el mensaje siguiente.</i>"
    for where, mid in old_msgs.items():
        chat = state["vip_chat"] if where == "vip" else config.FREE_CHANNEL
        try:
            (telegram.edit_caption if old_photo.get(where) else telegram.edit_text)(chat, mid, note)
        except telegram.TelegramError as e:
            print(f"No se pudo marcar la corrección en {where}: {e}")
    p.update(result=result, corrected_at=_iso(store.now_utc()))
    _post_result(state, p, formatting.result_correction(p))
    _after_result(state, p)


# ---------------------------------------------------------------- post partido (formato revista)
def RECAP_BUTTONS(p: dict) -> list:
    pid, msgs = p["id"], (p.get("recap") or {}).get("msgs") or {}
    st = p.get("ig_res_status")
    return [
        [("✅ En VIP", "noop") if "vip" in msgs else ("👑 Compartir en VIP", f"xv:{pid}"),
         ("✅ En Gratis", "noop") if "free" in msgs else ("🎁 Compartir en Gratis", f"xf:{pid}")],
        [("✅ Instagram" if st == "posted" else "⏳ Instagram en cola" if st == "queued" else "📸 Compartir en Instagram",
          "noop" if st in ("queued", "posted") else f"xi:{pid}")],
        [("🖼 Adjuntar mi imagen", f"xp:{pid}"), ("✏️ Cambiar titular", f"xt:{pid}")],
        [("🌙 Modo noche" if (p.get("recap") or {}).get("theme") == "light" else "☀️ Modo día", f"xh:{pid}")],
    ]


def _recap_supported(p: dict) -> bool:
    return len(p["legs"]) == 1 and (p["legs"][0].get("sport") or "soccer") == "soccer"


def _recap_file(p: dict) -> str:
    from . import recap
    return recap.image_path(p["id"])


def _recap_panel(state: dict, p: dict) -> None:
    """Te manda la imagen post partido con los botones para compartirla."""
    owner = state["owner_chat"]
    r = p["recap"]
    if r.get("panel"):
        telegram.edit_buttons_off(owner, r["panel"], "↪️ Reemplazada por la versión de abajo")
    label = {"W": " (✅ verde)", "L": " (❌ roja)", "V": " (↩️ nula)"}.get(p.get("result"), "")
    who = "partido " + p["id"] if p.get("news") else "pick #" + p["id"]
    cap = (f"📰 <b>Post partido · {who}</b>{label}\n"
           f"Titular: <b>{formatting.escape(r['title'])}</b> · para cambiarlo: /titular {p['id']} TU TITULAR\n"
           "Elige dónde compartirlo (puedes usar varios botones).")
    if r.get("credit"):
        cap += f"\n📸 {formatting.escape(r['credit']['text'])}"
    with open(_recap_file(p), "rb") as f:
        msg = telegram.send_photo(owner, f.read(), caption=cap)
    r["panel"] = msg["message_id"]
    telegram.set_buttons(owner, r["panel"], RECAP_BUTTONS(p))


def _upload_file(p: dict, kind: str = "recap") -> str:
    name = f"{p['id']}.jpg" if kind == "recap" else f"{p['id']}-{kind}.jpg"
    return os.path.join(config.ROOT, "data", "uploads", name)


def _recap(state: dict, p: dict, reuse: bool = False) -> bool:
    """Arma la imagen post partido con datos de ESPN y te la manda. False si ESPN aún no tiene el final.
    reuse=True vuelve a dibujarla con los datos ya guardados (titular nuevo o tu foto)."""
    if not state.get("owner_chat") or not _recap_supported(p):
        return False
    from . import commons, espn, postimage, recap
    l = p["legs"][0]
    old = p.get("recap") or {}
    rep = old.get("report") if reuse else None
    rep = rep or espn.match_report(l["home"], l["away"], l["kickoff"])
    if not rep:
        return False
    who = recap.hero(rep)
    if old.get("photo_src") == "user" and os.path.exists(_upload_file(p)):
        with open(_upload_file(p), "rb") as f:
            photo = (f.read(), None)
    else:
        photo = commons.photo(who["full"]) if who else None
    data = recap.build(p, rep, photo, old.get("custom_title"))
    data["credit"] = photo[1]["text"] if photo and photo[1] else None
    if old.get("mode") == "raw" and os.path.exists(_upload_file(p)):
        with open(_upload_file(p), "rb") as f:
            image = postimage.fit_instagram(f.read())
    else:
        image = postimage.render_recap(data, old.get("theme") or "dark")
    path = _recap_file(p)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(image)
    credit = photo[1] if photo and old.get("mode") != "raw" else None
    p["recap"] = {"title": data["headline"], "custom_title": old.get("custom_title"), "credit": credit,
                  "msgs": old.get("msgs") or {}, "panel": old.get("panel"), "hero": who["full"] if who else None,
                  "report": rep, "photo_src": old.get("photo_src"), "mode": old.get("mode"), "v": RECAP_TEXT_V,
                  "theme": old.get("theme"),
                  "tg": recap.telegram_caption(p, rep, data["headline"]),
                  "ig": recap.instagram_caption(p, rep, data["headline"], credit)}
    p.pop("recap_pending", None)
    p["ig_kit_sent"] = True   # el post partido reemplaza a la imagen de celebración
    _recap_panel(state, p)
    return True


def _after_result(state: dict, p: dict) -> None:
    """Con el resultado listo: imagen post partido (fútbol, pick simple) o la celebración de siempre."""
    if not _recap_supported(p):
        _instagram_kit(state, p)
        return
    p["recap_pending"] = True
    p["ig_kit_sent"] = True
    p.pop("recap_next", None)
    try:
        _recap(state, p)
    except Exception:
        traceback.print_exc()


def _recap_retry(state: dict, p: dict, now) -> None:
    """ESPN a veces tarda en cerrar el partido: reintenta cada 20 min durante 6 h y luego usa la celebración."""
    if not p.get("recap_pending") or p["status"] != "settled":
        return
    if p.get("recap_next") and now < store.parse_ts(p["recap_next"]):
        return
    if now - store.parse_ts(p.get("settled_at") or _iso(now)) > timedelta(minutes=config.RESULT_GIVE_UP_MIN):
        p.pop("recap_pending", None)
        if p.get("result") == "W":
            p["ig_kit_sent"] = False   # sin datos de ESPN: se ofrece la imagen de celebración
        return
    p["recap_next"] = _iso(now + timedelta(minutes=config.RESULT_RETRY_MIN))
    try:
        _recap(state, p)
    except Exception:
        traceback.print_exc()


RECAP_TEXT_V = 2


def _refresh_recap_texts(state: dict) -> None:
    """Textos nuevos del post partido para los que aún no salieron a Instagram."""
    from . import recap
    for p in state["picks"].values():
        r = p.get("recap") or {}
        if not r.get("report") or r.get("v") == RECAP_TEXT_V:
            continue
        r["v"] = RECAP_TEXT_V
        if p.get("ig_res_status") == "posted":
            continue
        r["tg"] = recap.telegram_caption(p, r["report"], r.get("title") or "")
        r["ig"] = recap.instagram_caption(p, r["report"], r.get("title") or "", r.get("credit"))
        if p.get("ig_res_status") == "queued":
            p["ig_res_caption"] = r["ig"]


def _recap_share(state: dict, p: dict, where: str) -> None:
    chat = state["vip_chat"] if where == "vip" else config.FREE_CHANNEL
    r = p["recap"]
    with open(_recap_file(p), "rb") as f:
        image = f.read()
    reply = (p.get("channel_msgs") or {}).get(where)
    text = r["tg"]
    if formatting.caption_fits(text):
        r["msgs"][where] = telegram.send_photo(chat, image, caption=text, reply_to=reply)["message_id"]
    else:
        r["msgs"][where] = telegram.send_photo(chat, image, reply_to=reply)["message_id"]
        telegram.send(chat, text)


def _teaser(state: dict, p: dict, reveal: str | None, vip: bool = False) -> None:
    """Adelanto en modo día para historias: pistas del pick y el pick tapado hasta la revelación."""
    from . import instagram, postimage, teaser
    owner = state["owner_chat"]
    image = postimage.render_teaser(teaser.teaser_data(p, reveal, vip))
    instagram.save_image(f"story-{p['id']}", image)
    p["teaser"] = {"reveal": reveal, "vip": vip}
    p.pop("ig_story_status", None)
    msg = telegram.send_photo(owner, image, caption=(
        f"📲 <b>Adelanto del pick #{p['id']}</b> (historia)\n"
        + (f"Se revela a las {reveal}." if reveal else
           f"Sin hora de revelación. Para ponerla: /adelanto {p['id']} 10:00")))
    p["teaser"]["msg"] = msg["message_id"]
    telegram.set_buttons(owner, msg["message_id"], TEASER_BUTTONS(p))


def TEASER_BUTTONS(p: dict) -> list:
    pid, st = p["id"], p.get("ig_story_status")
    return [[("✅ Historia publicada" if st == "posted" else "⏳ Historia en cola" if st == "queued"
              else "📲 Subir historia a Instagram", "noop" if st in ("queued", "posted") else f"ia:{pid}")],
            [("✅ En Gratis", "noop") if (p.get("teaser") or {}).get("free_msg")
             else ("🎁 Enviar también al canal Gratis", f"ag:{pid}")]]


def _teaser_command(state: dict, text: str) -> None:
    """/adelanto [N] [HH:MM] [vip]"""
    from . import teaser
    owner = state["owner_chat"]
    parts = text.split()[1:]
    now = store.now_utc()
    pid = next((x.lstrip("#") for x in parts if x.lstrip("#").isdigit()), None)
    if pid:
        p = state["picks"].get(pid)
    else:
        live = [x for x in state["picks"].values() if x["status"] in ("selected", "published")
                and store.parse_ts(x["kickoff"]) > now]
        live.sort(key=lambda x: (bool(x.get("free")), x.get("created_at") or ""), reverse=True)
        p = live[0] if live else None
    if not p or p["status"] not in ("selected", "published") or store.parse_ts(p["kickoff"]) <= now:
        telegram.send(owner, "Usa /adelanto, el número del pick y (si quieres) la hora en que lo revelas. "
                             "Ejemplo: /adelanto 8 10:00\nEl pick tiene que estar elegido y su partido aún no empieza.")
        return
    _teaser(state, p, teaser.parse_reveal(" ".join(x for x in parts if x.lstrip("#") != pid)),
            vip=any(x.lower() == "vip" for x in parts))


def _news_command(state: dict, text: str) -> None:
    """/postpartido Vasco vs Boca | Sudamericana — post partido de cualquier partido terminado (sin pick)."""
    import re as _re
    from . import espn
    owner = state["owner_chat"]
    body = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
    body, _, league = body.partition("|")
    teams = _re.split(r"\s+(?:vs\.?|v|-|contra)\s+", body.strip(), maxsplit=1, flags=_re.I)
    if len(teams) != 2 or not all(t.strip() for t in teams):
        telegram.send(owner, "Usa: /postpartido Vasco vs Boca | Sudamericana\n"
                             "(la liga después de la barra es opcional; busca partidos terminados de los últimos 3 días)")
        return
    found = espn.find_recent(teams[0].strip(), teams[1].strip())
    if not found:
        telegram.send(owner, "No encontré ese partido terminado en ESPN en los últimos 3 días. "
                             "Revisa los nombres (como aparecen en ESPN).")
        return
    rep, kickoff = found
    state["news_seq"] = state.get("news_seq", 0) + 1
    nid = f"N{state['news_seq']}"
    state["picks"][nid] = {"id": nid, "status": "news", "news": True, "kind": "news", "price": 0, "stake": 0,
                           "created_at": _iso(store.now_utc()), "kickoff": kickoff, "result": None,
                           "legs": [{"home": rep["home"]["name"], "away": rep["away"]["name"], "kickoff": kickoff,
                                     "league": league.strip(), "sport": "soccer"}],
                           "recap": {"report": rep}}
    telegram.send(owner, f"⚽ {formatting.escape(rep['home']['name'])} {rep['home']['score']}-"
                         f"{rep['away']['score']} {formatting.escape(rep['away']['name'])}: armando la imagen…")
    if not _recap(state, state["picks"][nid], reuse=True):
        telegram.send(owner, "⚠️ No pude armar la imagen. Intenta de nuevo en un rato.")


def _title_command(state: dict, text: str) -> None:
    owner = state["owner_chat"]
    parts = text.split(maxsplit=2)
    p = state["picks"].get(parts[1].lstrip("#")) if len(parts) > 1 else None
    if not p or len(parts) < 3:
        telegram.send(owner, "Usa /titular, el número del pick y el titular. Ejemplo: /titular 8 MARACA-NAZO\n"
                             "El guion marca dónde se parte en dos líneas (la segunda va en verde).")
        return
    if not p.get("recap"):
        telegram.send(owner, f"El pick #{p['id']} todavía no tiene imagen post partido.")
        return
    p["recap"]["custom_title"] = parts[2].strip()[:24]
    if p["recap"].get("mode") == "raw":
        telegram.send(owner, "Ese post usa tu imagen tal cual (sin titular). Para usar el diseño, adjunta la "
                             "imagen de nuevo y elige «Usar dentro del diseño».")
        return
    telegram.send(owner, "✏️ Generando la imagen con el nuevo titular…")
    if not _recap(state, p, reuse=True):
        telegram.send(owner, "⚠️ No pude volver a leer el partido en ESPN. Intenta de nuevo en un rato.")
    elif p.get("ig_res_status") in ("queued", "posted"):
        telegram.send(owner, "Ojo: en Instagram ya quedó la versión anterior.")



def _receive_upload(state: dict, msg: dict) -> None:
    """Llegó una imagen tuya para el post partido: la guarda y pregunta cómo usarla."""
    owner = state["owner_chat"]
    wait = state.get("await_photo") or {}
    kind = wait.get("kind") or "recap"
    p = state["picks"].get(wait.get("pid") or "")
    ok = p and (p.get("recap") if kind == "recap" else p["status"] in ("selected", "published"))
    if not ok or store.now_utc() > store.parse_ts(wait["until"]):
        state.pop("await_photo", None)
        telegram.send(owner, "Para usar una imagen tuya, primero toca «🖼 Adjuntar mi imagen» en el post partido.")
        return
    doc = msg.get("document") or {}
    if msg.get("photo"):
        file_id = max(msg["photo"], key=lambda x: x.get("file_size") or x.get("width", 0))["file_id"]
    elif (doc.get("mime_type") or "").startswith("image/"):
        file_id = doc["file_id"]
    else:
        telegram.send(owner, "Eso no parece una imagen. Mándala como foto o como archivo de imagen (JPG o PNG).")
        return
    import io
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(telegram.download(file_id))).convert("RGB")
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        telegram.send(owner, "⚠️ No pude abrir esa imagen. Prueba con otra (JPG o PNG).")
        return
    if im.width > 1440:
        im = im.resize((1440, round(im.height * 1440 / im.width)), Image.LANCZOS)
    path = _upload_file(p, kind)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path, "JPEG", quality=92)
    state.pop("await_photo", None)
    pre = "x" if kind == "recap" else "y"
    what = "el post partido" if kind == "recap" else "la imagen"
    telegram.send(owner, f"📥 Recibí tu imagen para {what} del pick #{p['id']}. ¿Cómo la uso?",
                  [[("🎨 Usar dentro del diseño", f"{pre}d:{p['id']}")], [("📤 Subir tal cual", f"{pre}r:{p['id']}")],
                   [("Cancelar", f"xc:{p['id']}")]])


# ---------------------------------------------------------------- botones y mensajes
def _norm_code(x: str) -> str:
    return x.strip().strip("<>\"'`").strip().lower()


def _code_ok(text: str) -> bool:
    parts = text.split(maxsplit=1)
    return bool(config.LINK_CODE) and len(parts) == 2 and _norm_code(parts[1]) == _norm_code(config.LINK_CODE)


def _handle_update(state: dict, u: dict) -> None:
    owner = state.get("owner_chat")

    msg = u.get("message")
    if msg and msg.get("chat", {}).get("type") == "private":
        text = (msg.get("text") or "").strip()
        chat = msg["chat"]["id"]
        if chat == owner and (msg.get("photo") or msg.get("document")):
            _receive_upload(state, msg)
            return
        if text.lower().startswith("/vincular") and not text.lower().startswith("/vincular_vip"):
            if _code_ok(text):
                state["owner_chat"] = chat
                telegram.send(chat, "🔗 Listo, este chat quedó vinculado como dueño de Stakevision.")
            else:
                telegram.send(chat, "⚠️ Ese código no coincide con LINK_CODE. Revísalo y vuelve a enviar /vincular CODIGO")
        elif chat == owner and text.startswith("/estado"):
            telegram.send(chat, _status_text(state))
        elif chat == owner and text.lower().startswith("/adelanto"):
            _teaser_command(state, text)
        elif chat == owner and text.lower().startswith("/postpartido"):
            _news_command(state, text)
        elif chat == owner and text.lower().startswith("/titular"):
            _title_command(state, text)
        elif chat == owner and text.lower().startswith("/compartir"):
            _share_command(state, text)
        elif chat == owner and text.lower().startswith(("/envivo", "/vivo")):
            _request_search(state, text, live=True)
        elif chat == owner and text.lower().startswith("/buscar"):
            _request_search(state, text)
        elif chat == owner and text.lower().startswith(("/ayuda", "/start", "/help")):
            telegram.send(chat, HELP_TEXT)
        return

    post = u.get("channel_post")
    if post:
        text = (post.get("text") or "").strip()
        if text.lower().startswith("/vincular_vip") and _code_ok(text):
            state["vip_chat"] = post["chat"]["id"]
            if owner:
                telegram.send(owner, "🔗 Canal VIP vinculado. Ya puedes borrar el mensaje /vincular_vip del canal.")
        return

    cb = u.get("callback_query")
    if not cb:
        return
    if cb.get("message", {}).get("chat", {}).get("id") != owner:
        telegram.answer(cb["id"], "No autorizado")
        return
    action, _, pid = (cb.get("data") or "").partition(":")
    p = state["picks"].get(pid)
    if not p:
        telegram.answer(cb["id"])
        return

    if action == "s":   # elegir: generar la imagen y preguntar destinos
        if p["status"] != "candidate":
            telegram.answer(cb["id"], "Ya estaba procesado")
            return
        if _expires(p) <= store.now_utc():
            p["status"] = "expired"
            telegram.edit_buttons_off(owner, cb["message"]["message_id"], "⌛ Ya no está vigente")
            telegram.answer(cb["id"], "Llegó tarde")
            return
        p["status"] = "selected"
        telegram.edit_buttons_off(owner, cb["message"]["message_id"], "🖼 Elegido: imagen generada abajo")
        _share_panel(state, p)
        telegram.answer(cb["id"], "Imagen generada")
        return

    if action in ("pv", "pf", "pi"):
        if p["status"] not in ("selected", "published"):
            telegram.answer(cb["id"], "Este pick ya no está disponible")
            return
        late = _expires(p) <= store.now_utc() and not p.get("live")
        if action in ("pv", "pf"):
            if late and not p.get("channel_msgs"):
                telegram.answer(cb["id"], "El partido ya empezó: no se publica")
                return
            if not state.get("vip_chat"):
                telegram.answer(cb["id"], "Primero vincula el canal VIP con /vincular_vip")
                return
            _publish(state, p, free=(action == "pf"))
            telegram.answer(cb["id"], "Publicado")
        else:
            from . import instagram
            if not instagram.enabled(state):
                telegram.answer(cb["id"], "Instagram no está conectado")
                return
            image = _pick_image(p)
            if not image:
                telegram.answer(cb["id"], "No se pudo generar la imagen")
                return
            from . import postimage
            instagram.save_image(f"pre-{p['id']}", postimage.fit_instagram(image))
            p["ig_pre_status"] = "queued"
            p["ig_pre_caption"] = formatting.instagram_pick_caption(p)
            telegram.answer(cb["id"], "Se publica en Instagram en unos minutos")
        telegram.set_buttons(owner, cb["message"]["message_id"], SHARE_BUTTONS(p))
        return

    if action == "u":   # deshacer un descarte
        mid = cb["message"]["message_id"]
        if p["status"] != "rejected":
            telegram.answer(cb["id"], "Ya no estaba descartado")
            return
        if _expires(p) <= store.now_utc():
            p["status"] = "expired"
            telegram.edit_buttons_off(owner, mid, "⌛ Ya no está vigente")
            telegram.answer(cb["id"], "Llegó tarde: ya no está vigente")
            return
        p["status"] = p.pop("prev_status", None) or "candidate"
        telegram.set_buttons(owner, mid, CANDIDATE_BUTTONS(pid) if p["status"] == "candidate" else SHARE_BUTTONS(p))
        telegram.answer(cb["id"], "Recuperado")
        return

    if action in ("a", "f", "r"):
        if p["status"] not in ("candidate", "selected") or (action != "r" and p["status"] != "candidate"):
            telegram.answer(cb["id"], "Ya estaba procesado")
            return
        if action == "r":
            if p.get("channel_msgs") or p.get("ig_pre_status"):
                telegram.answer(cb["id"], "Ya se publicó en algún lado")
                return
            p["prev_status"], p["status"] = p["status"], "rejected"
            telegram.set_buttons(owner, cb["message"]["message_id"], [[("❌ Descartado · ↩️ Deshacer", f"u:{pid}")]])
            telegram.answer(cb["id"], "Descartado (puedes deshacerlo)")
            return
        if store.parse_ts(p["kickoff"]) <= store.now_utc():
            p["status"] = "expired"
            telegram.edit_buttons_off(owner, cb["message"]["message_id"], "⌛ El partido ya empezó")
            telegram.answer(cb["id"], "Llegó tarde: el partido ya empezó")
            return
        if not state.get("vip_chat"):
            telegram.answer(cb["id"], "Primero vincula el canal VIP con /vincular_vip")
            return
        _publish(state, p, free=(action == "f"))
        note = "✅ Publicado en VIP + Gratis" if action == "f" else "✅ Publicado en VIP"
        telegram.edit_buttons_off(owner, cb["message"]["message_id"], note)
        telegram.answer(cb["id"], "Publicado")

    elif action == "th":   # modo día / noche de la versión con foto del pick
        if p["status"] not in ("selected", "published") or p.get("pick_style") != "photo":
            telegram.answer(cb["id"], "No disponible")
            return
        p["theme"] = "dark" if p.get("theme") == "light" else "light"
        telegram.answer(cb["id"], "Cambiando a modo " + ("día…" if p["theme"] == "light" else "noche…"))
        try:
            _make_pick_photo(p, reuse=True)
        except Exception:
            traceback.print_exc()
            telegram.send(owner, "⚠️ No pude cambiar el modo.")
            return
        if p.get("share_msg"):
            telegram.edit_buttons_off(owner, p["share_msg"], "↪️ Reemplazada por la versión de abajo")
        _share_panel(state, p)
        return

    elif action in ("st", "ad", "ia", "ag"):   # estilo de la imagen del pick y adelanto para historias
        if action == "st":
            if p["status"] not in ("selected", "published"):
                telegram.answer(cb["id"], "Este pick ya no está disponible")
                return
            if p.get("pick_style") == "photo":
                p["pick_style"] = "coupon"
            else:
                telegram.answer(cb["id"], "Armando la versión con foto…")
                try:
                    _make_pick_photo(p)
                    p["pick_style"] = "photo"
                except Exception:
                    traceback.print_exc()
                    telegram.send(owner, "⚠️ No pude armar la versión con foto. Sigue la del cupón.")
                    return
            if p.get("share_msg"):
                telegram.edit_buttons_off(owner, p["share_msg"], "↪️ Reemplazada por la versión de abajo")
            _share_panel(state, p)
            telegram.answer(cb["id"])
            return
        if action == "ad":
            if store.parse_ts(p["kickoff"]) <= store.now_utc():
                telegram.answer(cb["id"], "El partido ya empezó")
                return
            telegram.answer(cb["id"], "Generando el adelanto…")
            _teaser(state, p, None)
            return
        if not p.get("teaser"):
            telegram.answer(cb["id"], "Primero genera el adelanto")
            return
        if action == "ia":
            from . import instagram
            if not instagram.enabled(state):
                telegram.answer(cb["id"], "Instagram no está conectado")
                return
            p["ig_story_status"] = "queued"
            telegram.answer(cb["id"], "La historia se publica en un par de minutos")
        else:
            if p["teaser"].get("free_msg"):
                telegram.answer(cb["id"], "Ya estaba en Gratis")
                return
            from . import instagram
            with open(instagram.image_path(f"story-{p['id']}"), "rb") as f:
                p["teaser"]["free_msg"] = telegram.send_photo(config.FREE_CHANNEL, f.read())["message_id"]
            telegram.answer(cb["id"], "Enviado al canal Gratis")
        telegram.set_buttons(owner, cb["message"]["message_id"], TEASER_BUTTONS(p))
        return

    elif action in ("yp", "yd", "yr"):   # tu propia imagen para el pick (antes del partido)
        if p["status"] not in ("selected", "published"):
            telegram.answer(cb["id"], "Este pick ya no está disponible")
            return
        if action == "yp":
            state["await_photo"] = {"pid": pid, "kind": "pick", "until": _iso(store.now_utc() + timedelta(hours=2))}
            telegram.send(owner, f"🖼 Mándame ahora la imagen para el pick #{pid} (como foto o como archivo).\n"
                                 "Usa solo imágenes tuyas o con permiso de uso: las fotos de agencias o "
                                 "medios pueden traer reclamos de copyright en Instagram.")
            telegram.answer(cb["id"], "Esperando tu imagen")
            return
        up = _upload_file(p, "pick")
        if not os.path.exists(up):
            telegram.answer(cb["id"], "No encuentro tu imagen, mándala de nuevo")
            return
        with open(up, "rb") as f:
            raw = f.read()
        telegram.edit_buttons_off(owner, cb["message"]["message_id"],
                                  "🎨 Dentro del diseño" if action == "yd" else "📤 Tal cual")
        telegram.answer(cb["id"], "Generando…")
        try:
            if action == "yd":
                _make_pick_photo(p, user_photo=raw)
            else:
                from . import postimage
                path = _pick_photo_file(p)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(postimage.fit_instagram(raw))
            p["pick_photo_credit"] = None
            p["pick_style"] = "photo"
        except Exception:
            traceback.print_exc()
            telegram.send(owner, "⚠️ No pude usar esa imagen. Prueba con otra.")
            return
        if p.get("share_msg"):
            telegram.edit_buttons_off(owner, p["share_msg"], "↪️ Reemplazada por la versión de abajo")
        _share_panel(state, p)
        if p.get("ig_pre_status") in ("queued", "posted"):
            telegram.send(owner, "Ojo: en Instagram ya quedó la versión anterior.")
        return

    elif action == "xh":   # modo día / noche del post partido
        r = p.get("recap") or {}
        if not r or r.get("mode") == "raw":
            telegram.answer(cb["id"], "Esta imagen va tal cual: no tiene modo día")
            return
        r["theme"] = "dark" if r.get("theme") == "light" else "light"
        telegram.answer(cb["id"], "Cambiando a modo " + ("día…" if r["theme"] == "light" else "noche…"))
        if not _recap(state, p, reuse=True):
            telegram.send(owner, "⚠️ No pude cambiar el modo. Intenta de nuevo en un rato.")
        return

    elif action in ("xp", "xd", "xr", "xc"):   # tu propia imagen para el post partido
        if action == "xc":
            telegram.edit_buttons_off(owner, cb["message"]["message_id"], "Cancelado: sigue la imagen anterior")
            telegram.answer(cb["id"])
            return
        if not p.get("recap"):
            telegram.answer(cb["id"], "Este pick no tiene post partido")
            return
        if action == "xp":
            state["await_photo"] = {"pid": pid, "until": _iso(store.now_utc() + timedelta(hours=2))}
            telegram.send(owner, f"🖼 Mándame ahora la imagen para el pick #{pid} (como foto o como archivo).\n"
                                 "Usa solo imágenes tuyas o con permiso de uso: las fotos de agencias o "
                                 "medios pueden traer reclamos de copyright en Instagram.")
            telegram.answer(cb["id"], "Esperando tu imagen")
            return
        if action == "xc":
            telegram.edit_buttons_off(owner, cb["message"]["message_id"], "Cancelado: sigue la imagen anterior")
            telegram.answer(cb["id"])
            return
        if not os.path.exists(_upload_file(p)):
            telegram.answer(cb["id"], "No encuentro tu imagen, mándala de nuevo")
            return
        p["recap"]["photo_src"] = "user" if action == "xd" else p["recap"].get("photo_src")
        p["recap"]["mode"] = "raw" if action == "xr" else None
        telegram.edit_buttons_off(owner, cb["message"]["message_id"],
                                  "🎨 Dentro del diseño" if action == "xd" else "📤 Tal cual")
        telegram.answer(cb["id"], "Generando…")
        if not _recap(state, p, reuse=True):
            telegram.send(owner, "⚠️ No pude volver a armar el post partido. Intenta de nuevo en un rato.")
        elif p.get("ig_res_status") in ("queued", "posted"):
            telegram.send(owner, "Ojo: en Instagram ya quedó la versión anterior.")
        return

    elif action in ("xv", "xf", "xi", "xt"):   # compartir la imagen post partido
        if not p.get("recap") or not os.path.exists(_recap_file(p)):
            telegram.answer(cb["id"], "La imagen post partido ya no está disponible")
            return
        if action == "xt":
            telegram.send(owner, f"Escribe /titular {pid} y el titular nuevo. Ejemplo: /titular {pid} MARACA-NAZO\n"
                                 "El guion marca dónde se parte en dos líneas (la segunda va en verde).")
            telegram.answer(cb["id"])
            return
        if action in ("xv", "xf"):
            where = "vip" if action == "xv" else "free"
            if where in p["recap"]["msgs"]:
                telegram.answer(cb["id"], "Ya estaba compartida ahí")
                return
            if where == "vip" and not state.get("vip_chat"):
                telegram.answer(cb["id"], "Primero vincula el canal VIP con /vincular_vip")
                return
            _recap_share(state, p, where)
            telegram.answer(cb["id"], "Compartida")
        else:
            from . import instagram
            if not instagram.enabled(state):
                telegram.answer(cb["id"], "Instagram no está conectado")
                return
            if p.get("ig_res_status") in ("queued", "posted"):
                telegram.answer(cb["id"], "Ya estaba en proceso")
                return
            p["ig_res_status"] = "queued"
            p["ig_res_caption"] = p["recap"]["ig"]
            telegram.answer(cb["id"], "Se publica en Instagram en unos minutos")
        telegram.set_buttons(owner, cb["message"]["message_id"], RECAP_BUTTONS(p))

    elif action in ("ig", "ign"):  # publicar (o no) la celebración en Instagram
        if p.get("ig_status") in ("queued", "posted"):
            telegram.answer(cb["id"], "Ya estaba en proceso")
            return
        if action == "ign":
            p["ig_status"] = "skipped"
            telegram.edit_buttons_off(owner, cb["message"]["message_id"], "No se publica en Instagram")
            telegram.answer(cb["id"], "Listo, no se publica")
        else:
            p["ig_status"] = "queued"
            telegram.edit_buttons_off(owner, cb["message"]["message_id"], "⏳ Se publica en Instagram en unos minutos")
            telegram.answer(cb["id"], "Se publica en unos minutos")

    elif action == "c":  # corregir un resultado automático: mostrar las 3 opciones
        if p["status"] != "settled":
            telegram.answer(cb["id"])
            return
        telegram.set_buttons(owner, cb["message"]["message_id"], RESULT_BUTTONS(pid))
        telegram.answer(cb["id"], "Elige el resultado correcto")

    elif action in ("W", "L", "V"):
        mid = cb["message"]["message_id"]
        if p["status"] == "published":
            _settle(state, p, action)
            telegram.edit_buttons_off(owner, mid, formatting.RESULT_LABEL[action])
            telegram.answer(cb["id"], "Resultado guardado")
        elif p["status"] == "settled":
            if p.get("result") != action:
                _correct(state, p, action)
                telegram.answer(cb["id"], "Resultado corregido")
            else:
                telegram.answer(cb["id"], "Sin cambios")
            telegram.set_buttons(owner, mid, [[(formatting.RESULT_LABEL[action], "noop")],
                                              [("✏️ Corregir", f"c:{pid}")]])
        else:
            telegram.answer(cb["id"], "Ya estaba cerrado")


HELP_TEXT = (
    "👁 <b>Comandos de Stakevision</b>\n\n"
    "/buscar · analiza ahora los partidos de las próximas 30 h y te manda el top 3\n"
    "/buscar 40 · igual, pero mirando 40 horas hacia adelante (máximo 47)\n"
    "/envivo · busca valor en partidos que se están jugando ahora\n"
    "/compartir 8 · vuelve a mandarte la imagen del pick #8 (o su post partido, si ya terminó)\n"
    "/titular 8 MARACA-NAZO · cambia el titular de la imagen post partido del pick #8\n"
    "/postpartido Vasco vs Boca | Sudamericana · imagen post partido de cualquier partido terminado\n"
    "/adelanto 8 10:00 · adelanto del pick #8 para historias (pistas + pick tapado hasta las 10:00)\n"
    "/estado · candidatos pendientes, picks en juego, historial y consultas usadas\n"
    "/ayuda · esta lista\n\n"
    "El escaneo automático sigue saliendo todos los días a las 09:07."
)


def _request_search(state: dict, text: str, live: bool = False) -> None:
    from zoneinfo import ZoneInfo
    owner = state["owner_chat"]
    parts = text.split()
    hours = config.WINDOW_END_H
    if len(parts) > 1 and parts[1].lower() in ("vivo", "envivo", "live"):
        live = True
    elif len(parts) > 1 and not live:
        try:
            hours = max(2, min(47, int(parts[1])))
        except ValueError:
            telegram.send(owner, "Usa /buscar o /buscar 40 (horas hacia adelante, máximo 47).")
            return
    today = store.now_utc().astimezone(ZoneInfo(config.TIMEZONE)).date().isoformat()
    m = state.get("manual") or {}
    if m.get("date") != today:
        m = {"date": today, "n": 0}
    if m["n"] >= config.MANUAL_SEARCHES_PER_DAY:
        telegram.send(owner, f"⚠️ Ya hiciste {m['n']} búsquedas hoy (máximo {config.MANUAL_SEARCHES_PER_DAY}, "
                             f"para no agotar el plan gratis de OddsPapi). Mañana se reinicia.")
        return
    m["n"] += 1
    state["manual"] = m
    if live:
        state["scan_request"] = "live"
        telegram.send(owner, f"🔴 Buscando valor en los partidos que se están jugando… te llega en un par de "
                             f"minutos. (Búsqueda {m['n']} de {config.MANUAL_SEARCHES_PER_DAY} hoy)")
        return
    state["scan_request"] = hours
    telegram.send(owner, f"🔎 Buscando los mejores picks de las próximas {hours} horas… "
                         f"te llegan en un par de minutos. (Búsqueda {m['n']} de {config.MANUAL_SEARCHES_PER_DAY} hoy)")


def _status_text(state: dict) -> str:
    ps = list(state["picks"].values())
    pend = sum(1 for p in ps if p["status"] == "candidate")
    live = sum(1 for p in ps if p["status"] == "published")
    w = sum(1 for p in ps if p.get("result") == "W")
    l = sum(1 for p in ps if p.get("result") == "L")
    quota = "\nOddsPapi: " + oddspapi.quota_text()
    return (f"📊 Candidatos por aprobar: {pend}\nPublicados en juego: {live}\n"
            f"Historial: {w} verdes, {l} rojas.{quota}")


def _migrate_stakes(state: dict, now) -> None:
    """Escala de stake v2: recalcula picks que aún no empiezan y corrige sus mensajes."""
    from .value import stake_for
    for p in state["picks"].values():
        if p.get("stake_v") == 2:
            continue
        if p["status"] in ("candidate", "published") and store.parse_ts(p["kickoff"]) > now:
            p["stake"] = stake_for(p.get("tier", "valor"), p["kind"], p["price"], p["edge"])
            if p["status"] == "published":
                text = formatting.channel_post(p)
                for where, mid in (p.get("channel_msgs") or {}).items():
                    chat = state["vip_chat"] if where == "vip" else config.FREE_CHANNEL
                    try:
                        telegram.edit_text(chat, mid, text)
                    except telegram.TelegramError as e:
                        print(f"No se pudo editar el pick {p['id']} en {where}: {e}")
        p["stake_v"] = 2


def _process_updates(state: dict, wait: int = 0) -> int:
    ups = telegram.updates(state["tg_offset"], wait=wait)
    kinds = [k for u in ups for k in ("message", "channel_post", "callback_query") if k in u]
    if ups or not wait:
        print(f"Actualizaciones recibidas: {len(ups)} ({', '.join(sorted(set(kinds))) or 'ninguna'}); "
              f"dueño vinculado: {'sí' if state.get('owner_chat') else 'no'}; "
              f"VIP vinculado: {'sí' if state.get('vip_chat') else 'no'}")
    for u in ups:
        state["tg_offset"] = u["update_id"] + 1
        try:
            _handle_update(state, u)
        except Exception:
            traceback.print_exc()
        store.save(state)
    return len(ups)


def _checkpoint(msg: str = "Actualizar estado") -> None:
    """Guarda el estado en el repo a mitad de la escucha (solo en GitHub Actions)."""
    import subprocess
    if not os.environ.get("GIT_CHECKPOINT"):
        return
    try:
        subprocess.run("git add data docs/historial.json docs/ig", shell=True, check=False)
        if subprocess.run("git diff --cached --quiet", shell=True).returncode != 0:
            subprocess.run(f'git commit -q -m "{msg}" && git pull -q --rebase && git push -q', shell=True, check=False)
    except Exception:  # noqa: BLE001
        traceback.print_exc()


def _run_scan_request(state: dict) -> dict:
    request = state.pop("scan_request", None)
    if not request:
        return state
    store.save(state)
    if request == "live":
        scan(top=config.MANUAL_TOP, manual=True, live=True)
    else:
        scan(hours=request, top=config.MANUAL_TOP, manual=True)
    return store.load()


def listen(seconds: int = 270) -> None:
    """Revisión completa y luego queda escuchando: los botones responden al instante (1-2 s)."""
    import time
    end = time.time() + seconds
    poll()
    _checkpoint()
    last_ig = time.time()
    while time.time() < end - 25:
        state = store.load()
        try:
            n = _process_updates(state, wait=20)
        except Exception:
            traceback.print_exc()
            time.sleep(5)
            continue
        state = _run_scan_request(state)
        if n:
            store.save(state)
            _checkpoint()
        if time.time() - last_ig > 60:   # Instagram necesita que la imagen ya esté en la web
            last_ig = time.time()
            try:
                from . import instagram
                if instagram.enabled(state) and any(
                        p.get(f) == "queued" for p in state["picks"].values()
                        for f in ("ig_status", "ig_pre_status", "ig_res_status", "ig_story_status")):
                    _instagram_queue(state, store.now_utc())
                    store.save(state)
                    _checkpoint()
            except Exception:
                traceback.print_exc()


def poll() -> None:
    state = store.load()
    _process_updates(state)

    now = store.now_utc()
    owner = state.get("owner_chat")
    if owner and state.get("cmds_v") != 6:
        try:  # menú de comandos en Telegram (solo visible en tu chat con el bot)
            telegram._call("setMyCommands", scope={"type": "chat", "chat_id": owner}, commands=[
                {"command": "buscar", "description": "Analizar ahora y recibir el top 3"},
                {"command": "envivo", "description": "Buscar valor en partidos que se están jugando"},
                {"command": "compartir", "description": "Imagen de un pick para VIP, Gratis o Instagram"},
                {"command": "titular", "description": "Cambiar el titular de la imagen post partido"},
                {"command": "postpartido", "description": "Imagen post partido de cualquier partido (ej. Vasco vs Boca)"},
                {"command": "adelanto", "description": "Adelanto del pick para historias (ej. /adelanto 8 10:00)"},
                {"command": "estado", "description": "Pendientes, picks en juego e historial"},
                {"command": "ayuda", "description": "Lista de comandos"}])
            state["cmds_v"] = 6
        except Exception as e:
            print(f"No se pudo registrar el menú de comandos: {e}")
    _migrate_stakes(state, now)
    _refresh_recap_texts(state)
    for p in state["picks"].values():   # picks aprobados con el flujo antiguo: ofrecer la imagen para compartir
        if (owner and p["status"] == "published" and not p.get("share_msg") and not p.get("share_offered")
                and store.parse_ts(p["kickoff"]) > now):
            p["share_offered"] = True
            try:
                _share_panel(state, p)
            except Exception:
                traceback.print_exc()
    for p in state["picks"].values():
        if p["status"] in ("candidate", "selected") and _expires(p) <= now:
            was = p["status"]
            p["status"] = "expired"
            if owner and p.get("owner_msg") and was == "candidate":
                telegram.edit_buttons_off(owner, p["owner_msg"], "⌛ Sin aprobar a tiempo")
            if owner and p.get("share_msg"):
                telegram.edit_buttons_off(owner, p["share_msg"], "⌛ Ya no está vigente")
        _remind(state, p, now)
        _recap_retry(state, p, now)
        if (p["status"] == "settled" and p.get("result") == "W" and p.get("settled_at")
                and now - store.parse_ts(p["settled_at"]) < timedelta(hours=48)):
            from . import instagram
            if p.get("ig_kit_sent") and p.get("ig_kit_mode") != "api" and instagram.enabled(state) and not p.get("ig_status"):
                p["ig_kit_sent"] = False   # Instagram recién conectado: ofrecer publicar los verdes recientes
            if not p.get("ig_kit_sent"):
                _instagram_kit(state, p)
        last_kick = max(store.parse_ts(l["kickoff"]) for l in p["legs"])
        if (p["status"] == "published" and not p.get("result_asked") and owner
                and now >= last_kick + timedelta(minutes=config.RESULT_CHECK_AFTER_MIN)
                and not (p.get("next_check") and now < store.parse_ts(p["next_check"]))):
            _auto_result(state, p, owner, now, last_kick)
    try:
        from . import history
        history.update(max_fetch=1)   # arma el historial de resultados de a poco (1 consulta por revisión)
    except Exception:
        traceback.print_exc()
    try:
        from . import instagram
        if instagram.enabled(state):
            ig = state.setdefault("ig", {})
            fp = instagram._fp(config.INSTAGRAM_TOKEN)
            if ig.get("checked") != fp and state.get("owner_chat"):
                try:
                    me = instagram._call("GET", "me", state, fields="username")
                    telegram.send(state["owner_chat"], f"📸 Instagram conectado: @{formatting.escape(me.get('username', '?'))}. "
                                  "Los verdes te llegarán con el botón para publicarlos.")
                except instagram.InstagramError as e:
                    telegram.send(state["owner_chat"], f"⚠️ El token de Instagram no funcionó: {formatting.escape(str(e))}")
                ig["checked"] = fp
            instagram.refresh_token(state)
            _instagram_queue(state, now)
            from . import ig_inbox
            ig_inbox.run(state)   # responde comentarios y mensajes directos
    except Exception:
        traceback.print_exc()
    store.save(state)
    state = _run_scan_request(state)
    from zoneinfo import ZoneInfo
    local = store.now_utc().astimezone(ZoneInfo(config.TIMEZONE))
    if (config.AUTO_SCAN_FALLBACK and state.get("owner_chat") and state.get("auto_scan_date") != _local_today()
            and (local.hour, local.minute) >= (9, 7) and local.hour < 22):
        scan()   # respaldo del escaneo diario por si el disparo de las 09:07 no corrió


def setup() -> None:
    import os
    if not os.path.exists(config.MARKETS_CACHE):
        m = oddspapi.markets(force=True)
        print(f"Mercados de fútbol guardados: {len(m)}")
    t = oddspapi.tournaments()
    print(f"Torneos de fútbol guardados: {len(t)}")
    print("Uso OddsPapi:", oddspapi.quota_text())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "poll"
    {"scan": scan, "poll": poll, "listen": listen, "setup": setup}[cmd]()
