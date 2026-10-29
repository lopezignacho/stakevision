"""Redacción en español con un modelo de lenguaje (Gemini, plan gratuito de Google AI Studio).

Se usa solo para noticias públicas: nunca se envían claves ni datos de miembros.
Para cambiar de proveedor (Groq, Claude…) basta con cambiar este archivo y la clave.
"""
from __future__ import annotations

import json
import re

import requests

from . import config

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


LAST_MODEL = ""


class LLMError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(config.GEMINI_API_KEY)


_DISCOVERED: list[str] = []


def models() -> list[str]:
    """Modelos que esta clave puede usar (se le pregunta a Google): primero Flash (rápidos y del plan gratuito)."""
    if _DISCOVERED:
        return _DISCOVERED
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", params={"pageSize": 200},
                         headers={"x-goog-api-key": config.GEMINI_API_KEY}, timeout=30)
        data = r.json()
    except Exception:  # noqa: BLE001
        return list(config.LLM_MODELS)
    if r.status_code >= 400:
        msg = (data.get("error") or {}).get("message", "") if isinstance(data, dict) else ""
        raise LLMError(f"Google rechazó la clave ({r.status_code}): {msg[:160]}")
    names = []
    for m in data.get("models") or []:
        name = (m.get("name") or "").removeprefix("models/")
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        low = name.lower()
        if not low.startswith("gemini") or any(w in low for w in ("embedding", "image", "tts", "audio", "live", "vision")):
            continue
        names.append(name)

    def rank(n):
        low = n.lower()
        ver = 0.0
        import re as _re
        m_ = _re.search(r"gemini-(\d+(?:\.\d+)?)", low)
        if m_:
            ver = float(m_.group(1))
        return ("flash" in low and "lite" not in low, "flash" in low, "preview" not in low and "exp" not in low, ver)

    names.sort(key=rank, reverse=True)
    _DISCOVERED[:] = [n for n in names if "pro" not in n.lower()] + [n for n in names if "pro" in n.lower()]
    return _DISCOVERED or list(config.LLM_MODELS)


def _call(prompt: str, want_json: bool = True, temperature: float = 0.4, image: bytes | None = None) -> str:
    if not enabled():
        raise LLMError("Falta GEMINI_API_KEY")
    parts = [{"text": prompt}]
    if image:
        import base64
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image).decode()}})
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 4096}}
    if want_json:
        body["generationConfig"]["responseMimeType"] = "application/json"
    last = []
    for model in (list(config.LLM_MODELS) + [m for m in models() if m not in config.LLM_MODELS])[:6]:
        cfg = dict(body["generationConfig"])
        low = model.lower()
        if "2.5" in low:   # respuesta directa, sin «pensar» (más rápido y alcanza para redactar)
            cfg["thinkingConfig"] = {"thinkingBudget": 0}
        elif low.startswith("gemini-3"):
            cfg["thinkingConfig"] = {"thinkingLevel": "low"}
        for attempt in (1, 2):
            try:
                r = requests.post(API.format(model=model), json=dict(body, generationConfig=cfg), timeout=120,
                                  headers={"x-goog-api-key": config.GEMINI_API_KEY})
            except requests.Timeout:
                r = None
                last.append(f"{model}: tardó demasiado")
                break
            except requests.RequestException as e:
                raise LLMError(f"sin conexión con Gemini ({type(e).__name__})") from None
            if r.status_code == 400 and "thinking" in r.text.lower() and "thinkingConfig" in cfg:
                cfg.pop("thinkingConfig")   # ese modelo no acepta la opción: sin ella
                continue
            break
        if r is None:
            continue
        if r.status_code == 404 or (r.status_code == 400 and "not found" in r.text.lower()):
            last.append(f"{model}: no disponible")
            continue
        if r.status_code == 429:
            last.append(f"{model}: límite gratuito alcanzado")
            continue
        if r.status_code >= 500:
            last.append(f"{model}: error de Google {r.status_code}")
            continue
        if r.status_code >= 400:
            try:
                msg = r.json().get("error", {}).get("message", "")
            except ValueError:
                msg = ""
            raise LLMError(f"Gemini respondió {r.status_code}: {msg[:160]}")   # sin la clave
        global LAST_MODEL
        LAST_MODEL = model
        try:
            parts = r.json()["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        except (KeyError, IndexError, ValueError):
            last.append(f"{model}: respuesta vacía")
            continue
    raise LLMError("ningún modelo respondió (" + "; ".join(last[:4]) + f"); la clave ve: {', '.join(models()[:6]) or 'ninguno'}")


def ask_json(prompt: str, temperature: float = 0.4, image: bytes | None = None):
    txt = _call(prompt, True, temperature, image)
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip()).strip()
    try:
        return json.loads(txt)
    except ValueError:
        m = re.search(r"(\{.*\}|\[.*\])", txt, re.S)
        if m:
            return json.loads(m.group(1))
        raise LLMError("la respuesta no vino en el formato esperado") from None


def _small_jpeg(photo: bytes, side: int = 1024) -> bytes:
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(photo)).convert("RGB")
    im.thumbnail((side, side))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85)
    return out.getvalue()


def check_jersey(photo: bytes, player: str, team: str, sport: str) -> dict:
    """Mira la foto (pública, de Commons) y dice qué camiseta lleva el protagonista.
    {"ok": bool, "jersey": "...", "why": "..."}; ok solo si la camiseta es del equipo pedido."""
    deporte = "básquetbol (NBA)" if sport == "basketball" else "fútbol"
    prompt = (f"Mira esta foto de {deporte}. Necesito saber si el protagonista de la foto (la persona más grande y "
              f"en primer plano) lleva la camiseta del equipo «{team}» (debería ser {player}).\n"
              "Reglas: una camiseta de selección nacional (USA, Argentina, Chile, etc.), de otro club, de "
              "entrenamiento sin el nombre o los colores claros del equipo, ropa de calle, traje o polerón NO cuentan. "
              "Si no se ve la camiseta con claridad, o hay otra persona más protagonista, la respuesta es no.\n"
              'Responde en JSON: {"camiseta": "equipo o selección que se ve en la camiseta, o desconocido", '
              '"es_del_equipo": true/false, "protagonista_claro": true/false, "deporte_correcto": true/false, '
              '"motivo": "frase corta"}')
    d = ask_json(prompt, 0.0, _small_jpeg(photo))
    ok = bool(d.get("es_del_equipo")) and bool(d.get("protagonista_claro", True)) and bool(d.get("deporte_correcto", True))
    return {"ok": ok, "jersey": str(d.get("camiseta") or ""), "why": str(d.get("motivo") or "")}


def subject_box(photo: bytes) -> tuple[float, float, float] | None:
    """Dónde está la cara del protagonista de la foto (x, y del centro y ancho, de 0 a 1), o None."""
    prompt = ("En esta foto deportiva, ubica la CARA del protagonista: el jugador o la persona más grande, nítida y "
              "en primer plano (no el público ni jugadores del fondo). Si no se ve ninguna cara, ubica al sujeto "
              "principal. Responde en JSON: {\"box_2d\": [ymin, xmin, ymax, xmax]} con valores de 0 a 1000.")
    d = ask_json(prompt, 0.0, _small_jpeg(photo))
    b = d.get("box_2d") if isinstance(d, dict) else None
    if isinstance(d, list) and d and isinstance(d[0], dict):
        b = d[0].get("box_2d")
    if not (isinstance(b, list) and len(b) == 4):
        return None
    y0, x0, y1, x1 = [max(0.0, min(1000.0, float(v))) / 1000 for v in b]
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0
