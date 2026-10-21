"""Descarga una foto de Wikimedia Commons con su autor y licencia.

Solo acepta licencias libres que permiten uso comercial (CC0, CC BY, CC BY-SA, dominio público).
Guarda media/commons/<nombre>.jpg y <nombre>.json con el crédito a publicar.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

UA = "StakevisionBot/1.0 (https://lopezignacho.github.io/stakevision)"
OK = re.compile(r"^(CC0|CC BY(-SA)? [\d.]+|Public domain)", re.I)


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main(name: str, width: int = 1400) -> None:
    title = "File:" + name.removeprefix("File:")
    q = urllib.parse.urlencode({
        "action": "query", "titles": title, "prop": "imageinfo", "format": "json",
        "iiprop": "url|extmetadata", "iiurlwidth": width,
    })
    page = next(iter(json.loads(get("https://commons.wikimedia.org/w/api.php?" + q))["query"]["pages"].values()))
    info = page["imageinfo"][0]
    meta = info["extmetadata"]
    lic = meta.get("LicenseShortName", {}).get("value", "")
    if not OK.match(lic):
        sys.exit(f"Licencia no apta para uso comercial: {lic!r}")
    artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().rsplit(".", 1)[0]).strip("-")
    os.makedirs("media/commons", exist_ok=True)
    with open(f"media/commons/{slug}.jpg", "wb") as f:
        f.write(get(info["thumburl"]))
    credit = {"file": title, "author": artist, "license": lic, "page": info["descriptionurl"],
              "credit": f"Foto: {artist} / Wikimedia Commons ({lic})"}
    with open(f"media/commons/{slug}.json", "w") as f:
        json.dump(credit, f, ensure_ascii=False, indent=1)
    print(credit["credit"])


if __name__ == "__main__":
    main(sys.argv[1])
