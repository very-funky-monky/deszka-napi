"""
Belépési pont. Két alparancsra van bontva, mert a Brevo API-nak a
generált képek NYILVÁNOS URL-je kell (nem tud cid-es beágyazott képet
kezelni), a képek pedig a GitHub repóból vannak hosztolva - tehát előbb
commit+push kell, utána mehet csak a küldés. A GitHub Actions workflow
ezért két lépésben hívja ezt a szkriptet, közte egy git push-sal:

    python main.py render [--date YYYY-MM-DD] [--dry-run]
    (... git add/commit/push images/latest ...)
    python main.py send

Helyi teszteléshez (ha nem akarsz commitolni/küldeni):
    python main.py render --dry-run --date 2026-09-15
Ez a dry_run_output/ mappába menti a képeket, nem nyúl a repóhoz.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime

from config import SEND_EMPTY_DIGEST_NOTICE
from scraper import fetch_articles_for_date, get_target_date
from renderer import render_article_image
from image_host import RenderedArticle, save_rendered_images, load_manifest, public_url_for
from emailer import send_digest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("deszka-digest")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deszkavízió napi digest generátor és küldő")
    parser.add_argument("phase", choices=["render", "send"], help="melyik lépést futtassuk")
    parser.add_argument(
        "--date", type=str, default=None,
        help="Konkrét naptári nap YYYY-MM-DD formátumban (csak 'render'-nél; alapértelmezett: tegnap)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="'render' esetén: ne mentsen a repóba, csak a dry_run_output/ mappába lokálisan.",
    )
    return parser.parse_args()


def run_render(args: argparse.Namespace) -> int:
    target_date: date = (
        datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else get_target_date()
    )
    log.info("Célnap: %s", target_date)

    articles = fetch_articles_for_date(target_date)
    log.info("Talált cikkek száma: %d", len(articles))

    rendered: list[RenderedArticle] = []
    for article in articles:
        log.info("Renderelés: [%s] %s", article.category, article.title)
        try:
            image = render_article_image(article)
            rendered.append(RenderedArticle(article=article, image=image))
        except Exception:  # noqa: BLE001
            log.exception("Nem sikerült renderelni: %s", article.url)

    date_str = target_date.strftime("%Y. %m. %d.")

    if args.dry_run:
        out_dir = "dry_run_output"
        os.makedirs(out_dir, exist_ok=True)
        for i, item in enumerate(rendered):
            path = os.path.join(out_dir, f"{i:02d}_{item.article.category}.jpg")
            item.image.save(path, quality=90)
            log.info("Mentve: %s", path)
        return 0

    save_rendered_images(rendered, date_str)
    return 0


def run_send() -> int:
    manifest = load_manifest()
    items = manifest.get("items", [])
    target_date_str = manifest.get("target_date", "")

    if not items:
        log.info("Nincs cikk a mai manifestben.")
        if SEND_EMPTY_DIGEST_NOTICE:
            send_digest([], [], target_date_str or "-")
        return 0

    image_urls = [public_url_for(item["filename"]) for item in items]
    send_digest(items, image_urls, target_date_str)
    log.info("E-mail elküldve.")
    return 0


def main() -> int:
    args = parse_args()
    if args.phase == "render":
        return run_render(args)
    return run_send()


if __name__ == "__main__":
    sys.exit(main())
