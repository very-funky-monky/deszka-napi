"""
A Brevo API nem támogat valódi beágyazott (cid) képet az e-mailben, csak
nyilvánosan elérhető URL-t (lásd emailer.py). Ezért a generált képeket a
repóba mentjük (images/latest/), a workflow commitolja és pusholja őket,
utána pedig a raw.githubusercontent.com linkjükre hivatkozunk az e-mail
HTML-jében.

Fontos: a linkek mindig a repóban ÉPPEN AKTUÁLIS (aznapi) képre mutatnak,
mert a fájlneveket minden nap felülírjuk (0.jpg, 1.jpg, ...), nem
halmozzuk a repót. Ha valaki egy régebbi e-mailt nyit meg újra, ott már a
közben felülírt, aznapi kép fog megjelenni - ha aznap olvassa el a
digestet, ez nem probléma.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from PIL import Image

from config import GITHUB_REPOSITORY, GITHUB_BRANCH, IMAGES_REPO_DIR
from scraper import Article

log = logging.getLogger(__name__)

# a repó gyökeréhez képest (src/ egy szinttel lejjebb van)
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
IMAGES_DIR_ABS = os.path.join(REPO_ROOT, IMAGES_REPO_DIR)
MANIFEST_PATH = os.path.join(IMAGES_DIR_ABS, "manifest.json")


@dataclass
class RenderedArticle:
    article: Article
    image: Image.Image


def save_rendered_images(rendered: list[RenderedArticle], target_date_str: str) -> None:
    """Lementi a képeket images/latest/0.jpg, 1.jpg, ... néven, és egy
    manifest.json-t a cikk-adatokkal, hogy a küldő lépés (más futásban)
    tudja, mihez milyen URL és cím/szerző tartozik."""
    os.makedirs(IMAGES_DIR_ABS, exist_ok=True)

    # előző napi képek törlése, hogy ne maradjanak árva fájlok a mappában
    for name in os.listdir(IMAGES_DIR_ABS):
        if name.endswith(".jpg"):
            os.remove(os.path.join(IMAGES_DIR_ABS, name))

    manifest = {"target_date": target_date_str, "items": []}
    for i, item in enumerate(rendered):
        filename = f"{i}.jpg"
        path = os.path.join(IMAGES_DIR_ABS, filename)
        item.image.save(path, format="JPEG", quality=88)

        a = item.article
        manifest["items"].append({
            "filename": filename,
            "title": a.title,
            "author": a.author,
            "category": a.category,
            "url": a.url,
        })

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    log.info("Elmentve %d kép + manifest.json ide: %s", len(rendered), IMAGES_DIR_ABS)


def load_manifest() -> dict:
    if not os.path.exists(MANIFEST_PATH):
        return {"target_date": "", "items": []}
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def public_url_for(filename: str) -> str:
    if not GITHUB_REPOSITORY:
        raise RuntimeError(
            "Hiányzik a GITHUB_REPOSITORY környezeti változó - ezt a GitHub "
            "Actions automatikusan beállítja, helyi teszteléshez viszont "
            "kézzel kell megadni (pl. export GITHUB_REPOSITORY=felhasznalo/repo-nev)."
        )
    return (
        f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/{GITHUB_BRANCH}/"
        f"{IMAGES_REPO_DIR}/{filename}"
    )
