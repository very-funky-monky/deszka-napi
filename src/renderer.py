"""
A cikk adatait a Te saját sablonképeidbe illeszti be (lásd
templates/template_<rovat>.jpg). A sablon képi része - fejléc, logó,
panel-textúra, "liquid glass" rovat-címke - egy az egyben változatlan
marad; futásidőben csak két dolog kerül rá:
  1. a cikk borítóképe a fotó-dobozba,
  2. a szerző (dőlt) és a cím (félkövér) szövege a panel üres részére.
"""

from __future__ import annotations

import io
import logging

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from config import (
    LAYOUT, FONT_CANDIDATES, ACCENT_COLORS, DEFAULT_ACCENT,
    CATEGORY_TEMPLATE_FILES, DEFAULT_TEMPLATE_KEY,
)
from scraper import Article

log = logging.getLogger(__name__)
REQUEST_TIMEOUT = 20

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
_TEMPLATE_CACHE: dict[str, Image.Image] = {}


def _font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    """Betűtöltő - Averia Sans Libre-t próbálja, DejaVu-ra esik vissza."""
    key = (kind, size)
    if key not in _FONT_CACHE:
        last_err = None
        for path in FONT_CANDIDATES[kind]:
            try:
                _FONT_CACHE[key] = ImageFont.truetype(path, size)
                break
            except OSError as exc:
                last_err = exc
                continue
        else:
            raise last_err
    return _FONT_CACHE[key]


def _load_template(category: str) -> Image.Image:
    path = CATEGORY_TEMPLATE_FILES.get(category)
    if path is None:
        # nincs egyedi sablon ehhez a rovathoz -> a default sablon esik be
        path = CATEGORY_TEMPLATE_FILES[DEFAULT_TEMPLATE_KEY]

    if path not in _TEMPLATE_CACHE:
        _TEMPLATE_CACHE[path] = Image.open(path).convert("RGB")
    # minden felhasználásnál másolatot adunk vissza, hogy az eredeti cache-elt
    # kép ne módosuljon a rárajzolás közben
    return _TEMPLATE_CACHE[path].copy()


# ---------------------------------------------------------------------------
# Fő belépési pont
# ---------------------------------------------------------------------------

def render_article_image(article: Article) -> Image.Image:
    accent = ACCENT_COLORS.get(article.category, DEFAULT_ACCENT)
    canvas = _load_template(article.category)

    x0, y0, x1, y1 = LAYOUT["photo_box"]
    box_w, box_h = x1 - x0, y1 - y0
    photo = _load_cover_photo(article.image_url)
    if photo is not None:
        fitted = ImageOps.fit(photo, (box_w, box_h), method=Image.LANCZOS)
        canvas.paste(fitted, (x0, y0))
    # ha nincs kép, a sablon saját (minta-) fotóhelye marad látható

    _draw_author(canvas, article.author, accent)
    _draw_title(canvas, article.title, accent)

    return canvas


# ---------------------------------------------------------------------------
# Szerző (dőlt) és cím (félkövér)
# ---------------------------------------------------------------------------

def _draw_author(canvas: Image.Image, author: str, accent) -> None:
    cfg = LAYOUT["author"]
    font = _font("italic", cfg["font_size"])
    ImageDraw.Draw(canvas).text((cfg["x0"], cfg["y0"]), author, font=font, fill=(255, 255, 255))


def _draw_title(canvas: Image.Image, title: str, accent) -> None:
    draw = ImageDraw.Draw(canvas)
    cfg = LAYOUT["title"]
    max_width = canvas.width - cfg["x0"] - cfg["right_margin"]

    font_size = cfg["font_size"]
    while font_size > 22:
        font = _font("bold", font_size)
        lines = _wrap_text(draw, title, font, max_width)
        if len(lines) <= cfg["max_lines"]:
            break
        font_size -= 2
    else:
        font = _font("bold", font_size)
        lines = _wrap_text(draw, title, font, max_width)

    line_height = font_size * cfg["line_spacing"]
    y = cfg["y0"]
    for line in lines:
        draw.text((cfg["x0"], y), line, font=font, fill=(255, 255, 255))
        y += line_height


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Borítókép letöltése
# ---------------------------------------------------------------------------

def _load_cover_photo(image_url: str | None) -> Image.Image | None:
    if not image_url:
        return None
    try:
        resp = requests.get(image_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        log.warning("Nem sikerült letölteni a borítóképet (%s): %s", image_url, exc)
        return None
