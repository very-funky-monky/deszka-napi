"""
Letölti a valódi "Urbanist" betűtípus-fájlokat a Google Fonts hivatalos
(google/fonts) GitHub tárolójából, és a fonts/ mappába menti.

Ezt a GitHub Actions workflow futtatja le minden éles futás előtt (ott van
internet-hozzáférés). Ha bármiért nem sikerülne (pl. megváltozna az elérési
út), a renderer.py automatikusan a rendszerbe épített DejaVu Sans-ra esik
vissza - tehát ennek a hibája sosem állítja meg a digest küldését.

Helyi, kézi futtatás:
    python fonts/fetch_fonts.py

Ha inkább kézzel telepítenéd: töltsd le az "Urbanist" Regular, Bold és
Italic stílusait a https://fonts.google.com/specimen/Urbanist oldalról, és
mentsd őket pontosan ezekkel a nevekkel a fonts/ mappába:
    Urbanist-Regular.ttf
    Urbanist-Bold.ttf
    Urbanist-Italic.ttf
"""

import os
import sys
import urllib.request

FONTS_DIR = os.path.dirname(__file__)

BASE_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/urbanist/static/"

FILES = {
    "Urbanist-Regular.ttf": "Urbanist-Regular.ttf",
    "Urbanist-Bold.ttf": "Urbanist-Bold.ttf",
    "Urbanist-Italic.ttf": "Urbanist-Italic.ttf",
}


def fetch_all() -> bool:
    ok = True
    for local_name, remote_name in FILES.items():
        url = BASE_URL + remote_name
        dest = os.path.join(FONTS_DIR, local_name)
        try:
            print(f"Letöltés: {url}")
            urllib.request.urlretrieve(url, dest)
            size = os.path.getsize(dest)
            if size < 1000:  # gyanúsan kicsi -> valószínűleg hibaoldal jött vissza
                raise ValueError(f"a letöltött fájl túl kicsi ({size} bájt)")
            print(f"  OK ({size} bájt) -> {dest}")
        except Exception as exc:  # noqa: BLE001
            print(f"  HIBA: {exc}", file=sys.stderr)
            if os.path.exists(dest):
                os.remove(dest)
            ok = False
    return ok


if __name__ == "__main__":
    success = fetch_all()
    if not success:
        print(
            "\nNem sikerült minden fontfájlt letölteni - a rendszer emiatt "
            "a DejaVu Sans-ra fog visszaesni. Ez nem állítja meg a digest "
            "küldését, csak a betűtípus lesz más. Kézi pótlás: lásd a fájl "
            "elején lévő megjegyzést.",
            file=sys.stderr,
        )
        sys.exit(1)
