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


def _call(prompt: str, want_json: bool = True, temperature: float = 0.4) -> str:
    if not enabled():
        raise LLMError("Falta GEMINI_API_KEY")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 2048}}
    if want_json:
        body["generationConfig"]["responseMimeType"] = "application/json"
    last = ""
    for model in (list(config.LLM_MODELS) + [m for m in models() if m not in config.LLM_MODELS])[:8]:
        try:
            r = requests.post(API.format(model=model), json=body, timeout=60,
                              headers={"x-goog-api-key": config.GEMINI_API_KEY})
        except requests.RequestException as e:
            raise LLMError(f"sin conexión con Gemini ({type(e).__name__})") from None
        if r.status_code in (404, 400) and "not found" in r.text.lower() or r.status_code == 404:
            last = f"{model}: no disponible"
            continue   # ese modelo no existe en esta cuenta: probar el siguiente
        if r.status_code == 429:
            raise LLMError("se alcanzó el límite gratuito de Gemini por ahora; reintento más tarde")
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
            return "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError, ValueError):
            raise LLMError("Gemini no devolvió texto") from None
    raise LLMError(f"ningún modelo disponible ({last}); la clave ve: {', '.join(models()[:6]) or 'ninguno'}")


def ask_json(prompt: str, temperature: float = 0.4):
    txt = _call(prompt, True, temperature)
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip()).strip()
    try:
        return json.loads(txt)
    except ValueError:
        m = re.search(r"(\{.*\}|\[.*\])", txt, re.S)
        if m:
            return json.loads(m.group(1))
        raise LLMError("la respuesta no vino en el formato esperado") from None
