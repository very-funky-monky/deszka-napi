"""
Cikkek lekérése a deszkavizio.hu oldalról egy adott naptári napra
(alapértelmezetten "tegnapra", Europe/Budapest időzóna szerint).

Elsődleges út: WordPress REST API (/wp-json/wp/v2/posts?_embed=1)
   - ez adja vissza egy híváson belül a címet, szerzőt, kiemelt képet és
     a kategóriákat is.

Ha ez bármiért nem elérhető (pl. le van tiltva a REST API), HTML-fallback:
   - végigmegyünk a rovat-oldalakon (Színház, Mozgókép, stb.) és onnan
     szedjük ki a cikkeket.

A visszaadott formátum minden cikkre:
{
    "title": str,
    "url": str,
    "author": str,
    "category": str,           # elsődleges rovat neve, pl. "Színház"
    "image_url": str | None,
    "published_local_date": date,
}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from config import SITE_BASE_URL, WP_API_POSTS_URL, CATEGORY_FILTER

LOCAL_TZ = ZoneInfo("Europe/Budapest")
HEADERS = {"User-Agent": "Deszkavizio-Digest/1.0 (+daily digest bot)"}
REQUEST_TIMEOUT = 20

log = logging.getLogger(__name__)


@dataclass
class Article:
    title: str
    url: str
    author: str
    category: str
    image_url: str | None
    published_local_date: date


def get_target_date(reference: datetime | None = None) -> date:
    """Az a naptári nap (Budapest idő szerint), amelynek cikkeit összegyűjtjük.
    Alapból: a mai nap előtti nap ("tegnap")."""
    now_local = (reference or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ)
    return (now_local - timedelta(days=1)).date()


def fetch_articles_for_date(target_date: date) -> list[Article]:
    """Megpróbálja a WP REST API-t, ha nem megy, HTML-fallback-re vált."""
    try:
        articles = _fetch_via_rest_api(target_date)
        if articles:
            log.info("REST API-n keresztül %d cikk (dátum: %s)", len(articles), target_date)
            return articles
        log.warning("REST API elérhető volt, de nem adott vissza cikket erre a napra: %s", target_date)
    except Exception as exc:  # noqa: BLE001 - szándékosan széles: robusztus fallback kell
        log.warning("REST API lekérés sikertelen (%s), HTML-fallback indul.", exc)

    return _fetch_via_html(target_date)


# ---------------------------------------------------------------------------
# WordPress REST API
# ---------------------------------------------------------------------------

def _fetch_via_rest_api(target_date: date, max_pages: int = 3) -> list[Article]:
    articles: list[Article] = []
    page = 1

    while page <= max_pages:
        resp = requests.get(
            WP_API_POSTS_URL,
            params={
                "per_page": 30,
                "page": page,
                "_embed": 1,
                "orderby": "date",
                "order": "desc",
            },
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 400:
            # elfogytak az oldalak
            break
        resp.raise_for_status()
       
       posts = resp.content.decode("utf-8-sig")
       posts = __import__("json").loads(posts)
        
       if not posts:
            break

        stop = False
        for post in posts:
            post_local_date = _parse_wp_date(post["date"]).date()
            if post_local_date < target_date:
                # a lista dátum szerint csökkenő sorrendben jön, tehát ha
                # már a célnapnál korábbi cikkhez értünk, nincs több dolgunk
                stop = True
                continue
            if post_local_date != target_date:
                continue

            article = _article_from_wp_post(post)
            if article and _passes_category_filter(article.category):
                articles.append(article)

        if stop:
            break
        page += 1

    return articles


def _parse_wp_date(date_str: str) -> datetime:
    # a WP API "date" mezője a site helyi idejét adja vissza, tzinfo nélkül
    dt = datetime.fromisoformat(date_str)
    return dt.replace(tzinfo=LOCAL_TZ)


def _article_from_wp_post(post: dict) -> Article | None:
    title = _strip_html(post.get("title", {}).get("rendered", "")).strip()
    url = post.get("link", "")
    if not title or not url:
        return None

    embedded = post.get("_embedded", {})

    author = "Deszkavízió"
    authors = embedded.get("author") or []
    if authors:
        author = authors[0].get("name", author)

    category = "Deszkavízió"
    terms = embedded.get("wp:term") or []
    for term_group in terms:
        for term in term_group:
            if term.get("taxonomy") == "category" and term.get("name"):
                category = term["name"]
                break
        else:
            continue
        break

    image_url = None
    media = embedded.get("wp:featuredmedia") or []
    if media:
        media0 = media[0]
        image_url = (
            media0.get("media_details", {})
            .get("sizes", {})
            .get("large", {})
            .get("source_url")
        ) or media0.get("source_url")

    return Article(
        title=title,
        url=url,
        author=author,
        category=category,
        image_url=image_url,
        published_local_date=_parse_wp_date(post["date"]).date(),
    )


def _strip_html(text: str) -> str:
    return BeautifulSoup(text, "html.parser").get_text()


def _passes_category_filter(category: str) -> bool:
    if not CATEGORY_FILTER:
        return True
    return category in CATEGORY_FILTER


# ---------------------------------------------------------------------------
# HTML fallback (ha a REST API nem elérhető)
# ---------------------------------------------------------------------------

CATEGORY_PAGES = [
    "hirek", "kritikak", "ajanlok", "interjuk", "valogatasok",
    "szinhazoldal", "mozgokep", "tanc", "opera", "zene",
    "kepzomuveszet", "konyv",
]


def _fetch_via_html(target_date: date) -> list[Article]:
    seen_urls: set[str] = set()
    articles: list[Article] = []

    for slug in CATEGORY_PAGES:
        url = f"{SITE_BASE_URL}/{slug}/"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.warning("HTML fallback: %s nem elérhető (%s)", url, exc)
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        for card in soup.select("article"):
            link_tag = card.select_one("h2 a, h3 a")
            if not link_tag or not link_tag.get("href"):
                continue
            article_url = link_tag["href"]
            if article_url in seen_urls:
                continue

            time_tag = card.select_one("time")
            post_date = _parse_html_date(time_tag) if time_tag else None
            if post_date != target_date:
                continue

            img_tag = card.select_one("img")
            image_url = img_tag.get("src") if img_tag else None

            author_tag = card.select_one(".author, .byline, .posted-by")
            author = author_tag.get_text(strip=True) if author_tag else "Deszkavízió"

            seen_urls.add(article_url)
            articles.append(
                Article(
                    title=link_tag.get_text(strip=True),
                    url=article_url,
                    author=author,
                    category=slug,
                    image_url=image_url,
                    published_local_date=post_date,
                )
            )

    return articles


def _parse_html_date(time_tag) -> date | None:
    datetime_attr = time_tag.get("datetime") if time_tag else None
    if not datetime_attr:
        return None
    try:
        return datetime.fromisoformat(datetime_attr).date()
    except ValueError:
        return None
