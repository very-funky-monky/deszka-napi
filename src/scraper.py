from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo


SITE_BASE_URL = "https://deszkavizio.hu"
WP_API_URL = f"{SITE_BASE_URL}/wp-json/wp/v2"

LOCAL_TZ = ZoneInfo("Europe/Budapest")

REQUEST_TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
}


# WordPress author ID → szerző neve
AUTHOR_NAMES = {
    3: "Malik Andrea",
    9: "Flaisz János",
    13: "Steindl Gabriella",
    26: "Ráth Orsolya",
    35: "Bánfi Benedek",
    37: "Molnár Dóra",
    38: "Szabó Száva Anna",
}


CATEGORY_PAGES = [
    "szinhaz",
    "zene",
    "film",
    "kepzomuveszet",
    "irodalom",
    "interju",
    "kritika",
    "ajanlo",
    "hir",
]


# A weboldal alapértelmezett/elsődleges rovata. Sok cikk ezt a
# kategóriát a valódi rovat MELLETT is megkapja (pl. mert ez volt
# az oldal eredeti, egyetlen kategóriája, vagy ez az alapértelmezett
# WordPress-kategória) - ezért ezt csak akkor vesszük figyelembe,
# ha a cikken nincs más, konkrétabb rovat is megjelölve.
DEFAULT_FALLBACK_CATEGORY = "Színház"


log = logging.getLogger(__name__)


@dataclass
class Article:
    title: str
    url: str
    image_url: str | None
    category: str
    author: str
    published_at: datetime


def _clean_text(value: str | None) -> str:
    if not value:
        return ""

    value = BeautifulSoup(
        value,
        "html.parser",
    ).get_text(" ", strip=True)

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def _parse_datetime(
    value: str | None,
) -> datetime | None:
    if not value:
        return None

    value = value.strip()

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(LOCAL_TZ)

    except ValueError:
        pass

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(
                value,
                fmt,
            )

            return dt.replace(
                tzinfo=LOCAL_TZ
            )

        except ValueError:
            continue

    return None


def _extract_category(
    post: dict[str, Any],
) -> str:
    embedded = post.get(
        "_embedded",
        {},
    )

    terms = embedded.get(
        "wp:term",
        [],
    )

    category_names: list[str] = []

    # DIAGNOSZTIKA: minden beágyazott taxonómiát és termet kiírunk,
    # hogy lássuk, melyik taxonómiában van ténylegesen a rovat.
    all_terms_debug: list[str] = []

    for term_group in terms:
        for term in term_group:
            taxonomy = term.get(
                "taxonomy"
            )

            name = _clean_text(
                term.get("name")
            )

            slug = term.get("slug")

            all_terms_debug.append(
                f"{taxonomy}:{name}({slug})"
            )

            if taxonomy == "category":
                if name:
                    category_names.append(
                        name
                    )

    log.info(
        "TERMEK (%s) | link: %s",
        ", ".join(all_terms_debug)
        or "nincs term",
        post.get("link"),
    )

    if not category_names:
        categories = post.get(
            "categories",
            [],
        )

        if categories:
            return "Deszkavízió"

        return "Deszkavízió"

    # Ha egy cikken TÖBB rovat is szerepel, és az egyik közülük
    # az oldal alapértelmezett/elsődleges rovata (DEFAULT_FALLBACK_CATEGORY),
    # akkor azt csak abban az esetben vesszük figyelembe, ha nincs
    # más, konkrétabb rovat is a cikken. Enélkül a WordPress
    # term-sorrendje (jellemzően term_id szerint) miatt szinte
    # mindig ez az alapértelmezett kategória nyerne, függetlenül
    # attól, mi a cikk tényleges rovata.
    specific_categories = [
        name
        for name in category_names
        if name != DEFAULT_FALLBACK_CATEGORY
    ]

    if specific_categories:
        return specific_categories[0]

    return category_names[0]


def _extract_image(
    post: dict[str, Any],
) -> str | None:
    embedded = post.get(
        "_embedded",
        {}
    )

    media = embedded.get(
        "wp:featuredmedia",
        []
    )

    if media:
        image = media[0]

        source_url = image.get(
            "source_url"
        )

        if source_url:
            return source_url

        media_details = image.get(
            "media_details",
            {}
        )

        sizes = media_details.get(
            "sizes",
            {}
        )

        for size_name in (
            "large",
            "medium_large",
            "medium",
            "full",
        ):
            size = sizes.get(
                size_name
            )

            if (
                size
                and size.get("source_url")
            ):
                return size[
                    "source_url"
                ]

    featured_media = post.get(
        "featured_media"
    )

    if featured_media:
        log.debug(
            "Nincs beágyazott featured media, ID: %s",
            featured_media,
        )

    return None


def _article_from_wp_post(
    post: dict[str, Any],
) -> Article | None:
    title = _clean_text(
        post.get(
            "title",
            {}
        ).get(
            "rendered"
        )
    )

    link = post.get("link")

    if not title or not link:
        return None

    published_at = _parse_datetime(
        post.get("date_gmt")
        or post.get("date")
    )

    if published_at is None:
        return None

    author_id = post.get(
        "author"
    )

    try:
        author_id = int(
            author_id
        )
    except (
        TypeError,
        ValueError,
    ):
        author_id = None

    author = AUTHOR_NAMES.get(
        author_id,
        "Deszkavízió",
    )

    log.info(
        "SZERZŐ: ID %s → %s",
        author_id,
        author,
    )

    category = _extract_category(
        post
    )

    log.info(
        "ROVAT: %s → %s",
        title,
        category,
    )

    image_url = _extract_image(
        post
    )

    return Article(
        title=title,
        url=link,
        image_url=image_url,
        category=category,
        author=author,
        published_at=published_at,
    )


def _fetch_wp_posts_for_date(
    target_date: date,
) -> list[Article]:
    start = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        0,
        0,
        0,
        tzinfo=LOCAL_TZ,
    )

    end = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        23,
        59,
        59,
        tzinfo=LOCAL_TZ,
    )

    params = {
        "after": (
            start
            .astimezone(timezone.utc)
            .isoformat()
        ),
        "before": (
            end
            .astimezone(timezone.utc)
            .isoformat()
        ),
        "per_page": 100,
        "_embed": "1",
        "orderby": "date",
        "order": "asc",
    }

    url = f"{WP_API_URL}/posts"

    log.info(
        "REST API lekérés: %s",
        url,
    )

    try:
        response = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

    except requests.RequestException as exc:
        log.error(
            "REST API hiba: %s",
            exc,
        )

        return []

    log.info(
        "REST API HTTP státusz: %s",
        response.status_code,
    )

    if response.status_code != 200:
        log.error(
            "REST API válasz: %s",
            response.text[:1000],
        )

        return []

    try:
        # A Deszkavízió API-válasza időnként
        # UTF-8 BOM-mal érkezik.
        posts = json.loads(
            response.content.decode(
                "utf-8-sig"
            )
        )

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        log.error(
            "REST API JSON feldolgozási hiba: %s",
            exc,
        )

        return []

    if not isinstance(
        posts,
        list,
    ):
        log.error(
            "A REST API válasza nem lista."
        )

        return []

    articles: list[Article] = []

    for post in posts:
        article = _article_from_wp_post(
            post
        )

        if article is not None:
            articles.append(
                article
            )

    return articles


def _extract_author_from_html(
    soup: BeautifulSoup,
) -> str | None:
    selectors = [
        ".author",
        ".post-author",
        ".entry-author",
        ".author-name",
        ".byline",
        "[rel='author']",
        "[class*='author']",
    ]

    for selector in selectors:
        elements = soup.select(
            selector
        )

        for element in elements:
            text = _clean_text(
                element.get_text(
                    " ",
                    strip=True,
                )
            )

            if not text:
                continue

            text_lower = text.lower()

            if text_lower in {
                "szerző",
                "author",
                "deszkavízió",
            }:
                continue

            if len(text) > 100:
                continue

            return text

    return None


def _fetch_article_html(
    url: str,
) -> tuple[str | None, str | None]:
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

    except requests.RequestException as exc:
        log.debug(
            "HTML lekérés sikertelen: %s",
            exc,
        )

        return None, None

    if response.status_code != 200:
        log.debug(
            "HTML HTTP %s: %s",
            response.status_code,
            url,
        )

        return None, None

    soup = BeautifulSoup(
        response.content,
        "html.parser",
    )

    author = _extract_author_from_html(
        soup
    )

    image_url = None

    og_image = soup.find(
        "meta",
        property="og:image",
    )

    if og_image:
        image_url = og_image.get(
            "content"
        )

    if not image_url:
        image = soup.find("img")

        if image:
            image_url = (
                image.get("src")
                or image.get("data-src")
            )

    return author, image_url


def _fill_missing_article_data(
    article: Article,
) -> Article:
    if (
        article.image_url
        and article.author != "Deszkavízió"
    ):
        return article

    html_author, html_image = (
        _fetch_article_html(
            article.url
        )
    )

    author = article.author
    image_url = article.image_url

    if (
        author == "Deszkavízió"
        and html_author
    ):
        author = html_author

        log.info(
            "HTML-ből megtalált szerző: %s",
            author,
        )

    if (
        not image_url
        and html_image
    ):
        image_url = urljoin(
            SITE_BASE_URL,
            html_image,
        )

    return Article(
        title=article.title,
        url=article.url,
        image_url=image_url,
        category=article.category,
        author=author,
        published_at=article.published_at,
    )


def fetch_articles_for_date(
    target_date: date,
) -> list[Article]:
    log.info(
        "Célnap: %s",
        target_date.isoformat(),
    )

    articles = _fetch_wp_posts_for_date(
        target_date
    )

    log.info(
        "REST API-n keresztül %s cikk",
        len(articles),
    )

    completed: list[Article] = []

    for article in articles:
        article = _fill_missing_article_data(
            article
        )

        completed.append(
            article
        )

    completed.sort(
        key=lambda article:
            article.published_at
    )

    log.info(
        "Talált cikkek száma: %s",
        len(completed),
    )

    for article in completed:
        log.info(
            "%s | %s | %s | %s",
            article.published_at.strftime(
                "%Y-%m-%d %H:%M"
            ),
            article.author,
            article.category,
            article.title,
        )

    return completed


def get_target_date(
    value: str | None = None,
) -> date:
    # Ha a workflow konkrét dátumot ad meg,
    # azt használjuk.
    if value:
        return datetime.strptime(
            value,
            "%Y-%m-%d",
        ).date()

    # Automatikus futásnál mindig a tegnapi
    # magyarországi dátumot használjuk.
    now = datetime.now(
        LOCAL_TZ
    )

    return now.date() - timedelta(
        days=1
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s "
            "[%(levelname)s] "
            "%(message)s"
        ),
    )

    target = get_target_date()

    articles = fetch_articles_for_date(
        target
    )

    for article in articles:
        print(
            f"{article.author} — "
            f"{article.title}"
        )
