"""Publicación en Instagram (API de Instagram con inicio de sesión de Instagram).

Flujo de Meta: 1) crear el contenedor con la URL pública de la imagen y el texto,
2) publicarlo. La imagen se sirve desde GitHub Pages (docs/ig/), por eso se guarda
en una ejecución y se publica en una siguiente, cuando la web ya la tiene.
El token dura 60 días: se renueva solo cada semana y se guarda cifrado en el estado.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

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


def _key(caption: str) -> str:
    import re
    return re.sub(r"\s+", " ", (caption or "").strip())[:120].lower()


def already_posted(state: dict, caption: str, hours: int = 48) -> str | None:
    """¿Ya hay en la cuenta una publicación con este mismo texto (últimas `hours` horas)? Devuelve su enlace.
    Es la última barrera contra duplicados: si una vuelta anterior publicó y se cortó antes de anotarlo,
    no se vuelve a publicar."""
    if not caption:
        return None
    try:
        rows = _call("GET", "me/media", state, fields="caption,timestamp,permalink", limit=15).get("data") or []
    except InstagramError:
        return None
    k = _key(caption)
    now = store.now_utc()
    for m in rows:
        try:
            ts = datetime.strptime(m.get("timestamp", ""), "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            continue
        if now - ts <= timedelta(hours=hours) and _key(m.get("caption") or "") == k:
            return m.get("permalink") or "(ya publicada)"
    return None


def _guard(fn):
    """Envuelve una publicación: antes revisa si ya salió; si falla a medio camino, revisa si alcanzó a salir."""
    def wrapper(state, *a, caption=None, **kw):
        cap = caption if caption is not None else (a[-1] if a else "")
        done = already_posted(state, cap)
        if done:
            print("Instagram: ya estaba publicada, no se repite")
            return done
        try:
            return fn(state, *a, **({"caption": caption} if caption is not None else {}), **kw)
        except InstagramError:
            import time
            time.sleep(8)
            done = already_posted(state, cap)
            if done:
                return done
            raise
    return wrapper


def publish(state: dict, pid: str, caption: str) -> str:
    """Publica la imagen del pick. Devuelve el enlace de la publicación."""
    return _publish_guarded(state, pid, caption)


def _publish_raw(state: dict, pid: str, caption: str) -> str:
    me = _call("GET", "me", state, fields="user_id,username")
    uid = me.get("user_id") or me.get("id")
    c = _call("POST", f"{uid}/media", state, image_url=image_url(pid), caption=caption)
    # Instagram descarga y procesa la imagen: hay que esperar a que el contenedor esté listo.
    import time
    status = ""
    for _ in range(20):
        status = _call("GET", c["id"], state, fields="status_code").get("status_code") or ""
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise InstagramError(f"Instagram no pudo procesar la imagen ({status})")
        time.sleep(4)
    m = None
    for _ in range(5):
        try:
            m = _call("POST", f"{uid}/media_publish", state, creation_id=c["id"])
            break
        except InstagramError as e:
            if "not available" not in str(e).lower():
                raise
            time.sleep(5)
    if not m:
        raise InstagramError(f"la imagen no quedó lista a tiempo (estado: {status or 'desconocido'})")
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


# ---------------------------------------------------------------- carruseles e historias
def _uid(state: dict) -> str:
    me = _call("GET", "me", state, fields="user_id,username")
    return me.get("user_id") or me.get("id")


def _wait(state: dict, cid: str) -> None:
    import time
    for _ in range(30):
        st = _call("GET", cid, state, fields="status_code").get("status_code") or ""
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise InstagramError(f"Instagram no pudo procesar el contenido ({st})")
        time.sleep(4)
    raise InstagramError("el contenido no quedó listo a tiempo")


def _publish_container(state: dict, uid: str, cid: str) -> str:
    import time
    for _ in range(5):
        try:
            m = _call("POST", f"{uid}/media_publish", state, creation_id=cid)
            break
        except InstagramError as e:
            if "not available" not in str(e).lower():
                raise
            time.sleep(5)
    else:
        raise InstagramError("no se pudo publicar")
    try:
        return _call("GET", m["id"], state, fields="permalink").get("permalink") or m["id"]
    except InstagramError:
        return m["id"]


def publish_carousel(state: dict, urls: list[str], caption: str) -> str:
    uid = _uid(state)
    kids = []
    for u in urls:
        c = _call("POST", f"{uid}/media", state, image_url=u, is_carousel_item="true")
        _wait(state, c["id"])
        kids.append(c["id"])
    p = _call("POST", f"{uid}/media", state, media_type="CAROUSEL", children=",".join(kids), caption=caption)
    _wait(state, p["id"])
    return _publish_container(state, uid, p["id"])


def publish_single(state: dict, url: str, caption: str) -> str:
    uid = _uid(state)
    c = _call("POST", f"{uid}/media", state, image_url=url, caption=caption)
    _wait(state, c["id"])
    return _publish_container(state, uid, c["id"])


def publish_story(state: dict, url: str) -> str:
    uid = _uid(state)
    c = _call("POST", f"{uid}/media", state, image_url=url, media_type="STORIES")
    _wait(state, c["id"])
    return _publish_container(state, uid, c["id"])


# ---------------------------------------------------------------- Reels
def video_path(key: str) -> str:
    return os.path.join(config.ROOT, "docs", "ig", f"reel-{key}.mp4")


def video_url(key: str) -> str:
    return f"{config.PUBLIC_SITE}/ig/reel-{key}.mp4"


def save_video(key: str, mp4: bytes, cover: bytes | None = None) -> None:
    os.makedirs(os.path.dirname(video_path(key)), exist_ok=True)
    with open(video_path(key), "wb") as f:
        f.write(mp4)
    if cover:
        save_image(f"reel-{key}", cover)


def video_live(key: str) -> bool:
    try:
        return requests.head(video_url(key), timeout=20, allow_redirects=True).status_code == 200
    except requests.RequestException:
        return False


def reel_step(state: dict, job: dict, caption: str) -> str | None:
    """Publica un Reel en dos pasos (Instagram tarda en procesar el video): la primera vez crea el contenedor
    y guarda su id en job['cid']; las siguientes revisan si quedó listo y lo publican.
    Devuelve el enlace cuando se publicó; None si aún está procesando."""
    uid = _uid(state)
    done = already_posted(state, caption)
    if done:   # una vuelta anterior ya lo publicó (y se cortó antes de anotarlo)
        job.pop("cid", None)
        return done
    if not job.get("cid"):
        params = {"media_type": "REELS", "video_url": video_url(job["reel"]), "caption": caption, "share_to_feed": "true"}
        if image_live(f"reel-{job['reel']}"):
            params["cover_url"] = image_url(f"reel-{job['reel']}")
        job["cid"] = _call("POST", f"{uid}/media", state, **params)["id"]
        return None
    st = _call("GET", job["cid"], state, fields="status_code").get("status_code") or ""
    if st in ("ERROR", "EXPIRED"):
        job.pop("cid", None)
        raise InstagramError(f"Instagram no pudo procesar el video ({st})")
    if st != "FINISHED":
        return None
    link = _publish_container(state, uid, job["cid"])
    job.pop("cid", None)
    return link


_publish_guarded = _guard(_publish_raw)
publish_single = _guard(publish_single)
publish_carousel = _guard(publish_carousel)
