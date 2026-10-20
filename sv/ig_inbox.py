"""Respuestas automáticas en Instagram (mensajes directos y comentarios). Opción A: sin IA.

Reconoce las preguntas típicas por palabras clave y responde con textos fijos y honestos.
Lo que no entiende, lo delicado (pagos, reclamos, problemas con el juego) o lo dudoso
te lo avisa por Telegram para que respondas tú. Revisa cada 5 minutos (junto al bot).

Reglas que nunca se rompen: no promete ganancias, no nombra casas de apuestas,
no conversa con menores y siempre recuerda que es +18.
"""
from __future__ import annotations

import json
import re
import unicodedata

from . import config, formatting, instagram, store, telegram

WEB = config.PUBLIC_SITE
TG = "t.me/stakevision"
MAIL = "stakevisioncl@gmail.com"
FOOT = "\n\n🔞 +18 · Juega con responsabilidad."
MAX_REPLIES_PER_RUN = 15


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", (t or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t)


# ---------------------------------------------------------------- intenciones
# (nombre, palabras clave, respuesta para mensaje directo, respuesta corta para comentario, avisarte)
INTENTS = [
    ("menor", [], (
        "Gracias por escribir. Stakevision es solo para mayores de 18 años, así que no podemos "
        "ayudarte con esto. ¡Cuídate! 🙌"), None, True),
    ("ayuda_juego", ["adiccion", "adicto", "no puedo parar", "perdi todo", "perdi mucho", "deudas", "endeudado",
                     "ludopat", "me arruine", "recuperar lo que perdi", "estoy mal"], (
        "Gracias por contarlo, de verdad. Si apostar te está afectando, lo más importante es pausar y "
        "pedir ayuda: en Chile puedes llamar gratis a Salud Responde, 600 360 7777, las 24 horas. "
        "También existe Jugadores Anónimos. Nunca intentes recuperar pérdidas apostando más. "
        "Si quieres, te escribimos personalmente. 💚"), None, True),
    ("pago", ["pague", "pagué", "transferi", "cobro", "cobraron", "reembolso", "devolucion", "boleta",
              "factura", "no me llego el link", "no me llega", "estafa", "reclamo"], (
        "Gracias por escribir. Para temas de pagos o reclamos te atendemos personalmente: ya le avisamos "
        "al equipo y te respondemos por aquí lo antes posible. También puedes escribirnos a " + MAIL + "."),
        None, True),
    ("precio", ["precio", "cuanto cuesta", "cuanto vale", "valor del vip", "vip", "premium", "suscrip",
                "plan", "mensual", "trimestral", "pagar", "costo", "cuesta"], (
        "¡Hola! 👑 El VIP de Stakevision trae 2 a 4 picks diarios con análisis completo, aviso 30 minutos "
        "antes de cada partido y seguimiento de resultados.\n\n"
        "💳 Mensual: $14.990 · Trimestral: $39.990 (ahorras $4.980).\n"
        "Estamos por abrir los cupos: mientras tanto, únete gratis al canal de Telegram (" + TG + ") "
        "y serás de los primeros en enterarte. Detalles en la web: " + WEB),
     "¡Hola! 👑 VIP: 2 a 4 picks diarios. Te dejamos todos los detalles por mensaje directo 📩", False),
    ("gratis", ["gratis", "free", "pick de hoy", "pick del dia", "pronostico de hoy", "telegram", "canal",
                "unirme", "unirse", "como entro", "link", "enlace", "donde veo"], (
        "¡Hola! 🎁 Cada día publicamos 1 pick gratis con su análisis completo en nuestro canal de Telegram: "
        + TG + "\n\nTambién lo ves en vivo en la web, con el marcador del partido: " + WEB),
     "¡Hola! 🎁 El pick gratis de cada día está en nuestro Telegram: link en la bio 👆", False),
    ("stake", ["stake", "cuanto apostar", "cuanto apuesto", "bankroll", "unidad", "unidades"], (
        "El stake es la confianza que le damos a cada pick, del 1 al 10. Cada punto equivale al 0,5% de tu "
        "bankroll (el dinero que separas solo para apostar). Ejemplo: stake 4/10 = 2% del bankroll.\n\n"
        "Nunca usamos 9 ni 10: ninguna apuesta es segura. Tenemos una guía en la publicación fijada "
        "«¿Qué es el stake?» 📌"),
     "El stake va del 1 al 10: cada punto es 0,5% de tu bankroll. Mira la publicación fijada 📌", False),
    ("como_funciona", ["como funciona", "como trabajan", "como eligen", "analisis", "metodo", "que hacen",
                       "de que se trata", "info", "informacion", "mas info"], (
        "¡Hola! 👁 Analizamos cada día los partidos de las ligas más importantes de América y Europa, "
        "calculamos la cuota justa de cada mercado y publicamos solo cuando la cuota disponible paga más de "
        "lo que debería (valor).\n\n🎁 1 pick gratis diario en Telegram: " + TG +
        "\n👑 VIP: 2 a 4 picks diarios\n📊 Historial público: " + WEB),
     "¡Hola! 👁 Te explicamos todo por mensaje directo 📩 (y en la publicación fijada «Bienvenida»)", False),
    ("resultados", ["resultado", "historial", "aciertos", "porcentaje", "efectividad", "ganan", "ganaron",
                    "verdes", "rojas", "yield", "estadistica", "es real", "confiable", "seguro",
                    "garantiz", "100%", "fijo", "fija"], (
        "Buena pregunta 👀 Todos nuestros picks quedan en el historial público de la web, verdes y rojas, "
        "sin editar ni borrar nada: " + WEB + "\n\nSomos honestos: no existen apuestas seguras ni "
        "ganancias garantizadas. Buscamos cuotas con valor y las publicamos antes del partido."),
     "Todo queda en el historial público de la web (link en la bio), verdes y rojas 📊", False),
    ("casa", ["casa de apuesta", "que casa", "donde apuesto", "donde apostar", "betano", "betplay", "bet365",
              "codere", "jugabet", "coolbet"], (
        "Nosotros solo publicamos pronósticos: no trabajamos con ninguna casa de apuestas ni recomendamos una "
        "en particular. Cada persona decide si apuesta y dónde, siempre siendo mayor de edad y de forma "
        "responsable."), None, False),
    ("deportes", ["tenis", "basquet", "basket", "nba", "baloncesto", "deportes", "que ligas", "ligas"], (
        "Por ahora nos enfocamos en fútbol: las primeras divisiones y torneos internacionales más importantes "
        "de América y Europa (Champions, Libertadores, Premier, LaLiga, Chile, Argentina, Brasil y más). "
        "Pronto sumaremos otros deportes 🎾🏀"), None, False),
    ("contacto", ["contacto", "correo", "mail", "email", "hablar con", "una persona", "humano", "soporte"], (
        "¡Claro! Ya le avisamos al equipo y te responden personalmente por aquí. También puedes escribir a "
        + MAIL + " 📩"), None, True),
    ("gracias", ["gracias", "grax", "genial", "excelente", "buenisimo", "crack", "vamos", "verde", "🔥", "💚"], (
        "¡Gracias a ti! 💚 Cualquier duda, aquí estamos. Recuerda que el pick gratis de cada día está en "
        + TG), "¡Gracias! 💚", False),
    ("saludo", ["hola", "buenas", "buenos dias", "buenas tardes", "buenas noches", "hey", "holi", "que tal"], (
        "¡Hola! 👋 Bienvenido a Stakevision. ¿En qué te ayudamos?\n\n"
        "• Pick gratis de hoy → escribe «gratis»\n• Planes VIP → escribe «VIP»\n"
        "• Cómo funciona → escribe «info»\n• Historial y resultados → escribe «resultados»"),
     None, False),
]

FALLBACK_DM = ("¡Gracias por escribir! 🙌 No estoy seguro de haber entendido, así que ya le avisé al equipo y te "
               "responden personalmente pronto.\n\nMientras tanto: el pick gratis de cada día está en " + TG +
               " y toda la info en " + WEB)


def _is_minor(t: str) -> bool:
    m = re.search(r"\btengo (\d{1,2}) ?(anos|años)?\b", t)
    if m and int(m.group(1)) < 18:
        return True
    return any(k in t for k in ("soy menor", "menor de edad", "estoy en el colegio", "voy en el liceo",
                                "mis papas no", "mi mama no me deja"))


def classify(text: str) -> str | None:
    t = _norm(text)
    if _is_minor(t):
        return "menor"
    raw = text or ""
    for name, keys, *_ in INTENTS:
        for k in keys:
            nk = _norm(k).strip()
            if not nk:                       # emojis: se buscan tal cual
                if k in raw:
                    return name
            elif len(nk) <= 4:               # palabras cortas: palabra completa
                if re.search(rf"\b{re.escape(nk)}\b", t):
                    return name
            elif nk in t:
                return name
    return None


def reply_for(intent: str | None, kind: str) -> tuple[str | None, bool]:
    """(texto, avisarte). kind = 'dm' | 'comment'. En comentarios sin respuesta corta, no se contesta en público."""
    if intent is None:
        return (FALLBACK_DM if kind == "dm" else None), True
    for name, _k, dm, comment, notify in INTENTS:
        if name == intent:
            if kind == "dm":
                return dm + ("" if name in ("menor", "ayuda_juego", "pago", "contacto") else FOOT), notify
            return comment, (notify or comment is None)
    return None, True


# ---------------------------------------------------------------- Instagram
def _me(state: dict) -> dict:
    return instagram._call("GET", "me", state, fields="user_id,username")


def _notify(state: dict, kind: str, who: str, text: str, answer: str | None, intent: str | None) -> None:
    owner = state.get("owner_chat")
    if not owner:
        return
    where = "💬 Mensaje directo" if kind == "dm" else "🗨 Comentario"
    why = {"menor": "⚠️ Posible menor de edad: no se sigue la conversación.",
           "ayuda_juego": "⚠️ Posibles problemas con el juego: se le dio la línea de ayuda.",
           "pago": "💳 Tema de pagos o reclamo: responde tú.",
           "contacto": "🙋 Pide hablar con una persona.",
           None: "❓ No lo entendí: responde tú."}.get(intent, "ℹ️ Para tu información.")
    msg = (f"📩 <b>Instagram · {where}</b> de @{formatting.escape(who)}\n"
           f"«{formatting.escape(text[:500])}»\n\n{why}"
           + (f"\n\nRespondí: «{formatting.escape(answer[:300])}»" if answer else "\n\nNo respondí en público."))
    try:
        telegram.send(owner, msg)
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo avisar por Telegram: {e}")


def _remember(box: dict, key: str, value: str) -> None:
    lst = box.setdefault(key, [])
    lst.append(value)
    del lst[:-500]


def _comments(state: dict, box: dict, me: dict, budget: list) -> None:
    since = box["since"]
    media = instagram._call("GET", "me/media", state, fields="id,timestamp,comments_count,permalink",
                            limit=12).get("data") or []
    counts = box.setdefault("counts", {})
    first = not counts
    for m in media:
        n = int(m.get("comments_count") or 0)
        seen = counts.get(m["id"], n if first else 0)
        counts[m["id"]] = n
        data = instagram._call("GET", f"{m['id']}/comments", state,
                               fields="id,text,username,timestamp,from").get("data") or []
        if n > seen and len(data) < n and state.get("owner_chat"):
            # Meta (sin revisión de la app) no deja leer comentarios de terceros: al menos te avisamos.
            telegram.send(state["owner_chat"],
                          f"🗨 <b>Comentario nuevo en Instagram</b> ({n - seen})\n"
                          f"Todavía no puedo leerlo ni responderlo solo (falta la revisión de Meta). "
                          f"Respóndelo tú aquí: {m.get('permalink') or ''}")
        for c in data:
            if budget[0] <= 0:
                return
            cid = c["id"]
            who = c.get("username") or (c.get("from") or {}).get("username") or ""
            if cid in box.get("comments", []) or who == me.get("username"):
                continue
            if (c.get("timestamp") or "") < since:   # comentarios anteriores a activar el asistente
                _remember(box, "comments", cid)
                continue
            intent = classify(c.get("text") or "")
            answer, notify = reply_for(intent, "comment")
            if intent == "menor":
                answer = None
            if answer:
                instagram._call("POST", f"{cid}/replies", state, message=answer)
                budget[0] -= 1
            if notify or not answer:
                _notify(state, "comment", who, c.get("text") or "", answer, intent)
            _remember(box, "comments", cid)


def _messages(state: dict, box: dict, me: dict, budget: list) -> None:
    since = box["since"]
    my_id = str(me.get("user_id") or me.get("id"))
    convs = instagram._call("GET", "me/conversations", state, platform="instagram",
                            fields="id,updated_time").get("data") or []
    for conv in convs[:20]:
        if (conv.get("updated_time") or "") and conv["updated_time"] < since:
            continue
        msgs = (instagram._call("GET", conv["id"], state,
                                fields="messages{id,created_time,from,message}").get("messages") or {}).get("data") or []
        # del más antiguo al más nuevo; respondemos solo el último mensaje pendiente de cada persona
        pending = [x for x in msgs if str((x.get("from") or {}).get("id")) != my_id
                   and x["id"] not in box.get("dms", []) and (x.get("created_time") or "") >= since]
        if not pending or budget[0] <= 0:
            for x in msgs:
                if (x.get("created_time") or "") < since:
                    _remember(box, "dms", x["id"])
            continue
        last = max(pending, key=lambda x: x.get("created_time") or "")
        sender = last.get("from") or {}
        text = " ".join(x.get("message") or "" for x in sorted(pending, key=lambda x: x.get("created_time") or ""))
        blocked = box.setdefault("blocked", [])
        if str(sender.get("id")) in blocked:      # menor detectado antes: no se sigue la conversación
            answer, intent, notify = None, "menor", False
        else:
            intent = classify(text)
            answer, notify = reply_for(intent, "dm")
            if intent == "menor":
                blocked.append(str(sender.get("id")))
        if answer:
            instagram._call("POST", f"{my_id}/messages", state,
                            recipient=json.dumps({"id": sender.get("id")}),
                            message=json.dumps({"text": answer}))
            budget[0] -= 1
        if notify:
            _notify(state, "dm", sender.get("username") or "?", text, answer, intent)
        for x in pending:
            _remember(box, "dms", x["id"])


def run(state: dict) -> None:
    """Revisa comentarios y mensajes nuevos y responde. Nunca detiene al resto del bot."""
    if not instagram.enabled(state):
        return
    box = state.setdefault("ig_inbox", {})
    if not box.get("since"):   # al activarlo no se responde nada antiguo
        box["since"] = store.now_utc().strftime("%Y-%m-%dT%H:%M:%S+0000")
    budget = [MAX_REPLIES_PER_RUN]
    try:
        me = _me(state)
    except instagram.InstagramError as e:
        print(f"Instagram (asistente): {e}")
        return
    for part, fn in (("comentarios", _comments), ("mensajes", _messages)):
        try:
            fn(state, box, me, budget)
            box.pop(f"err_{part}", None)
        except instagram.InstagramError as e:
            print(f"Instagram (asistente, {part}): {e}")
            if not box.get(f"err_{part}") and state.get("owner_chat"):
                box[f"err_{part}"] = str(e)[:200]
                telegram.send(state["owner_chat"],
                              f"⚠️ El asistente de Instagram no pudo leer los {part}: "
                              f"{formatting.escape(str(e)[:200])}\n(Te aviso una sola vez; sigue intentando solo.)")
