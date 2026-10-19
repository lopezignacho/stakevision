"""Publicación en Instagram (API de Instagram con inicio de sesión de Instagram).

Flujo de Meta: 1) crear el contenedor con la URL pública de la imagen y el texto,
2) publicarlo. La imagen se sirve desde GitHub Pages (docs/ig/), por eso se guarda
en una ejecución y se publica en una siguiente, cuando la web ya la tiene.
El token dura 60 días: se renueva solo cada semana y se guarda cifrado en el estado.
"""
from __future__ import annotations

import os
from datetime import timedelta

import requests

from . import config, store

API = "https://graph.instagram.com/v21.0"


class InstagramError(RuntimeError):
    pass


def _fp(t: str) -> str:
    import hashlib
    return hashlib.sha256(t.encode()).hexdigest()[:16] if t else ""


def token(state: dict) -> str:
    """Token renovado guardado en el estado; si cambiaste el secreto en GitHub, manda el secreto."""
    ig = state.get("ig") or {}
    if ig.get("token") and ig.get("src") == _fp(config.INSTAGRAM_TOKEN):
        return ig["token"]
    return config.INSTAGRAM_TOKEN


def enabled(state: dict) -> bool:
    return bool(token(state))


def _call(method: str, path: str, state: dict, **params) -> dict:
    params["access_token"] = token(state)
    try:
        r = (requests.post if method == "POST" else requests.get)(
            f"{API}/{path}", data=params if method == "POST" else None,
            params=params if method == "GET" else None, timeout=60)
    except requests.RequestException as e:
        raise InstagramError(f"sin conexión con Instagram ({type(e).__name__})") from None
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or "error" in data:
        msg = (data.get("error") or {}).get("message") or f"HTTP {r.status_code}"
        raise InstagramError(msg)   # nunca incluir el token
    return data


def image_path(pid: str) -> str:
    return os.path.join(config.ROOT, "docs", "ig", f"pick-{pid}.jpg")


def image_url(pid: str) -> str:
    return f"{config.PUBLIC_SITE}/ig/pick-{pid}.jpg"


def save_image(pid: str, jpeg: bytes) -> None:
    os.makedirs(os.path.dirname(image_path(pid)), exist_ok=True)
    with open(image_path(pid), "wb") as f:
        f.write(jpeg)


def image_live(pid: str) -> bool:
    try:
        return requests.head(image_url(pid), timeout=20, allow_redirects=True).status_code == 200
    except requests.RequestException:
        return False


def publish(state: dict, pid: str, caption: str) -> str:
    """Publica la imagen del pick. Devuelve el enlace de la publicación."""
    me = _call("GET", "me", state, fields="user_id,username")
    uid = me.get("user_id") or me.get("id")
    c = _call("POST", f"{uid}/media", state, image_url=image_url(pid), caption=caption)
    m = _call("POST", f"{uid}/media_publish", state, creation_id=c["id"])
    try:
        return _call("GET", m["id"], state, fields="permalink").get("permalink") or ""
    except InstagramError:
        return ""


def refresh_token(state: dict) -> None:
    """Renueva el token (vale 60 días) una vez por semana."""
    if not enabled(state):
        return
    ig = state.setdefault("ig", {})
    now = store.now_utc()
    last = ig.get("refreshed_at")
    if not last:   # token recién creado: Meta solo deja renovarlo cuando tiene más de 24 h
        ig["refreshed_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        return
    if last and now - store.parse_ts(last) < timedelta(days=7):
        return
    try:
        r = requests.get("https://graph.instagram.com/refresh_access_token",
                         params={"grant_type": "ig_refresh_token", "access_token": token(state)}, timeout=30)
        data = r.json()
        if data.get("access_token"):
            ig["token"] = data["access_token"]
            ig["src"] = _fp(config.INSTAGRAM_TOKEN)
        ig["refreshed_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo renovar el token de Instagram: {type(e).__name__}")
