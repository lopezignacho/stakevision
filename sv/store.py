"""Estado del sistema.

- data/state.enc: estado completo CIFRADO (picks pendientes, VIP, ids de chat). El repositorio
  es público, así que nada privado se guarda en texto plano.
- docs/historial.json: lo que se muestra en la web. Picks VIP solo aparecen cuando su partido
  ya empezó, para no regalarlos antes de tiempo.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
from datetime import datetime, timezone

from cryptography.fernet import Fernet

from . import config


def _fernet() -> Fernet:
    """La clave se deriva de STATE_KEY, que puede ser cualquier contraseña larga."""
    if not config.STATE_KEY:
        raise RuntimeError("Falta STATE_KEY")
    digest = hashlib.sha256(("stakevision:" + config.STATE_KEY).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def empty_state() -> dict:
    return {"owner_chat": None, "vip_chat": None, "tg_offset": 0, "picks": {}, "seq": 0}


def load() -> dict:
    if not os.path.exists(config.STATE_FILE):
        return empty_state()
    with open(config.STATE_FILE, "rb") as f:
        raw = f.read()
    if not raw.strip():
        return empty_state()
    state = json.loads(_fernet().decrypt(raw))
    base = empty_state()
    base.update(state)
    return base


def save(state: dict) -> None:
    os.makedirs(os.path.dirname(config.STATE_FILE), exist_ok=True)
    with open(config.STATE_FILE, "wb") as f:
        f.write(_fernet().encrypt(json.dumps(state, ensure_ascii=False).encode()))
    export_public(state)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def export_public(state: dict) -> None:
    now = now_utc()
    rows = []
    for p in state["picks"].values():
        if p["status"] not in ("published", "settled"):
            continue
        started = parse_ts(p["kickoff"]) <= now
        if not (p.get("free") or started):
            continue
        rows.append({
            "id": p["id"],
            "published_at": p.get("published_at"),
            "kickoff": p["kickoff"],
            "kind": p["kind"],
            "price": p["price"],
            "stake": p["stake"],
            "prob": p.get("prob") if p.get("free") else None,
            "free": bool(p.get("free")),
            "result": p.get("result"),          # "W" | "L" | "V" | None
            "legs": [{"home": l["home"], "away": l["away"], "league": l["league"],
                      "market": l["market"], "outcome": l["outcome"], "price": l["price"],
                      "label": l.get("label")}
                     for l in p["legs"]],
            "analysis": html.unescape(p.get("analysis") or "") if p.get("free") else None,
        })
    rows.sort(key=lambda r: r["kickoff"], reverse=True)

    settled = [r for r in rows if r["result"] in ("W", "L")]
    staked = sum(r["stake"] for r in settled)
    profit = sum(r["stake"] * (r["price"] - 1) if r["result"] == "W" else -r["stake"] for r in settled)
    summary = {
        "picks": len([r for r in rows if r["result"] in ("W", "L", "V")]),
        "wins": len([r for r in settled if r["result"] == "W"]),
        "losses": len([r for r in settled if r["result"] == "L"]),
        "hit_rate": round(len([r for r in settled if r["result"] == "W"]) / len(settled), 4) if settled else None,
        "yield": round(profit / staked, 4) if staked else None,
        "avg_odds": round(sum(r["price"] for r in settled) / len(settled), 2) if settled else None,
        "units": round(profit, 2),
    }
    os.makedirs(os.path.dirname(config.PUBLIC_HISTORY), exist_ok=True)
    with open(config.PUBLIC_HISTORY, "w", encoding="utf-8") as f:
        json.dump({"updated_at": now.isoformat(), "summary": summary, "picks": rows},
                  f, ensure_ascii=False, indent=1)
