"""
Cikkek lekérése a deszkavizio.hu oldalról egy adott naptári napra
(alapértelmezetten "tegnapra", Europe/Budapest időzóna szerint).

Elsődleges út: WordPress REST API (/wp-json/wp/v2/posts?_embed=1)

A WordPress REST API nem adja vissza közvetlenül a szerző nevét,
ezért a post author ID mellett a cikk HTML-oldalából is megpróbáljuk
kinyerni a szerző nevét.

Ha a REST API nem elérhető, HTML-fallback indul.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from config import SITE_BASE_URL, WP_API_POSTS_URL, CATEGORY_FILTER

LOCAL_TZ = ZoneInfo("Europe/Budapest")
HEADERS = {
    "User-Agent": "Deszkavizio-Digest/1.0 (+daily digest bot)"
}
REQUEST_TIMEOUT = 20

log = logging.getLogger(__name__)

_AUTHOR_CACHE: dict[int, str] = {}
_URL_AUTHOR_CACHE: dict[str, str] = {}


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
            log.info(
                "REST API-n keresztül %d cikk (dátum: %s)",
                len(articles),
                target_date,
            )
            return articles

        log.warning(
            "REST API elérhető volt, de nem adott vissza cikket erre a napra: %s",
            target_date,
        )

    except Exception as exc:
        log.warning(
            "REST API lekérés sikertelen (%s), HTML-fallback indul.",
            exc,
        )

    return _fetch_via_html(target_date)


def _fetch_via_rest_api(
    target_date: date,
    max_pages: int = 3,
) -> list[Article]:
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
            break

        resp.raise_for_status()

        posts = json.loads(
            resp.content.decode("utf-8-sig")
        )

        if not posts:
            break

        stop = False

        for post in posts:
            post_local_date = _parse_wp_date(
                post["date"]
            ).date()

            if post_local_date < target_date:
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
    dt = datetime.fromisoformat(date_str)

    if dt.tzinfo is None:
        return dt.replace(tzinfo=LOCAL_TZ)

    return dt.astimezone(LOCAL_TZ)


def _article_from_wp_post(post: dict) -> Article | None:
    title = _strip_html(
        post.get("title", {}).get("rendered", "")
    ).strip()

    url = post.get("link", "")

    if not title or not url:
        return None

    embedded = post.get("_embedded", {})

    author_id = post.get("author")

    log.info(
        "DEBUG SZERZŐ: post.author=%r | embedded.author=%r",
        author_id,
        embedded.get("author"),
    )

    author = _get_author_from_post(
        post,
        embedded,
        url,
    )

    category = "Deszkavízió"

    terms = embedded.get("wp:term") or []

    for term_group in terms:
        for term in term_group:
            if (
                term.get("taxonomy") == "category"
                and term.get("name")
            ):
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
        published_local_date=_parse_wp_date(
            post["date"]
        ).date(),
    )


def _get_author_from_post(
    post: dict,
    embedded: dict,
    article_url: str,
) -> str:

    # 1. Embedded WordPress author
    authors = embedded.get("author") or []

    if authors:
        for author_data in authors:
            if not isinstance(author_data, dict):
                continue

            name = author_data.get("name")

            if name and not author_data.get("code"):
                name = str(name).strip()

                if name:
                    return name

    # 2. Korábban megtalált szerző URL alapján
    cached_url_author = _URL_AUTHOR_CACHE.get(article_url)

    if cached_url_author:
        return cached_url_author

    # 3. WordPress author ID
    author_id = post.get("author")

    try:
        author_id = int(author_id)
    except (TypeError, ValueError):
        author_id = None

    if author_id:
        cached_name = _AUTHOR_CACHE.get(author_id)

        if cached_name:
            return cached_name

    # 4. Közvetlen WordPress users endpoint
    if author_id:
        try:
            url = f"{SITE_BASE_URL}/wp-json/wp/v2/users/{author_id}"

            resp = requests.get(
                url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

            if resp.ok:
                data = json.loads(
                    resp.content.decode("utf-8-sig")
                )

                name = (
                    data.get("name")
                    or data.get("slug")
                    or ""
                ).strip()

                if name:
                    _AUTHOR_CACHE[author_id] = name
                    return name

        except Exception as exc:
            log.info(
                "WordPress users endpoint nem használható (ID %s): %s",
                author_id,
                exc,
            )

    # 5. Cikk HTML-oldalából szerző keresése
    html_author = _get_author_from_article_html(
        article_url
    )

    if html_author:
        if author_id:
            _AUTHOR_CACHE[author_id] = html_author

        _URL_AUTHOR_CACHE[article_url] = html_author

        return html_author

    return "Deszkavízió"


def _get_author_from_article_html(
    article_url: str,
) -> str | None:

    try:
        resp = requests.get(
            article_url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()

    except Exception as exc:
        log.warning(
            "Nem sikerült lekérni a cikk HTML-oldalát: %s (%s)",
            article_url,
            exc,
        )
        return None

    soup = BeautifulSoup(
        resp.text,
        "html.parser",
    )

    # 1. WordPress szabványos meta
    meta_selectors = [
        'meta[name="author"]',
        'meta[property="article:author"]',
    ]

    for selector in meta_selectors:
        tag = soup.select_one(selector)

        if tag:
            value = (
                tag.get("content")
                or tag.get_text(strip=True)
            )

            if value:
                value = value.strip()

                if _looks_like_real_author(value):
                    log.info(
                        "DEBUG HTML SZERZŐ: %s",
                        value,
                    )
                    return value

    # 2. Gyakori WordPress author elemek
    selectors = [
        ".author a",
        ".author",
        ".byline a",
        ".byline",
        ".posted-by a",
        ".posted-by",
        ".entry-author a",
        ".entry-author",
        ".post-author a",
        ".post-author",
        '[class*="author"] a',
        '[class*="author"]',
    ]

    for selector in selectors:
        tags = soup.select(selector)

        for tag in tags:
            value = tag.get_text(" ", strip=True)

            if not value:
                continue

            value = _clean_author_text(value)

            if _looks_like_real_author(value):
                log.info(
                    "DEBUG HTML SZERZŐ: %s",
                    value,
                )
                return value

    # 3. JSON-LD strukturált adat
    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
        raw = script.string or script.get_text()

        if not raw.strip():
            continue

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        author = _find_author_in_jsonld(data)

        if author:
            log.info(
                "DEBUG JSON-LD SZERZŐ: %s",
                author,
            )
            return author

    # 4. Oldal szövegében tipikus "Szerző:" formátum
    text = soup.get_text(
        " ",
        strip=True,
    )

    patterns = [
        r"Szerző:\s*([A-ZÁÉÍÓÖŐÚÜŰ][^|•\n]{2,60})",
        r"Írta:\s*([A-ZÁÉÍÓÖŐÚÜŰ][^|•\n]{2,60})",
        r"Írta\s*[-–—]\s*([A-ZÁÉÍÓÖŐÚÜŰ][^|•\n]{2,60})",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            value = _clean_author_text(
                match.group(1)
            )

            if _looks_like_real_author(value):
                log.info(
                    "DEBUG SZÖVEG SZERZŐ: %s",
                    value,
                )
                return value

    log.warning(
        "A cikk HTML-oldalán sem találtam szerzőt: %s",
        article_url,
    )

    return None


def _find_author_in_jsonld(data) -> str | None:
    if isinstance(data, list):
        for item in data:
            result = _find_author_in_jsonld(item)

            if result:
                return result

        return None

    if not isinstance(data, dict):
        return None

    author = data.get("author")

    if isinstance(author, dict):
        name = author.get("name")

        if name:
            name = str(name).strip()

            if _looks_like_real_author(name):
                return name

    elif isinstance(author, list):
        for item in author:
            if isinstance(item, dict):
                name = item.get("name")

                if name:
                    name = str(name).strip()

                    if _looks_like_real_author(name):
                        return name

            elif isinstance(item, str):
                name = item.strip()

                if _looks_like_real_author(name):
                    return name

    for value in data.values():
        if isinstance(value, (dict, list)):
            result = _find_author_in_jsonld(value)

            if result:
                return result

    return None


def _clean_author_text(value: str) -> str:
    value = re.sub(
        r"^\s*(szerző|írta|by)\s*:\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip(" :-–—|•")


def _looks_like_real_author(value: str) -> bool:
    if not value:
        return False

    normalized = value.strip().lower()

    forbidden = {
        "deszkavízió",
        "deszkavizio",
        "szerző",
        "author",
        "by",
        "admin",
        "wordpress",
    }

    if normalized in forbidden:
        return False

    if len(value) < 3 or len(value) > 80:
        return False

    return True


def _strip_html(text: str) -> str:
    return BeautifulSoup(
        text,
        "html.parser",
    ).get_text()


def _passes_category_filter(category: str) -> bool:
    if not CATEGORY_FILTER:
        return True

    return category in CATEGORY_FILTER


CATEGORY_PAGES = [
    "hirek",
    "kritikak",
    "ajanlok",
    "interjuk",
    "valogatasok",
    "szinhazoldal",
    "mozgokep",
    "tanc",
    "opera",
    "zene",
    "kepzomuveszet",
    "konyv",
]


def _fetch_via_html(target_date: date) -> list[Article]:
    seen_urls: set[str] = set()
    articles: list[Article] = []

    for slug in CATEGORY_PAGES:
        url = f"{SITE_BASE_URL}/{slug}/"

        try:
            resp = requests.get(
                url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()

        except Exception as exc:
            log.warning(
                "HTML fallback: %s nem elérhető (%s)",
                url,
                exc,
            )
            continue

        soup = BeautifulSoup(
            resp.text,
            "html.parser",
        )

        for card in soup.select("article"):
            link_tag = card.select_one(
                "h2 a, h3 a"
            )

            if not link_tag or not link_tag.get("href"):
                continue

            article_url = link_tag["href"]

            if article_url in seen_urls:
                continue

            time_tag = card.select_one("time")

            post_date = (
                _parse_html_date(time_tag)
                if time_tag
                else None
            )

            if post_date != target_date:
                continue

            img_tag = card.select_one("img")

            image_url = (
                img_tag.get("src")
                if img_tag
                else None
            )

            author_tag = card.select_one(
                ".author, .byline, .posted-by"
            )

            author = (
                author_tag.get_text(strip=True)
                if author_tag
                else "Deszkavízió"
            )

            author = _clean_author_text(author)

            if not _looks_like_real_author(author):
                author = "Deszkavízió"

            seen_urls.add(article_url)

            articles.append(
                Article(
                    title=link_tag.get_text(
                        strip=True
                    ),
                    url=article_url,
                    author=author,
                    category=slug,
                    image_url=image_url,
                    published_local_date=post_date,
                )
            )

    return articles


def _parse_html_date(time_tag) -> date | None:
    datetime_attr = (
        time_tag.get("datetime")
        if time_tag
        else None
    )

    if not datetime_attr:
        return None

    try:
        return datetime.fromisoformat(
            datetime_attr
        ).date()
    except ValueError:
        return None
