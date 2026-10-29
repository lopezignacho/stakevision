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


def _call(prompt: str, want_json: bool = True, temperature: float = 0.4) -> str:
    if not enabled():
        raise LLMError("Falta GEMINI_API_KEY")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 2048}}
    if want_json:
        body["generationConfig"]["responseMimeType"] = "application/json"
    last = ""
    for model in config.LLM_MODELS:
        try:
            r = requests.post(API.format(model=model), json=body, timeout=60,
                              headers={"x-goog-api-key": config.GEMINI_API_KEY})
        except requests.RequestException as e:
            raise LLMError(f"sin conexión con Gemini ({type(e).__name__})") from None
        if r.status_code == 404:   # ese modelo no existe en esta cuenta: probar el siguiente
            last = f"{model}: no disponible"
            continue
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
    raise LLMError(f"ningún modelo disponible ({last})")


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
