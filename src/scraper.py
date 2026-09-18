from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from config import (
    LOCAL_TZ,
    HEADERS,
    REQUEST_TIMEOUT,
)

log = logging.getLogger(__name__)

SITE_BASE_URL = "https://deszkavizio.hu"

_AUTHOR_CACHE: dict[int, str] = {}
_URL_AUTHOR_CACHE: dict[str, str] = {}


@dataclass
class Article:
    title: str
    url: str
    image_url: str | None
    category: str
    author: str
    published_at: datetime


def get_target_date() -> date:
    """Alapértelmezésben a tegnapi nap."""
    now = datetime.now(LOCAL_TZ)
    return (now - timedelta(days=1)).date()


def fetch_articles_for_date(target_date: date) -> list[Article]:
    """Cikkek lekérése REST API-ról, szükség esetén HTML fallbackkel."""
    articles = _fetch_via_rest_api(target_date)

    if articles:
        log.info("REST API-n keresztül %d cikk", len(articles))
        return articles

    log.warning(
        "REST API nem adott cikkeket, HTML-fallback indul."
    )

    articles = _fetch_via_html(target_date)
    log.info("HTML-fallbacken keresztül %d cikk", len(articles))
    return articles


def _fetch_via_rest_api(target_date: date) -> list[Article]:
    """WordPress REST API használata."""
    url = f"{SITE_BASE_URL}/wp-json/wp/v2/posts"

    params = {
        "after": f"{target_date.isoformat()}T00:00:00",
        "before": f"{(target_date + timedelta(days=1)).isoformat()}T00:00:00",
        "per_page": 100,
        "orderby": "date",
        "order": "asc",
        "_embed": "1",
    }

    try:
        resp = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()

        # A Deszkavízió REST API válaszában előfordul UTF-8 BOM.
        posts = json.loads(
            resp.content.decode("utf-8-sig")
        )

        if not isinstance(posts, list):
            log.warning("A REST API válasza nem lista.")
            return []

        articles: list[Article] = []

        for post in posts:
            try:
                article = _article_from_wp_post(post)

                if article is not None:
                    articles.append(article)

            except Exception:
                log.exception(
                    "Nem sikerült feldolgozni egy REST API-s cikket."
                )

        return articles

    except Exception as exc:
        log.warning(
            "REST API lekérés sikertelen (%s), HTML-fallback indul.",
            exc,
        )
        return []


def _parse_wp_date(value: str | None) -> datetime:
    """WordPress dátum ISO formátumból."""
    if not value:
        return datetime.now(LOCAL_TZ)

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=LOCAL_TZ)

        return dt.astimezone(LOCAL_TZ)

    except Exception:
        return datetime.now(LOCAL_TZ)


def _article_from_wp_post(post: dict) -> Article | None:
    """Egy WordPress REST API postból Article készítése."""
    embedded = post.get("_embedded", {}) or {}

    title_data = post.get("title", {}) or {}
    title_html = title_data.get("rendered", "")

    title = _strip_html(title_html).strip()

    url = (
        post.get("link")
        or ""
    ).strip()

    if not title or not url:
        return None

    published_at = _parse_wp_date(
        post.get("date")
    )

    category = _get_category_from_post(
        post,
        embedded,
    )

    if not _passes_category_filter(category):
        return None

    image_url = _get_image_from_post(
        post,
        embedded,
    )

    author = _get_author_from_post(
        post,
        embedded,
        url,
    )

    log.info(
        "DEBUG SZERZŐ: post.author=%r | embedded.author=%r | végső=%r",
        post.get("author"),
        embedded.get("author"),
        author,
    )

    return Article(
        title=title,
        url=url,
        image_url=image_url,
        category=category,
        author=author,
        published_at=published_at,
    )


def _get_author_from_post(
    post: dict,
    embedded: dict,
    article_url: str,
) -> str:
    """
    Szerző keresése.

    Prioritás:
    1. _embedded.author
    2. WordPress users endpoint include=ID
    3. a cikk HTML-oldala
    4. Deszkavízió fallback
    """

    # ---------------------------------------------------------
    # 1. _embedded.author
    # ---------------------------------------------------------

    authors = embedded.get("author") or []

    if isinstance(authors, list):
        for author_data in authors:
            if not isinstance(author_data, dict):
                continue

            # Ha az API hibaobjektumot adott vissza,
            # ezt nem tekintjük szerzőnek.
            if author_data.get("code"):
                continue

            name = author_data.get("name")

            if name:
                name = str(name).strip()

                if _looks_like_real_author(name):
                    return name

    # ---------------------------------------------------------
    # 2. WordPress users endpoint
    # ---------------------------------------------------------

    author_id = post.get("author")

    try:
        author_id = int(author_id)
    except (TypeError, ValueError):
        author_id = None

    if author_id:

        if author_id in _AUTHOR_CACHE:
            return _AUTHOR_CACHE[author_id]

        try:
            url = f"{SITE_BASE_URL}/wp-json/wp/v2/users"

            resp = requests.get(
                url,
                params={
                    "include": author_id,
                    "per_page": 100,
                },
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

            log.info(
                "DEBUG USER LIST %s: HTTP %s",
                author_id,
                resp.status_code,
            )

            if resp.ok:
                data = json.loads(
                    resp.content.decode("utf-8-sig")
                )

                log.info(
                    "DEBUG USER LIST %s: %r",
                    author_id,
                    data,
                )

                if isinstance(data, list) and data:
                    name = (
                        data[0].get("name")
                        or data[0].get("slug")
                        or ""
                    ).strip()

                    if _looks_like_real_author(name):
                        _AUTHOR_CACHE[author_id] = name
                        return name

        except Exception as exc:
            log.warning(
                "Szerzőlista lekérése sikertelen (ID %s): %s",
                author_id,
                exc,
            )

    # ---------------------------------------------------------
    # 3. Cikk HTML-oldala
    # ---------------------------------------------------------

    if article_url in _URL_AUTHOR_CACHE:
        return _URL_AUTHOR_CACHE[article_url]

    html_author = _get_author_from_article_html(
        article_url
    )

    if html_author:
        _URL_AUTHOR_CACHE[article_url] = html_author

        if author_id:
            _AUTHOR_CACHE[author_id] = html_author

        return html_author

    # ---------------------------------------------------------
    # 4. Fallback
    # ---------------------------------------------------------

    return "Deszkavízió"


def _get_author_from_article_html(
    article_url: str,
) -> str | None:
    """Szerző keresése közvetlenül a cikk HTML-oldalán."""

    try:
        resp = requests.get(
            article_url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()

        soup = BeautifulSoup(
            resp.content,
            "html.parser",
        )

        # -----------------------------------------------------
        # Meta tagek
        # -----------------------------------------------------

        meta_selectors = [
            'meta[name="author"]',
            'meta[property="article:author"]',
            'meta[name="article:author"]',
        ]

        for selector in meta_selectors:
            tag = soup.select_one(selector)

            if tag:
                value = (
                    tag.get("content")
                    or ""
                ).strip()

                value = _clean_author_text(value)

                if _looks_like_real_author(value):
                    return value

        # -----------------------------------------------------
        # Gyakori HTML classok
        # -----------------------------------------------------

        selectors = [
            ".author",
            ".byline",
            ".posted-by",
            ".entry-author",
            ".post-author",
            ".article-author",
            ".single-author",
            ".author-name",
            "[class*='author']",
        ]

        for selector in selectors:
            try:
                elements = soup.select(selector)
            except Exception:
                continue

            for element in elements:

                # Először nézzük meg, van-e kifejezetten
                # linkként megadott szerző.
                link = element.select_one(
                    'a[href*="/author/"]'
                )

                if link:
                    value = link.get_text(
                        " ",
                        strip=True,
                    )

                    value = _clean_author_text(value)

                    if _looks_like_real_author(value):
                        return value

                value = element.get_text(
                    " ",
                    strip=True,
                )

                value = _clean_author_text(value)

                if _looks_like_real_author(value):
                    return value

        # -----------------------------------------------------
        # JSON-LD
        # -----------------------------------------------------

        for script in soup.find_all(
            "script",
            type="application/ld+json",
        ):
            raw = script.string or script.get_text()

            if not raw:
                continue

            try:
                data = json.loads(raw)
            except Exception:
                continue

            author = _find_author_in_jsonld(data)

            if author:
                return author

        # -----------------------------------------------------
        # Szöveges minták
        # -----------------------------------------------------

        text = soup.get_text(
            " ",
            strip=True,
        )

        patterns = [
            r"Szerző\s*:\s*([^|•\n]+)",
            r"Írta\s*:\s*([^|•\n]+)",
            r"Írta\s*-\s*([^|•\n]+)",
            r"írta\s*:\s*([^|•\n]+)",
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
                    return value

        log.warning(
            "A cikk HTML-oldalán sem találtam szerzőt: %s",
            article_url,
        )

    except Exception as exc:
        log.warning(
            "Szerző keresése HTML-ből sikertelen (%s): %s",
            article_url,
            exc,
        )

    return None


def _find_author_in_jsonld(data) -> str | None:
    """Szerző keresése JSON-LD struktúrában."""

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
            name = _clean_author_text(
                str(name)
            )

            if _looks_like_real_author(name):
                return name

    elif isinstance(author, list):
        for item in author:
            if isinstance(item, dict):
                name = item.get("name")

                if name:
                    name = _clean_author_text(
                        str(name)
                    )

                    if _looks_like_real_author(name):
                        return name

            elif isinstance(item, str):
                name = _clean_author_text(item)

                if _looks_like_real_author(name):
                    return name

    elif isinstance(author, str):
        name = _clean_author_text(author)

        if _looks_like_real_author(name):
            return name

    # Néha nested @graph alatt van.
    graph = data.get("@graph")

    if graph:
        result = _find_author_in_jsonld(graph)

        if result:
            return result

    return None


def _clean_author_text(value: str) -> str:
    """Szerzőnév tisztítása."""

    value = re.sub(
        r"\s+",
        " ",
        value or "",
    ).strip()

    prefixes = [
        "Szerző:",
        "Szerző",
        "Írta:",
        "Írta",
        "Írta -",
        "By:",
        "By",
    ]

    for prefix in prefixes:
        if value.lower().startswith(
            prefix.lower()
        ):
            value = value[len(prefix):].strip()

    value = value.strip(
        " \t\r\n:|-•"
    )

    return value


def _looks_like_real_author(value: str | None) -> bool:
    """
    Megpróbáljuk kiszűrni az olyan értékeket,
    amelyek nem valódi szerzőnevek.
    """

    if not value:
        return False

    value = value.strip()

    if not value:
        return False

    lowered = value.lower()

    invalid = {
        "deszkavízió",
        "deszkavizio",
        "deszkavízió.hu",
        "deszkavizio.hu",
        "admin",
        "administrator",
        "wordpress",
        "szerző",
        "author",
        "by",
    }

    if lowered in invalid:
        return False

    if len(value) > 100:
        return False

    return True


def _get_category_from_post(
    post: dict,
    embedded: dict,
) -> str:
    """Kategória meghatározása."""

    categories = embedded.get("wp:term") or []

    if isinstance(categories, list):
        for taxonomy_group in categories:
            if not isinstance(taxonomy_group, list):
                continue

            for term in taxonomy_group:
                if not isinstance(term, dict):
                    continue

                taxonomy = term.get("taxonomy")

                if taxonomy != "category":
                    continue

                name = (
                    term.get("name")
                    or ""
                ).strip()

                if name:
                    return name

    return "Egyéb"


def _get_image_from_post(
    post: dict,
    embedded: dict,
) -> str | None:
    """Kiemelt kép URL keresése."""

    # Elsőként az embedded featured media.
    media = embedded.get("wp:featuredmedia") or []

    if media:
        first = media[0]

        if isinstance(first, dict):
            source_url = first.get("source_url")

            if source_url:
                return source_url

            media_details = first.get(
                "media_details"
            ) or {}

            sizes = media_details.get(
                "sizes"
            ) or {}

            for size_name in (
                "large",
                "medium_large",
                "medium",
                "full",
            ):
                size_data = sizes.get(size_name)

                if isinstance(size_data, dict):
                    source_url = size_data.get(
                        "source_url"
                    )

                    if source_url:
                        return source_url

    # Ha az embedded nem adta vissza,
    # nézzük meg a post featured_media ID-jét.
    media_id = post.get("featured_media")

    if media_id:
        try:
            url = (
                f"{SITE_BASE_URL}/wp-json/wp/v2/media/"
                f"{int(media_id)}"
            )

            resp = requests.get(
                url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

            if resp.ok:
                data = json.loads(
                    resp.content.decode("utf-8-sig")
                )

                source_url = data.get(
                    "source_url"
                )

                if source_url:
                    return source_url

        except Exception:
            pass

    return None


def _strip_html(value: str) -> str:
    """HTML tagek eltávolítása."""
    soup = BeautifulSoup(
        value or "",
        "html.parser",
    )

    return soup.get_text(
        " ",
        strip=True,
    )


def _passes_category_filter(
    category: str,
) -> bool:
    """
    Kategóriaszűrés.

    Ha a config.py-ban nincs külön kategóriafilter,
    minden kategóriát engedünk.
    """

    # A jelenlegi projektben a rovatok a WordPress
    # kategórianeveiből készülnek, ezért alapból mindent
    # továbbengedünk.
    return True


CATEGORY_PAGES = [
    ("szinhaz", "https://deszkavizio.hu/category/szinhaz/"),
    ("zene", "https://deszkavizio.hu/category/zene/"),
    ("film", "https://deszkavizio.hu/category/film/"),
    ("konyv", "https://deszkavizio.hu/category/konyv/"),
    ("kepzomuveszet", "https://deszkavizio.hu/category/kepzomuveszet/"),
    ("tanc", "https://deszkavizio.hu/category/tanc/"),
]


def _fetch_via_html(target_date: date) -> list[Article]:
    """
    HTML fallback.

    A kategóriaoldalakat végignézi, és megpróbálja
    összegyűjteni a célnapon megjelent cikkeket.
    """

    found: dict[str, Article] = {}

    for category, url in CATEGORY_PAGES:
        try:
            resp = requests.get(
                url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()

            soup = BeautifulSoup(
                resp.content,
                "html.parser",
            )

            links = soup.find_all("a", href=True)

            for link in links:
                href = link.get("href")

                if not href:
                    continue

                if not href.startswith(
                    SITE_BASE_URL
                ):
                    continue

                if href in found:
                    continue

                article_date = _parse_html_date(
                    link
                )

                if article_date != target_date:
                    continue

                title = (
                    link.get_text(
                        " ",
                        strip=True,
                    )
                    or ""
                ).strip()

                if not title:
                    continue

                author = _get_author_from_article_html(
                    href
                ) or "Deszkavízió"

                found[href] = Article(
                    title=title,
                    url=href,
                    image_url=None,
                    category=category,
                    author=author,
                    published_at=datetime.combine(
                        target_date,
                        datetime.min.time(),
                        tzinfo=LOCAL_TZ,
                    ),
                )

        except Exception as exc:
            log.warning(
                "HTML kategóriaoldal sikertelen (%s): %s",
                url,
                exc,
            )

    return list(found.values())


def _parse_html_date(
    element,
) -> date | None:
    """
    Dátum kinyerése egy HTML elem környezetéből.
    """

    # 1. datetime attribútumok
    parent = element

    for _ in range(4):
        if parent is None:
            break

        for tag in parent.find_all(
            attrs={"datetime": True}
        ):
            value = tag.get("datetime")

            if not value:
                continue

            try:
                return datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                ).date()
            except Exception:
                pass

        parent = parent.parent

    # 2. time elem
    parent = element

    for _ in range(4):
        if parent is None:
            break

        time_tag = parent.find("time")

        if time_tag:
            value = (
                time_tag.get("datetime")
                or time_tag.get_text(
                    " ",
                    strip=True,
                )
            )

            if value:
                try:
                    return datetime.fromisoformat(
                        value.replace("Z", "+00:00")
                    ).date()
                except Exception:
                    pass

        parent = parent.parent

    return None
