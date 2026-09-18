"""
Központi beállítások: a Deszkavízió napi digest generátorhoz.

A sablon mostantól EGYSÉGES: a fejléc, a panel-textúra és az üveg-címke
felépítése minden rovatnál pontosan ugyanaz, kódból generálva - kategóriánként
kizárólag az accent-szín változik. Ez van itt beállítva:
"""

import os

# ---------------------------------------------------------------------------
# Forrás oldal
# ---------------------------------------------------------------------------
SITE_BASE_URL = "https://deszkavizio.hu"
WP_API_POSTS_URL = f"{SITE_BASE_URL}/wp-json/wp/v2/posts"

CATEGORY_FILTER = None  # pl.: {"Színház", "Mozgókép", "Tánc"} - üresen = mind

# ---------------------------------------------------------------------------
# Vászon és elrendezés (pixelben, 945x2048-as vászonra vonatkoztatva)
# ---------------------------------------------------------------------------
CANVAS_SIZE = (945, 2048)

LAYOUT = {
    "header_height": 558,
    "photo_box": (0, 558, 945, 1092),
    "panel_start_y": 1092,
    "panel_bg_color": (10, 11, 11),

    "tag_pill": {
        "x0": 56,
        "y0": 1187,          # panel_start_y-hoz képest kb. +95
        "height": 70,
        "padding_x": 34,
        "font_size": 27,
    },
    "author": {
        "x0": 60, "y0": 1300,
        "font_size": 28,
    },
    "title": {
        "x0": 60, "y0": 1372,
        "right_margin": 65,
        "font_size": 46,
        "line_spacing": 1.18,
        "max_lines": 6,
    },
}

# ---------------------------------------------------------------------------
# Betűtípus - Urbanist (a szerző dőlttel, a cím félkövérrel)
#
# A tényleges .ttf fájlok licenc-korlát miatt nincsenek idemellékelve -
# ehelyett a fonts/fetch_fonts.py (vagy a GitHub Actions workflow) tölti le
# hivatalos forrásból (Google Fonts / google/fonts repó) build-időben.
# Ha ezek valamiért hiányoznának, a rendszer automatikusan a rendszerbe
# épített DejaVu Sans-ra esik vissza, hogy sose álljon le hibával.
# ---------------------------------------------------------------------------
FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")

FONT_CANDIDATES = {
    "bold": [
        os.path.join(FONT_DIR, "Urbanist-Bold.ttf"),
        os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf"),
    ],
    "italic": [
        os.path.join(FONT_DIR, "Urbanist-Italic.ttf"),
        os.path.join(FONT_DIR, "DejaVuSans-Oblique.ttf"),
    ],
    "regular": [
        os.path.join(FONT_DIR, "Urbanist-Regular.ttf"),
        os.path.join(FONT_DIR, "DejaVuSans.ttf"),
    ],
}


TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")

# ---------------------------------------------------------------------------
# A sablon mostantól a Te 7 saját (JPEG) képed - változtatás nélkül.
# Minden kategóriához a hozzá tartozó fájl tartozik; a fotó-doboz és a
# cím/szerző szöveg kerül csak rá futásidőben, minden más (fejléc, logó,
# panel-textúra, "liquid glass" rovat-címke) pontosan az marad, ami a
# képen van.
# ---------------------------------------------------------------------------
DEFAULT_TEMPLATE_KEY = "Színház"

CATEGORY_TEMPLATE_FILES = {
    "Színház": os.path.join(TEMPLATE_DIR, "template_szinhaz.jpg"),
    "Mozgókép": os.path.join(TEMPLATE_DIR, "template_mozgokep.jpg"),
    "Tánc": os.path.join(TEMPLATE_DIR, "template_tanc.jpg"),
    "Opera": os.path.join(TEMPLATE_DIR, "template_opera.jpg"),
    "Zene": os.path.join(TEMPLATE_DIR, "template_zene.jpg"),
    "Képzőművészet": os.path.join(TEMPLATE_DIR, "template_kepzomuveszet.jpg"),
    "Könyv": os.path.join(TEMPLATE_DIR, "template_konyv.jpg"),
}

# ---------------------------------------------------------------------------
# Rovatszínek - a sablonképek logójából mérve. Ez adja a cím/szerző
# szövegszínét (a sablon képi része - fejléc, panel, címke - változatlan).
# ---------------------------------------------------------------------------
DEFAULT_ACCENT = (41, 234, 215)

ACCENT_COLORS = {
    "Színház": (27, 245, 210),
    "Mozgókép": (28, 246, 212),
    "Tánc": (255, 48, 255),
    "Opera": (254, 196, 73),
    "Zene": (131, 118, 255),
    "Képzőművészet": (255, 79, 211),
    "Könyv": (182, 231, 0),
}

# ---------------------------------------------------------------------------
# E-mail (Brevo - lásd emailer.py a választás indoklásáért)
#
# DIGEST_EMAIL_TO: egy vagy több cím, vesszővel elválasztva
# (pl. "en@example.com, baratom@example.com, masik@example.com")
# ---------------------------------------------------------------------------
EMAIL_TO_LIST = [e.strip() for e in os.environ.get("DIGEST_EMAIL_TO", "").split(",") if e.strip()]
EMAIL_FROM = os.environ.get("DIGEST_EMAIL_FROM", "")
EMAIL_FROM_NAME = os.environ.get("DIGEST_EMAIL_FROM_NAME", "Deszkavízió digest")
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
EMAIL_SUBJECT_PREFIX = "Deszkavízió napi összefoglaló"

# Ha nincs cikk az adott napra, küldjön-e egy rövid "nincs cikk" e-mailt,
# vagy inkább maradjon csendben.
SEND_EMPTY_DIGEST_NOTICE = True

# ---------------------------------------------------------------------------
# Kép-hosztolás a GitHub repóból (mert a Brevo API nem támogat valódi
# beágyazott/cid képet, csak nyilvánosan elérhető URL-t - lásd emailer.py).
#
# A workflow a generált képeket a repóba commitolja, majd raw.githubusercontent.com
# linkeken hivatkozunk rájuk az e-mailben. GITHUB_REPOSITORY és GITHUB_REF_NAME
# a GitHub Actions által automatikusan beállított env változók - helyi
# teszteléshez kézzel is megadhatók.
# ---------------------------------------------------------------------------
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")  # "felhasznalo/repo-nev"
GITHUB_BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
IMAGES_REPO_DIR = "images/latest"  # a repóhoz képest relatív útvonal
