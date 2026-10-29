"""Noticias deportivas para Instagram, siempre en español y siempre con tu aprobación.

Flujo (con la clave de Gemini, GEMINI_API_KEY):
1) Cada 2 h (9:00–23:00 de Chile) busca noticias importantes: titulares grandes de fútbol y NBA
   (ESPN) y las de los equipos de nuestros picks. Un editor (Gemini) elige las que valen la pena.
2) Te las manda traducidas y resumidas en español, con la fuente: «✅ Sí, prepárala» / «✖️ No».
3) Al aprobar, la redacta al instante en español con los datos del artículo y arma imagen + Reel.
4) Te llega para revisar: «🎬 Reel ahora», «⏰ En horario», «🖼 Solo imagen», «✏️ Modificar», «✖️ No».
5) «Modificar»: le escribes qué cambiar y te llega la versión nueva.
6) Se publica solo en Instagram (máx. 4 noticias al día; «En horario» = 13:00–15:00 o 20:00–23:00).
Sin la clave, la redacción queda pedida en data/news_requests.json (la puede hacer Claude a mano).
"""
from __future__ import annotations

import html
import json
import re
import os
import traceback
from datetime import datetime, timedelta, timezone

import requests

from . import config, formatting, store, telegram

REQ = os.path.join(config.ROOT, "data", "news_requests.json")
READY = os.path.join(config.ROOT, "data", "news_ready.json")
CHECK_EVERY_H = 2
MAX_PER_CHECK = 3
DAILY_MAX = 4                        # noticias publicadas por día, como máximo
WINDOWS = ((13, 15), (20, 23))       # horarios de más movimiento (hora de Chile)
TOP_SOURCES = [("soccer", "eng.1"), ("soccer", "esp.1"), ("soccer", "ita.1"), ("soccer", "uefa.champions"),
               ("soccer", "conmebol.libertadores"), ("soccer", "chi.1"), ("soccer", "fifa.world"), ("basketball", "nba")]
UA = {"User-Agent": "Mozilla/5.0 (StakevisionBot)"}
SOCCER_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary"


def BUTTONS(nid: str) -> list:
    return [[("✅ Sí, prepárala", f"nq:{nid}"), ("✖️ No", f"nx:{nid}")]]


def PUBLISH_BUTTONS(nid: str, reel: bool = True) -> list:
    rows = ([[("🎬 Reel ahora", f"np:{nid}"), ("⏰ Reel en horario", f"nt:{nid}")]] if reel else
            [[("📸 Publicar ahora", f"ni:{nid}"), ("⏰ En horario", f"nh:{nid}")]])
    rows.append(([("🖼 Solo imagen", f"ni:{nid}")] if reel else []) + [("✏️ Modificar", f"ne:{nid}")])
    rows.append([("📷 Cambiar foto", f"nf:{nid}"), ("🚫 Sin foto", f"nz:{nid}")])
    rows.append([("✖️ No publicar", f"nn:{nid}")])
    return rows


EDITORIAL = """Eres el editor de Stakevision, una cuenta chilena de Instagram de fútbol y NBA (también da pronósticos
deportivos). Escribes SIEMPRE en español neutro con toques chilenos suaves, claro y atractivo para el público general.
Reglas: usa SOLO los datos del texto fuente (no inventes cifras, fechas, citas ni diagnósticos); si una cita está en
inglés, tradúcela fiel y di que es traducida; nada de casas de apuestas ni cuotas; nombres propios bien escritos."""


def _article_text(link: str, fallback: str = "") -> str:
    """Texto del artículo (párrafos), para redactar con los datos reales."""
    import re
    if not link:
        return fallback
    try:
        r = requests.get(link, headers=UA, timeout=25)
        paras = re.findall(r"<p[^>]*>(.*?)</p>", r.text, re.S)
        txt = "\n".join(html.unescape(re.sub(r"<[^>]+>", "", p_)).strip() for p_ in paras)
        txt = "\n".join(x for x in txt.split("\n") if len(x) > 40)
        return (txt[:7000] or fallback)
    except Exception:  # noqa: BLE001
        return fallback


def _load(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return []


def _save(path: str, rows: list) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- 1) vigía
def _our_games(state: dict) -> list[dict]:
    """Partidos de nuestros picks (candidatos, aprobados, publicados o recién cerrados): ayer, hoy y mañana."""
    now = store.now_utc()
    out, seen = [], set()
    for p in state["picks"].values():
        if p.get("status") not in ("candidate", "selected", "published", "settled") or p.get("news"):
            continue
        for l in p.get("legs") or []:
            ko = store.parse_ts(l.get("kickoff") or p["kickoff"])
            if not (now - timedelta(hours=30) <= ko <= now + timedelta(hours=30)):
                continue
            key = (l["home"], l["away"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"pid": p["id"], "home": l["home"], "away": l["away"], "kickoff": l.get("kickoff") or p["kickoff"],
                        "sport": l.get("sport") or "soccer", "status": p["status"]})
    return out


def _articles(g: dict) -> list[dict]:
    """Artículos de ESPN del partido y de sus equipos."""
    arts = []
    if g["sport"] == "basketball":
        from . import nba
        found = nba.find_event(g["home"], g["away"], g["kickoff"])
        if not found:
            return []
        e = found[0]
        arts += ((nba._get("/summary", event=e.get("id")) or {}).get("news") or {}).get("articles") or []
        for c in e["competitions"][0]["competitors"]:
            tid = (c.get("team") or {}).get("id")
            if tid:
                arts += nba._get("/news", team=tid, limit=8).get("articles") or []
    else:
        from . import espn
        found = espn._find(g["home"], g["away"], g["kickoff"])
        if not found:
            return []
        try:
            sm = requests.get(SOCCER_SUMMARY, params={"event": found[0]["id"]}, timeout=25).json()
        except Exception:  # noqa: BLE001
            sm = {}
        arts += ((sm.get("news") or {}).get("articles")) or []
    return arts


def _plain(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


def check(state: dict, force: bool = False) -> int:
    """Busca titulares nuevos de nuestros partidos y te los manda para decidir. Devuelve cuántos mandó."""
    owner = state.get("owner_chat")
    if not owner:
        return 0
    now = store.now_utc()
    nx = state.get("news_next")
    if not force and nx and now < store.parse_ts(nx):
        return 0
    state["news_next"] = (now + timedelta(hours=CHECK_EVERY_H)).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen = state.setdefault("news_seen", [])
    sent = 0
    since = now - timedelta(hours=18)
    for g in _our_games(state):
        try:
            arts = _articles(g)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            continue
        names = [_plain(n).split()[-1] for n in (g["home"], g["away"])]
        for a in arts:
            aid = str(a.get("id") or a.get("headline") or "")
            head = html.unescape((a.get("headline") or "").strip())
            if not aid or aid in seen or not head:
                continue
            try:
                when = datetime.fromisoformat((a.get("published") or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            if when < since:
                continue
            text = _plain(head + " " + (a.get("description") or ""))
            if not any(n in text for n in names):
                continue
            seen.append(aid)
            link = (((a.get("links") or {}).get("web") or {}).get("href")) or ""
            nid = f"n{len(seen)}{now.strftime('%d%H%M')}"
            pend = state.setdefault("news_pending", {})
            pend[nid] = {"id": nid, "headline": head, "description": html.unescape(a.get("description") or ""),
                         "link": link, "published": a.get("published"), "pick": g["pid"],
                         "home": g["home"], "away": g["away"], "sport": g["sport"]}
            esc = formatting.escape
            telegram.send(owner,
                          f"📰 <b>Noticia de un partido nuestro</b> · pick #{g['pid']} "
                          f"({esc(formatting.team(g['home']))} vs {esc(formatting.team(g['away']))})\n\n"
                          f"<b>{esc(head)}</b>\n" + (f"<i>{esc(pend[nid]['description'])}</i>\n" if pend[nid]["description"] else "")
                          + (f"🔗 {esc(link)}\n" if link else "") + "\n¿La preparamos para Instagram?",
                          BUTTONS(nid))
            sent += 1
            if sent >= MAX_PER_CHECK:
                break
        if sent >= MAX_PER_CHECK:
            break
    del seen[:-400]
    return sent


def _top_articles() -> list[dict]:
    """Titulares grandes de fútbol y NBA (ESPN)."""
    out = []
    for sport, lg in TOP_SOURCES:
        try:
            if sport == "basketball":
                from . import nba
                arts = nba._get("/news", limit=15).get("articles") or []
            else:
                arts = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/news",
                                    params={"limit": 10}, timeout=25).json().get("articles") or []
        except Exception:  # noqa: BLE001
            continue
        for a in arts:
            a["_sport"] = sport
            out.append(a)
    return out


def check_editor(state: dict, force: bool = False) -> int:
    """Con Gemini: noticias importantes (generales + de nuestros picks), elegidas y resumidas en español."""
    from . import llm
    owner = state.get("owner_chat")
    if not owner:
        return 0
    now = store.now_utc()
    from zoneinfo import ZoneInfo
    local = now.astimezone(ZoneInfo(config.TIMEZONE))
    nx = state.get("news_next")
    if not force and ((nx and now < store.parse_ts(nx)) or not (9 <= local.hour < 23)):
        return 0
    state["news_next"] = (now + timedelta(hours=CHECK_EVERY_H)).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen = state.setdefault("news_seen", [])
    since = now - timedelta(hours=18)
    cands = []
    ours = {}
    for g in _our_games(state):
        try:
            for a in _articles(g):
                a["_pick"] = g["pid"]
                a["_sport"] = g["sport"]
                cands.append(a)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    cands += _top_articles()
    rows, ids = [], set()
    for a in cands:
        aid = str(a.get("id") or a.get("headline") or "")
        head = html.unescape((a.get("headline") or "").strip())
        if not aid or aid in seen or aid in ids or not head:
            continue
        try:
            when = datetime.fromisoformat((a.get("published") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < since:
            continue
        ids.add(aid)
        rows.append({"aid": aid, "headline": head, "description": html.unescape(a.get("description") or ""),
                     "link": (((a.get("links") or {}).get("web") or {}).get("href")) or "",
                     "sport": a.get("_sport") or "soccer", "pick": a.get("_pick")})
        if a.get("_pick"):
            ours[aid] = a["_pick"]
    if not rows:
        return 0
    rows = rows[:40]
    listing = "\n".join(f"{i}. [{'NBA' if r['sport'] == 'basketball' else 'Fútbol'}]"
                         f"{' [de nuestro pick]' if r['pick'] else ''} {r['headline']} — {r['description'][:220]}"
                         for i, r in enumerate(rows))
    prompt = (EDITORIAL + "\n\nDe esta lista de titulares de hoy (en inglés), elige SOLO las noticias realmente "
              "interesantes para nuestro público: resultados o hazañas importantes, títulos, premios (Balón de Oro, MVP), "
              "fichajes grandes, lesiones de figuras, sorteos de copas, récords, clásicos o partidos muy atractivos. "
              "Descarta previas genéricas, notas menores, columnas de opinión, rumores sin fuente y apuestas. "
              f"Máximo {MAX_PER_CHECK}. Las marcadas [de nuestro pick] valen un poco más.\n\n{listing}\n\n"
              'Responde en JSON: {"elegidas": [{"i": número, "titulo": "titular en español (máx. 90 caracteres)", '
              '"resumen": "1 o 2 frases en español, fieles al texto", "categoria": "Lesión|Fichaje|Resultado|Premio|'
              'Sorteo|Récord|Partido|Otra", "importancia": 1-5}]}')
    try:
        got = llm.ask_json(prompt, 0.2).get("elegidas") or []
    except Exception as e:  # noqa: BLE001
        print(f"Editor de noticias: {e}")
        state["news_next"] = (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return 0
    for r in rows:   # lo revisado no se vuelve a ofrecer
        seen.append(r["aid"])
    del seen[:-600]
    sent = 0
    esc = formatting.escape
    for c in sorted(got, key=lambda x: -int(x.get("importancia") or 0)):
        try:
            r = rows[int(c["i"])]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        if int(c.get("importancia") or 0) < (3 if r["pick"] else 4):
            continue
        nid = f"n{now.strftime('%d%H%M')}{sent}"
        state.setdefault("news_pending", {})[nid] = dict(r, id=nid, titulo=c.get("titulo"), resumen=c.get("resumen"),
                                                         categoria=c.get("categoria"))
        tag = f" · pick #{r['pick']}" if r["pick"] else ""
        telegram.send(owner, f"📰 <b>Noticia sugerida</b> · {esc(c.get('categoria') or 'Noticia')}{tag}\n\n"
                             f"<b>{esc(c.get('titulo') or r['headline'])}</b>\n{esc(c.get('resumen') or '')}\n\n"
                             + (f"🔗 Fuente (ESPN, en inglés): {esc(r['link'])}\n" if r["link"] else "")
                             + "\n¿La preparamos para Instagram?", BUTTONS(nid))
        sent += 1
        if sent >= MAX_PER_CHECK:
            break
    return sent


def test_file(state: dict) -> None:
    """data/news_test.json ({"id": "..."}): prueba ahora la conexión con Gemini y busca noticias (una vez)."""
    from . import llm
    path = os.path.join(config.ROOT, "data", "news_test.json")
    owner = state.get("owner_chat")
    if not os.path.exists(path) or not owner:
        return
    try:
        with open(path, encoding="utf-8") as f:
            req = json.load(f)
    except Exception:  # noqa: BLE001
        return
    if not req.get("id") or req["id"] in (state.get("news_test_done") or []):
        return
    state.setdefault("news_test_done", []).append(req["id"])
    if req.get("resend"):   # volver a proponer una noticia puntual (ej. «Curry 44»)
        if not resend(state, str(req["resend"]), req.get("title")):
            telegram.send(owner, f"📰 No encontré la noticia «{formatting.escape(str(req['resend']))}» para proponértela de nuevo.")
        return
    if not llm.enabled():
        telegram.send(owner, "⚠️ El bot no ve la clave GEMINI_API_KEY. Revisa que el nombre del secreto en GitHub sea exacto.")
        return
    try:
        hi = llm.ask_json('Responde en JSON {"ok": true, "saludo": "un saludo corto en español para el dueño de Stakevision"}', 0.3)
        telegram.send(owner, f"🤖 Gemini conectado ({llm.LAST_MODEL}): {formatting.escape(str(hi.get('saludo', '')))}\n"
                             "Ahora busco noticias importantes para proponerte…")
    except Exception as e:  # noqa: BLE001
        telegram.send(owner, f"⚠️ No pude conectar con Gemini: {formatting.escape(str(e))}")
        return
    try:
        n = check_editor(state, force=True)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        telegram.send(owner, f"⚠️ Falló la búsqueda de noticias: {formatting.escape(str(e))}")
        return
    if not n:
        telegram.send(owner, "📰 Por ahora no encontré noticias nuevas que valgan la pena. Reviso de nuevo en 2 horas.")


def resend(state: dict, query: str, title: str | None = None) -> bool:
    """Vuelve a proponer (con los botones de siempre) una noticia que coincide con todas las palabras de query:
    primero entre las ya vistas por el bot, luego en los titulares actuales de ESPN."""
    words = [w for w in re.split(r"\s+", query.lower()) if w]

    def hit(*texts) -> bool:
        blob = " ".join(str(t or "") for t in texts).lower()
        return all(w in blob for w in words)

    row = None
    for it in reversed(list((state.get("news_items") or {}).values()) + list((state.get("news_pending") or {}).values())):
        if hit(it.get("orig"), it.get("headline"), it.get("titulo"), it.get("name"), it.get("_source", "")[:1500],
               it.get("description")):
            row = {"headline": it.get("orig") or it.get("headline"), "link": it.get("link") or "",
                   "description": it.get("description") or (it.get("_source") or "")[:600],
                   "sport": it.get("sport") or "basketball", "pick": None,
                   "titulo": title or it.get("titulo") or it.get("headline"), "resumen": it.get("resumen") or it.get("sub")}
            break
    if not row:
        for a in _top_articles():
            head = html.unescape(a.get("headline") or "")
            desc = html.unescape(a.get("description") or "")
            if hit(head, desc):
                row = {"headline": head, "description": desc, "sport": a.get("_sport") or "soccer", "pick": None,
                       "link": (((a.get("links") or {}).get("web") or {}).get("href")) or "", "titulo": title or head}
                break
    if not row:
        return False
    nid = f"n{store.now_utc().strftime('%d%H%M')}r"
    state.setdefault("news_pending", {})[nid] = dict(row, id=nid, categoria="Récord")
    esc = formatting.escape
    telegram.send(state["owner_chat"], f"📰 <b>Noticia sugerida</b> (de nuevo, con los formatos nuevos)\n\n"
                  f"<b>{esc(row.get('titulo') or row['headline'])}</b>\n{esc(row.get('resumen') or '')}\n\n"
                  + (f"🔗 Fuente (ESPN, en inglés): {esc(row['link'])}\n" if row["link"] else "")
                  + "\n¿La preparamos para Instagram?", BUTTONS(nid))
    return True


def _clean(item: dict) -> dict:
    """Valida lo que devuelve el editor (largos y tipos), para que la imagen salga bien."""
    out = dict(item)
    out["headline"] = str(item.get("headline") or "").upper()[:60]
    out["tag"] = str(item.get("tag") or "NOTICIA").upper()[:16]
    out["kicker"] = str(item.get("kicker") or "").upper()[:48]
    out["sub"] = str(item.get("sub") or "")[:90]
    out["facts"] = [str(f)[:95] for f in (item.get("facts") or []) if str(f).strip()][:3] or ["(sin datos)"]
    st = str(item.get("status") or "").upper()[:26]
    if st:
        out["status"] = st
    else:
        out.pop("status", None)
    cols = item.get("colors") or []
    try:
        out["colors"] = [[max(0, min(255, int(v))) for v in c][:3] for c in cols][:2]
        assert len(out["colors"]) == 2 and all(len(c) == 3 for c in out["colors"])
    except Exception:  # noqa: BLE001
        out["colors"] = [[30, 40, 60], [80, 90, 110]]
    out["caption"] = str(item.get("caption") or "")[:2100]
    out["name"] = str(item.get("name") or item.get("player") or "")[:40]
    out["line"] = str(item.get("line") or item.get("sub") or "")[:90]
    stv = item.get("stat") if isinstance(item.get("stat"), dict) else {}
    val = str((stv or {}).get("value") or "").strip()
    out["stat"] = {"value": val[:6], "label": str(stv.get("label") or "")[:14]} if val and len(val) <= 6 else None
    out["match"] = _clean_match(item.get("match"))
    sts = []
    for x in item.get("stats") or []:
        if isinstance(x, dict) and str(x.get("value") or "").strip() and len(str(x["value"]).strip()) <= 4:
            sts.append({"value": str(x["value"]).strip(), "label": str(x.get("label") or "").upper()[:6]})
    out["stats"] = sts[:4]
    fmt = str(item.get("format") or "").lower().strip()
    out["format"] = fmt if fmt in LAYOUTS else None
    return out


def _rgb(c, default):
    try:
        v = [max(0, min(255, int(x))) for x in c][:3]
        return v if len(v) == 3 else default
    except Exception:  # noqa: BLE001
        return default


def _clean_match(m) -> dict | None:
    """Partido de la noticia (para «versus» y «resultado»): equipos, figura, colores y marcador si ya se jugó."""
    if not isinstance(m, dict):
        return None
    out = {}
    for side, dc in (("home", [30, 60, 140]), ("away", [160, 30, 40])):
        t = m.get(side)
        if not isinstance(t, dict) or not str(t.get("name") or "").strip():
            return None
        sc = t.get("score")
        try:
            sc = int(sc) if sc not in (None, "", "null") else None
        except (TypeError, ValueError):
            sc = None
        out[side] = {"name": str(t["name"])[:40], "short": str(t.get("short") or t["name"])[:16],
                     "player": str(t.get("player") or "")[:40], "color": _rgb(t.get("color") or dc, dc), "score": sc}
    out["when"] = str(m.get("when") or "")[:40]
    out["played"] = out["home"]["score"] is not None and out["away"]["score"] is not None
    return out


FIELDS = ('{"tag": "LESIÓN|BAJA|FICHAJE|PREMIO|CAMPEÓN|RÉCORD|SORTEO|RESULTADO|NOTICIA", '
          '"kicker": "EQUIPO O COMPETENCIA · LIGA (mayúsculas)", "headline": "titular de 4 a 7 palabras", '
          '"sub": "1 frase de contexto (máx. 80 caracteres)", "facts": ["dato 1 (máx. 85 caracteres)", "dato 2", '
          '"dato 3 opcional"], "status": "estado corto opcional (ej. DIAGNÓSTICO PENDIENTE) o vacío", '
          '"colors": [[r,g,b],[r,g,b]] colores del equipo protagonista, "player": "jugador protagonista o vacío", '
          '"name": "nombre corto del protagonista para la imagen (ej. Stephen Curry) o del equipo", '
          '"stat": {"value": "la cifra clave si la hay, solo el número (ej. 44)", "label": "qué es (PUNTOS, GOLES, '
          'AÑOS, TÍTULOS…)"} o null si no hay una cifra protagonista, '
          '"line": "UNA frase corta para el diseño visual (máx. 70 caracteres)", '
          '"teams": ["nombre completo del equipo", "apodo"], "sport": "soccer|basketball", '
          '"match": si la noticia trata de UN partido concreto (que viene o que ya se jugó): {"home": {"name": '
          '"nombre del equipo local", "short": "nombre corto (ej. Warriors, Colo-Colo)", "player": "su figura o '
          'vacío", "color": [r,g,b], "score": número o null si no se ha jugado}, "away": {igual}, "when": "ej. Hoy '
          '· 22:00 (Chile) o Final"}; si no trata de un partido, null, '
          '"stats": si hay un jugador figura del partido, hasta 4 cifras de SU planilla tal como dice el texto '
          '[{"value": "44", "label": "PTS"}, {"value": "8", "label": "REB"}] (fútbol: GOLES, ASIST, TIROS…), o [], '
          '"format": "figura (la gran actuación de un jugador en un partido ya jugado: su planilla y el marcador) | '
          'hero (actuación individual con una cifra: puntos, goles) | versus (partido que viene, '
          'previa o duelo) | result (resultado de un partido importante) | impact (fichaje, lesión, premio, '
          'campeón, polémica) | classic (varios datos, sin protagonista claro)", '
          '"caption": "texto para Instagram en español: 2-3 párrafos cortos con los hechos, una pregunta para '
          'comentarios, la línea \'📲 Pick gratis todos los días en nuestro canal de Telegram (link en la bio)\', '
          'la línea \'Fuentes: ...\' y 4-6 hashtags (#Stakevision + liga + equipo + jugador)"}')


def draft(state: dict, nid: str) -> bool:
    """«Sí, prepárala» (con Gemini): redacta al instante en español y te la manda para revisar."""
    from . import llm
    item = (state.get("news_pending") or {}).pop(nid, None)
    if not item:
        return False
    src = _article_text(item.get("link"), item.get("description") or "")
    prompt = (EDITORIAL + "\n\nRedacta esta noticia para una imagen y un Reel de Instagram.\n"
              f"Titular original: {item['headline']}\nResumen: {item.get('description', '')}\n"
              f"Texto fuente:\n{src}\n\nResponde en JSON con este formato: {FIELDS}")
    data = _clean(llm.ask_json(prompt, 0.4))
    data.update(id=nid, sources=data.get("sources") or "ESPN", link=item.get("link"), _source=src[:6000],
                rev=0, orig=item.get("headline"))
    state.setdefault("news_items", {})[nid] = data
    _prepare(state, data)
    return True


def revise(state: dict, text: str) -> bool:
    """«Modificar»: aplica lo que pediste y te manda la versión nueva."""
    from . import llm
    ed = state.pop("news_edit", None) or {}
    item = (state.get("news_items") or {}).get(ed.get("nid") or "")
    owner = state["owner_chat"]
    if not item:
        return False
    cur = {k: item.get(k) for k in ("tag", "kicker", "headline", "sub", "facts", "status", "colors", "player", "teams",
                                    "sport", "caption", "name", "line", "stat", "match", "format")}
    prompt = (EDITORIAL + "\n\nEsta es la noticia actual (JSON):\n" + json.dumps(cur, ensure_ascii=False) +
              f"\n\nEl dueño pide este cambio: «{text}»\nAplica el cambio sin inventar datos (texto fuente abajo) y "
              f"devuelve el JSON completo con el mismo formato.\n\nTexto fuente:\n{item.get('_source', '')}")
    try:
        data = _clean(llm.ask_json(prompt, 0.4))
    except Exception as e:  # noqa: BLE001
        telegram.send(owner, f"⚠️ No pude aplicar el cambio: {formatting.escape(str(e))}")
        return True
    old = (state.get("ig_jobs") or {}).get(item["id"])
    if old and old.get("status") == "draft":
        old["status"] = "replaced"
    item.update(data)
    item["rev"] = item.get("rev", 0) + 1
    telegram.send(owner, "✏️ Listo, aquí va la versión nueva 👇")
    _prepare(state, item)
    return True


def _next_window(now):
    """Inicio del próximo horario de publicación (o ahora, si estamos dentro de uno)."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(config.TIMEZONE)
    local = now.astimezone(tz)
    for add in (0, 1):
        day = (local + timedelta(days=add)).date()
        for a, b in WINDOWS:
            start = datetime(day.year, day.month, day.day, a, tzinfo=tz)
            end = datetime(day.year, day.month, day.day, b, tzinfo=tz)
            if local < end:
                return max(start, local).astimezone(timezone.utc)
    return now


def _posted_today(state: dict) -> int:
    from zoneinfo import ZoneInfo
    today = store.now_utc().astimezone(ZoneInfo(config.TIMEZONE)).date().isoformat()
    return sum(1 for j in (state.get("ig_jobs") or {}).values() if (j.get("posted_at") or "")[:10] == today
               or (j.get("day") == today and j.get("status") in ("queued", "scheduled")))


def request(state: dict, nid: str) -> bool:
    """«Sí, prepárala»: queda pedida para que Claude la redacte en español con datos verificados."""
    item = (state.get("news_pending") or {}).pop(nid, None)
    if not item:
        return False
    rows = _load(REQ)
    item.update(status="pending", requested_at=store.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"))
    rows.append(item)
    _save(REQ, rows[-50:])
    return True


# ---------------------------------------------------------------- 3) listas para publicar
LAYOUTS = ("figura", "hero", "versus", "result", "impact", "classic")
LAYOUT_NAME = {"figura": "Figura (planilla + marcador)", "hero": "Héroe (foto + cifra)", "versus": "Versus (cara a cara)", "result": "Resultado (marcador)",
               "impact": "Impacto (foto + titular)", "classic": "Clásico (datos)"}


def _photo_for(item: dict):
    from . import commons
    sport = item.get("sport") or ("basketball" if "NBA" in item.get("kicker", "") else "soccer")
    if item.get("no_photo"):
        return None
    own = _own_photo(item, "main")
    if own:
        return own
    if item.get("photo_file"):
        return commons.file_photo(item["photo_file"])
    if item.get("player"):
        return (commons.player_photo(item["player"], item.get("teams") or [], need_team=True, sport=sport)
                or commons.player_photo(item["player"], item.get("teams") or [], need_team=True, sport=sport, years=10)
                or commons.player_photo(item["player"], item.get("teams") or [], need_team=False, sport=sport))
    if item.get("teams"):
        return commons.team_photo(item["teams"][0], sport)
    return None


def _layouts_for(item: dict, has_photo: bool) -> list[str]:
    """Plantillas que sirven para esta noticia; la primera es la que se usa (la que sugirió el editor, si aplica)."""
    m = item.get("match") or None
    opts = []
    if m and m.get("played") and (item.get("player") or item.get("name")) and \
            (len(item.get("stats") or []) >= 2 or item.get("sport") == "basketball"):
        opts.append("figura")   # la figura del partido: su planilla + el marcador (aunque no haya foto)
    if m and m.get("played"):
        opts.append("result")
    elif m:
        opts.append("versus")
    if has_photo:
        opts += (["hero"] if item.get("stat") else []) + ["impact"]
    opts.append("classic")
    fmt = item.get("format")
    if fmt == "hero" and "figura" in opts:
        fmt = "figura"   # gran actuación en un partido ya jugado: la planilla completa luce más que una sola cifra
    if fmt in opts:
        opts.remove(fmt)
        opts.insert(0, fmt)
    return opts


def _side_photo(t: dict, sport: str):
    """Foto de un lado del versus: su figura con la camiseta del equipo, o una del equipo."""
    from . import commons
    if t.get("_no_photo"):
        return None
    if t.get("_own"):
        return t["_own"]
    try:
        if t.get("player"):
            got = (commons.player_photo(t["player"], [t["name"], t["short"]], need_team=True, sport=sport)
                   or commons.player_photo(t["player"], [t["name"], t["short"]], need_team=True, sport=sport, years=10))
            return got   # si no hay foto suya con el club, mitad con el color del equipo (no otra foto con su nombre)
        return commons.team_photo(t["name"], sport)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return None


def _versus_data(item: dict, n: dict) -> dict:
    m = item["match"]
    sport = item.get("sport") or ("basketball" if "NBA" in item.get("kicker", "") else "soccer")
    v = {"tag": n.get("tag") or "PARTIDO", "kicker": n.get("kicker", ""), "when": m.get("when", ""),
         "source": n.get("source", "")}
    authors = []
    for side in ("home", "away"):
        t = dict(m[side])
        t["color"] = tuple(t["color"])
        t["logo"] = _crest(t, sport)
        t["_no_photo"] = bool(item.get("no_photo"))
        t["_own"] = _own_photo(item, side)
        got = _side_photo(t, sport)
        if got:
            t["photo"] = got[0]
            a = (got[1] or {}).get("author")
            if a and a not in authors:
                authors.append(a)
            if (got[1] or {}).get("own"):
                v["_own_credit"] = True
        v[side] = t
    if authors:
        v["credit"] = ("Fotos: " + ", ".join(authors)[:70] + (" (con permiso)" if v.pop("_own_credit", False) else
                                                              " / Wikimedia Commons, modificadas"))
    return v


PHOTO_DIR = os.path.join(config.ROOT, "data", "news_photos")


def _own_photo(item: dict, side: str):
    """Foto que mandaste tú (con permiso del autor) para esta noticia: (jpeg, crédito) o None.
    side: 'main' (la foto principal), 'home' o 'away' (cada lado del versus)."""
    ph = (item.get("own_photos") or {}).get(side)
    if not ph and side == "main":
        ph = next(iter((item.get("own_photos") or {}).values()), None)
    if not ph:
        return None
    try:
        with open(os.path.join(PHOTO_DIR, ph["file"]), "rb") as f:
            data = f.read()
    except OSError:
        return None
    return data, {"author": ph["credit"], "license": "con permiso", "own": True}


def receive_photo(state: dict, msg: dict) -> bool:
    """Llegó la foto que pediste con «📷 Cambiar foto»: se guarda con su crédito y se rearma la noticia."""
    wait = state.get("news_photo") or {}
    owner = state["owner_chat"]
    item = (state.get("news_items") or {}).get(wait.get("nid") or "")
    if not item or store.now_utc() - store.parse_ts(wait["at"]) > timedelta(minutes=60):
        state.pop("news_photo", None)
        return False
    if msg.get("photo"):
        fid = msg["photo"][-1]["file_id"]
    elif (msg.get("document") or {}).get("mime_type", "").startswith("image/"):
        fid = msg["document"]["file_id"]
    else:
        telegram.send(owner, "📷 Eso no es una imagen. Mándame la foto (como foto o como archivo).")
        return True
    cap = (msg.get("caption") or "").strip()
    side = "main"
    low = cap.lower()
    if (item.get("match") or {}) and low.split(" ", 1)[0] in ("local", "visita", "izq", "der", "izquierda", "derecha"):
        side = "home" if low.split(" ", 1)[0] in ("local", "izq", "izquierda") else "away"
        cap = cap.split(" ", 1)[1].strip() if " " in cap else ""
    elif item.get("layout") == "versus":
        side = "home" if not (item.get("own_photos") or {}).get("home") else "away"
    credit = cap.removeprefix("Foto:").removeprefix("foto:").strip()
    if not credit:
        telegram.send(owner, "📷 Me falta el crédito del autor. Vuelve a mandar la foto con el nombre o @ del autor "
                             "en el texto de la foto (ej. «@juanfotos»). Sin crédito no la uso.")
        return True
    os.makedirs(PHOTO_DIR, exist_ok=True)
    name = f"{item['id']}-{side}-{store.now_utc().strftime('%H%M%S')}.jpg"
    with open(os.path.join(PHOTO_DIR, name), "wb") as f:
        f.write(telegram.download(fid))
    item.setdefault("own_photos", {})[side] = {"file": name, "credit": credit[:60]}
    item.pop("no_photo", None)
    if side != "main":
        item["layout"] = "versus"
    elif item.get("layout") == "classic":
        item.pop("layout", None)
    state.pop("news_photo", None)
    old = (state.get("ig_jobs") or {}).get(item["id"])
    if old and old.get("status") == "draft":
        old["status"] = "replaced"
    item["rev"] = item.get("rev", 0) + 1
    where = {"home": " (lado local)", "away": " (lado visita)"}.get(side, "")
    telegram.send(owner, f"📷 Foto recibida{where}, crédito: {formatting.escape(credit[:60])}. Aquí va la versión nueva 👇")
    _prepare(state, item)
    return True


def _crest(t: dict, sport: str):
    from . import crest
    try:
        return crest.get(t["name"], sport) or crest.get(t.get("short") or "", sport)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return None


def _figura_data(item: dict, n: dict) -> dict | None:
    """Datos de la «Figura». En NBA se toman de ESPN (planilla y marcador verificados); si no, del texto."""
    sport = item.get("sport") or ("basketball" if "NBA" in item.get("kicker", "") else "soccer")
    player = item.get("player") or item.get("name") or ""
    g = None
    if sport == "basketball":
        try:
            from . import espnstats
            g = espnstats.nba_figura(player)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    if not g:
        m = item.get("match") or {}
        if not (m.get("played") and len(item.get("stats") or []) >= 2):
            return None
        h, a = dict(m["home"]), dict(m["away"])
        h["logo"], a["logo"] = _crest(h, sport), _crest(a, sport)
        h["color"], a["color"] = tuple(h["color"]), tuple(a["color"])
        teams = [x.lower() for x in item.get("teams") or []]
        side = "away" if any(x and (x in a["name"].lower() or x in a["short"].lower()) for x in teams) else "home"
        g = {"player": player, "stats": [(x["value"], x["label"]) for x in item["stats"]], "focus": side,
             "color": (h if side == "home" else a)["color"], "home": h, "away": a,
             "winner": "home" if h["score"] > a["score"] else "away" if a["score"] > h["score"] else None,
             "competition": (item.get("kicker") or "").split("·")[0].strip(), "team": (h if side == "home" else a)["name"]}
    if g.get("team") and g["team"] not in (item.get("teams") or []):   # la foto se valida con SU equipo
        item = dict(item, teams=[g["team"]] + list(item.get("teams") or []), player=g["player"])
    got = None if item.get("no_photo") else _photo_for(item)
    if got:
        cr = got[1] or {}
        g["photo"] = got[0]
        g["credit"] = (f"Foto: {cr.get('author')} (con permiso)" if cr.get("own") else
                       f"Foto: {cr.get('author')} / Wikimedia Commons ({cr.get('license')}), modificada")
    return g


def _result_data(item: dict, n: dict) -> dict:
    m = item["match"]
    sport = item.get("sport") or ("basketball" if "NBA" in item.get("kicker", "") else "soccer")
    h, a = dict(m["home"]), dict(m["away"])
    h["logo"], a["logo"] = _crest(h, sport), _crest(a, sport)
    win = "home" if h["score"] > a["score"] else "away" if a["score"] > h["score"] else None
    g = {"colors": n["colors"], "kicker": n.get("kicker", ""), "winner": win, "when": m.get("when") or "Final",
         "notes": [f for f in n.get("facts") or [] if f != "(sin datos)"][:3], "source": n.get("source", ""),
         "home": dict(h, color=tuple(h["color"])), "away": dict(a, color=tuple(a["color"]))}
    if n.get("photo"):
        g["photo"], g["credit"] = n["photo"], (n.get("credit") or "").replace("Foto de referencia:", "Foto:")
    return g


def _render(item: dict) -> tuple[bytes, str | None, dict]:
    """Imagen según la plantilla: «héroe» (foto + cifra), «impacto» (foto + titular) o «clásico» (datos)."""
    from . import newsimage
    photo, credit = None, None
    try:
        got = _photo_for(item)
        if got:
            photo = got[0]
            cr = got[1] or {}
            credit = (f"Foto: {cr.get('author')} (con permiso)" if cr.get("own") else
                      f"Foto de referencia: {cr.get('author')} / Wikimedia Commons ({cr.get('license')}), modificada")
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    n = {k: item[k] for k in ("tag", "kicker", "headline", "sub", "facts", "status", "name", "line", "stat") if k in item}
    n["colors"] = [tuple(c) for c in item.get("colors") or [(30, 40, 60), (80, 90, 110)]]
    n["source"] = "Fuentes: " + item.get("sources", "ESPN")
    options = _layouts_for(item, bool(photo))
    layout = item.get("layout") if item.get("layout") in options else options[0]
    item["layout"], item["_layouts"] = layout, options
    if photo:
        n["photo"], n["credit"] = photo, credit
    n["layout"] = layout
    if layout == "versus":
        n["versus"] = _versus_data(item, n)
        cr = n["versus"].get("credit")
        return newsimage.render_versus(n["versus"]), cr, n
    if layout == "figura":
        fg = _figura_data(item, n)
        if fg:
            n["figura"] = fg
            return newsimage.render_figura(fg), fg.get("credit"), n
        options.remove("figura")
        layout = options[0]
        item["layout"], item["_layouts"], n["layout"] = layout, options, layout
        if layout == "versus":
            n["versus"] = _versus_data(item, n)
            return newsimage.render_versus(n["versus"]), n["versus"].get("credit"), n
    if layout == "result":
        n["result"] = _result_data(item, n)
        return newsimage.render_postgame(n["result"]), credit, n
    img = (newsimage.render_hero(dict(n, credit=(credit or "").replace("Foto de referencia:", "Foto:"))) if layout == "hero" else
           newsimage.render_impact(dict(n, credit=(credit or "").replace("Foto de referencia:", "Foto:"))) if layout == "impact" else
           newsimage.render_news(n))
    return img, credit, n


def _prepare(state: dict, item: dict, approved: bool = False) -> None:
    """Imagen + Reel de una noticia redactada; te la manda para revisar (o la deja en cola si ya la aprobaste)."""
    from . import instagram
    owner = state["owner_chat"]
    nid = item["id"]
    img, credit, nd = _render(item)
    key = f"news-{nid}" + (f"-r{item['rev']}" if item.get("rev") else "")
    instagram.save_image(key, img)
    caption = item["caption"]
    if credit and "Wikimedia" in credit and "Wikimedia" not in caption:
        caption += "\n\n📸 Foto de referencia: Wikimedia Commons (licencia libre), modificada."
    job = {"key": key, "caption": caption, "status": "draft", "title": item.get("headline", "")}
    reel_mp4 = None
    try:   # Reel (video vertical con animación): es lo que más alcance da en Instagram
        from . import reel
        nr = dict(nd, credit=(nd.get("credit") or "").replace("Foto de referencia:", "Foto:"))
        lay = nd.get("layout")
        reel_mp4, cover = (reel.still(img) if lay == "figura" else
                           reel.versus(nd["versus"]) if lay == "versus" else
                           reel.postgame(nd["result"]) if lay == "result" else
                           reel.hero(nr) if lay == "hero" else reel.impact(nr) if lay == "impact" else reel.news(nr))
        instagram.save_video(key, reel_mp4, cover)
        job["reel"] = key
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    job["layout"] = nd.get("layout")
    state.setdefault("ig_jobs", {})[nid] = job
    if approved:
        job["status"] = "queued"
        job["mode"] = "reel" if job.get("reel") else "image"
        what = "Reel" if job.get("reel") else "imagen"
        if reel_mp4:
            telegram.send_video(owner, reel_mp4, caption=f"📰 <b>Noticia para Instagram</b> (aprobada en el chat): "
                                f"el {what} se publica en unos minutos.")
        else:
            telegram.send_photo(owner, img, caption="📰 <b>Noticia para Instagram</b> (aprobada en el chat): "
                                "se publica en unos minutos.")
        return
    cap = (f"📰 <b>Noticia lista para revisar</b> · diseño {LAYOUT_NAME.get(nd.get('layout'), '')}\n"
           "Abajo va el texto para Instagram. Puedes publicarla, dejarla para el horario de más movimiento, "
           "pedirme cambios, probar otro diseño o descartarla.")
    try:
        msg = telegram.send_video(owner, reel_mp4, caption=cap) if reel_mp4 else telegram.send_photo(owner, img, caption=cap)
    except Exception:  # noqa: BLE001
        msg = telegram.send_photo(owner, img, caption=cap)
    telegram.send(owner, "<pre>" + formatting.escape(caption) + "</pre>")
    btns = PUBLISH_BUTTONS(nid, bool(reel_mp4))
    if len(item.get("_layouts") or []) > 1 and nid in (state.get("news_items") or {}):
        btns.insert(-1, [("🎨 Otro diseño", f"nd:{nid}")])
    telegram.set_buttons(owner, msg["message_id"], btns)


def ready(state: dict) -> None:
    """Noticias ya redactadas a mano (data/news_ready.json): te llegan para revisar o, si ya la aprobaste
    en el chat (approved), se publican directo en Instagram."""
    owner = state.get("owner_chat")
    if not owner:
        return
    done = state.setdefault("news_done", [])
    for item in _load(READY):
        nid = item.get("id")
        if not nid or nid in done:
            continue
        done.append(nid)
        try:
            _prepare(state, item, bool(item.get("approved")))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            telegram.send(owner, f"⚠️ No pude armar la noticia {formatting.escape(nid)}: {formatting.escape(str(e))}")
    del done[:-200]


def callback(state: dict, cb: dict, action: str, nid: str) -> None:
    from . import llm
    owner = state["owner_chat"]
    mid = cb["message"]["message_id"]
    if action == "nq":
        if llm.enabled() and nid in (state.get("news_pending") or {}):
            telegram.edit_buttons_off(owner, mid, "✅ Aprobada: la estoy redactando en español…")
            telegram.answer(cb["id"], "La redacto")
            try:
                draft(state, nid)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                telegram.send(owner, f"⚠️ No pude redactarla: {formatting.escape(str(e))}. "
                                     "Vuelve a intentarlo en un rato desde el mismo mensaje.")
                state.setdefault("news_pending", {})
            return
        ok = request(state, nid)
        telegram.edit_buttons_off(owner, mid, "✅ Pedida. Para redactarla en español, pídele a Claude: «prepara las noticias "
                                  "pendientes»; luego te llega aquí lista para aprobar" if ok else "Ya estaba procesada")
        telegram.answer(cb["id"], "La preparo" if ok else "Ya procesada")
    elif action == "nx":
        (state.get("news_pending") or {}).pop(nid, None)
        telegram.edit_buttons_off(owner, mid, "✖️ Descartada")
        telegram.answer(cb["id"], "Descartada")
    elif action == "nd":   # otro diseño: la siguiente plantilla disponible
        item = (state.get("news_items") or {}).get(nid)
        job = (state.get("ig_jobs") or {}).get(nid)
        if not item or not job or job.get("status") != "draft":
            telegram.answer(cb["id"], "Ya estaba procesada")
            return
        opts = item.get("_layouts") or ["classic"]
        cur = item.get("layout") if item.get("layout") in opts else opts[0]
        item["layout"] = opts[(opts.index(cur) + 1) % len(opts)]
        item["rev"] = item.get("rev", 0) + 1
        job["status"] = "replaced"
        telegram.edit_buttons_off(owner, mid, f"🎨 Probando diseño {LAYOUT_NAME[item['layout']]} 👇")
        telegram.answer(cb["id"], "Armando otro diseño")
        _prepare(state, item)
    elif action in ("nf", "nz"):   # cambiar foto (una tuya, con permiso) / sin foto
        item = (state.get("news_items") or {}).get(nid)
        job = (state.get("ig_jobs") or {}).get(nid)
        if not item or not job or job.get("status") != "draft":
            telegram.answer(cb["id"], "Ya estaba procesada")
            return
        if action == "nf":
            state["news_photo"] = {"nid": nid, "at": store.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")}
            telegram.answer(cb["id"], "Mándame la foto")
            vs = " Si es un versus, empieza el texto con «local» o «visita» para decirme a qué lado va." if item.get("match") else ""
            telegram.send(owner, "📷 Mándame la foto (mejor como archivo, para que no pierda calidad) y en el texto de la "
                                 "foto escribe el crédito del autor (ej. «@juanfotos»)." + vs +
                                 "\n\n⚠️ Usa solo fotos tuyas o con permiso del autor: las fotos de agencia (Getty, AP, "
                                 "NBA) o copiadas de otras cuentas pueden traer denuncias en Instagram.")
            return
        item["no_photo"] = True
        item.pop("own_photos", None)
        item["rev"] = item.get("rev", 0) + 1
        job["status"] = "replaced"
        telegram.edit_buttons_off(owner, mid, "🚫 Sin foto: la armo con colores y escudos 👇")
        telegram.answer(cb["id"], "Sin foto")
        _prepare(state, item)
    elif action == "ne":
        if nid not in (state.get("news_items") or {}):
            telegram.answer(cb["id"], "Esta noticia no se puede modificar aquí")
            return
        state["news_edit"] = {"nid": nid, "at": store.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")}
        telegram.answer(cb["id"], "Escríbeme el cambio")
        telegram.send(owner, "✏️ Escríbeme qué quieres cambiar. Ej.: «titular más corto», «quita el segundo dato», "
                             "«más emoción en el texto», «agrega que es su segunda lesión».")
    elif action in ("np", "ni", "nn", "nt", "nh"):
        job = (state.get("ig_jobs") or {}).get(nid)
        if not job or job["status"] != "draft":
            telegram.answer(cb["id"], "Ya estaba procesada")
            return
        if action == "nn":
            job["status"] = "skipped"
            telegram.edit_buttons_off(owner, mid, "✖️ No se publica")
            telegram.answer(cb["id"], "Listo")
            return
        from zoneinfo import ZoneInfo
        job["mode"] = "reel" if action in ("np", "nt") and job.get("reel") else "image"
        now = store.now_utc()
        at = _next_window(now) if action in ("nt", "nh") else now
        if _posted_today(state) >= DAILY_MAX and at.astimezone(ZoneInfo(config.TIMEZONE)).date() == \
                now.astimezone(ZoneInfo(config.TIMEZONE)).date():
            local = now.astimezone(ZoneInfo(config.TIMEZONE))
            nxt = datetime(local.year, local.month, local.day, WINDOWS[0][0], tzinfo=ZoneInfo(config.TIMEZONE)) + timedelta(days=1)
            at = nxt.astimezone(timezone.utc)
        job["day"] = at.astimezone(ZoneInfo(config.TIMEZONE)).date().isoformat()
        what = "Reel" if job["mode"] == "reel" else "imagen"
        if at <= now + timedelta(minutes=2):
            job["status"] = "queued"
            telegram.edit_buttons_off(owner, mid, f"⏳ Se publica en Instagram ({what}) en unos minutos")
        else:
            job["status"] = "scheduled"
            job["at"] = at.strftime("%Y-%m-%dT%H:%M:%SZ")
            hhmm = at.astimezone(ZoneInfo(config.TIMEZONE)).strftime("%d/%m %H:%M")
            telegram.edit_buttons_off(owner, mid, f"⏰ Programada en Instagram ({what}) para el {hhmm}")
        telegram.answer(cb["id"], "Listo")


def publish_jobs(state: dict) -> None:
    """Publica en Instagram las noticias aprobadas (cuando la imagen ya está en la web)."""
    from . import instagram
    owner = state.get("owner_chat")
    now = store.now_utc()
    for nid, job in (state.get("ig_jobs") or {}).items():
        if job.get("status") == "scheduled" and now >= store.parse_ts(job["at"]):
            job["status"] = "queued"
        if job.get("status") != "queued":
            continue
        reel_mode = job.get("mode") == "reel" and job.get("reel")
        if not (instagram.video_live(job["reel"]) if reel_mode else instagram.image_live(job["key"])):
            continue
        try:
            link = instagram.reel_step(state, job, job["caption"]) if reel_mode else instagram.publish(state, job["key"], job["caption"])
            if reel_mode and link is None:
                continue   # Instagram aún procesa el video: se revisa en la próxima vuelta
            job["status"] = "posted"
            from zoneinfo import ZoneInfo
            job["posted_at"] = now.astimezone(ZoneInfo(config.TIMEZONE)).isoformat()
            if owner:
                telegram.send(owner, f"✅ Noticia publicada en Instagram ({'Reel' if reel_mode else 'imagen'})"
                              + (f"\n{link}" if link else ""))
        except instagram.InstagramError as e:
            job["tries"] = job.get("tries", 0) + 1
            if job["tries"] >= 3:
                job["status"] = "failed"
                if owner:
                    telegram.send(owner, f"⚠️ No pude publicar la noticia en Instagram: {formatting.escape(str(e))}")
