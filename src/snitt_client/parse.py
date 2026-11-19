"""Parse verified Snitt film-sheet HTML into SheetSnapshot."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from snitt_client.models import EpisodeOption, SheetSnapshot, TagRef, WatchingFormSnapshot

BASE_URL = "https://snitt.hu"
_BOOK_ID_RE = re.compile(r"bookmarkable_id=(\d+).*bookmarkable_type=Book|bookmarkable_type=Book.*bookmarkable_id=(\d+)")
_RATER_RE = re.compile(
    r"\$\(['\"]#rating['\"]\)\.rater\(\{[^}]*postHref:\s*['\"]([^'\"]+)['\"][^}]*rating:\s*(\d+(?:\.\d+)?)",
    re.I | re.S,
)
_RATER_RE_ALT = re.compile(
    r"\$\(['\"]#rating['\"]\)\.rater\(\{[^}]*rating:\s*(\d+(?:\.\d+)?)[^}]*postHref:\s*['\"]([^'\"]+)['\"]",
    re.I | re.S,
)
_FAVORITE_ID_RE = re.compile(r"^/kedvenc-filmek/(\d+)$")


def parse_sheet_html(html: str, slug: str, base_url: str = BASE_URL) -> SheetSnapshot:
    """Parse a film sheet HTML document.

    Uses only structures observed in mapping captures: CSRF meta, /cimkek/ links,
    #tags open-tag block, add-modal hrefs under /cimkezesek/ and /leirasok/, plus
    verified user-action widgets (favorite heart, rater, mark-watched, review).

    :param str html: Raw HTML from GET /filmek/<slug>.
    :param str slug: Film slug.
    :param str base_url: Site origin.
    :rtype: SheetSnapshot
    """
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""
    csrf_meta = soup.find("meta", attrs={"name": "csrf-token"})
    csrf_token = csrf_meta.get("content") if csrf_meta else None
    all_tags: list[TagRef] = []
    seen_hrefs: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if not href.startswith("/cimkek/"):
            continue
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        name = anchor.get_text(" ", strip=True)
        if name:
            all_tags.append(TagRef(name=name, href=href))
    open_tags: list[TagRef] = []
    tags_div = soup.find(id="tags")
    if tags_div:
        for anchor in tags_div.find_all("a", href=True):
            href = anchor["href"]
            if not href.startswith("/cimkek/"):
                continue
            name = anchor.get_text(" ", strip=True)
            if name:
                open_tags.append(TagRef(name=name, href=href))
    open_hrefs = {tag.href for tag in open_tags}
    header_tags = [tag for tag in all_tags if tag.href not in open_hrefs]
    description_nav_text = None
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if href.endswith("/leirasok") or href.rstrip("/").endswith("/leirasok"):
            description_nav_text = anchor.get_text(" ", strip=True)
            break
    book_id, personal_stars, set_rating_path = _parse_rating_and_book_id(soup, html)
    favorite = soup.select_one("a.favorite")
    favorite_href = favorite.get("href") if favorite else None
    favorite_classes = favorite.get("class") or [] if favorite else []
    is_favorite = "on" in favorite_classes
    favorite_id = None
    if favorite_href:
        fav_match = _FAVORITE_ID_RE.match(favorite_href)
        if fav_match:
            favorite_id = int(fav_match.group(1))
    sheet_url = urljoin(base_url, f"/filmek/{slug}")
    return SheetSnapshot(
        slug=slug,
        url=sheet_url,
        title=title,
        csrf_token=csrf_token,
        header_tags=header_tags,
        open_tags=open_tags,
        all_tags=all_tags,
        description_nav_text=description_nav_text,
        has_add_tag_link=f"/filmek/{slug}/cimkezesek/uj" in html,
        has_add_genre_link=f"/filmek/{slug}/cimkezesek/uj-mufaj" in html,
        has_add_description_link=f"/filmek/{slug}/leirasok/uj" in html,
        book_id=book_id,
        is_favorite=is_favorite,
        favorite_href=favorite_href,
        favorite_id=favorite_id,
        personal_stars=personal_stars,
        set_rating_path=set_rating_path,
        has_mark_watched_link=f"/filmek/{slug}/filmnezesek/uj" in html,
        has_add_review_link=f"/filmek/{slug}/ertekelesek/uj" in html,
    )


def _parse_rating_and_book_id(soup: BeautifulSoup, html: str) -> tuple[int | None, float | None, str | None]:
    """Extract book_id, personal stars, and set_rating path from sheet HTML.

    :param BeautifulSoup soup: Parsed sheet.
    :param str html: Raw HTML (for rater script regex).
    :rtype: tuple[int | None, float | None, str | None]
    """
    book_id = None
    personal_stars = None
    set_rating_path = None
    match = _RATER_RE.search(html) or None
    if match:
        set_rating_path = match.group(1)
        personal_stars = float(match.group(2))
    else:
        alt = _RATER_RE_ALT.search(html)
        if alt:
            personal_stars = float(alt.group(1))
            set_rating_path = alt.group(2)
    if set_rating_path:
        book_match = re.search(r"book_id=(\d+)", set_rating_path)
        if book_match:
            book_id = int(book_match.group(1))
    if book_id is None:
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].replace("&amp;", "&")
            book_match = _BOOK_ID_RE.search(href)
            if book_match:
                book_id = int(book_match.group(1) or book_match.group(2))
                break
    return book_id, personal_stars, set_rating_path


def parse_watching_form_html(html: str, slug: str) -> WatchingFormSnapshot:
    """Parse the mark-watched modal from GET ``/filmek/<slug>/filmnezesek/uj``.

    Series forms expose ``watching[episode_id]`` options; movie forms use
    ``watching[in_cinema]`` instead.

    :param str html: Modal HTML.
    :param str slug: Film slug.
    :rtype: WatchingFormSnapshot
    """
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("h1")
    title = title_tag.get_text(" ", strip=True) if title_tag else None
    form = soup.find("form", id="new_watching") or soup.find("form")
    if form is None:
        raise ValueError(f"No watching form found for slug {slug!r}")
    path = form.get("action") or f"/filmek/{slug}/filmnezesek"
    episodes: list[EpisodeOption] = []
    select = form.find("select", attrs={"name": "watching[episode_id]"})
    if select:
        for option in select.find_all("option"):
            value = (option.get("value") or "").strip()
            if not value:
                continue
            episodes.append(EpisodeOption(episode_id=int(value), label=option.get_text(" ", strip=True)))
    return WatchingFormSnapshot(
        slug=slug,
        title=title,
        path=path,
        is_series=bool(episodes) or bool(select),
        episodes=episodes,
        has_in_cinema=form.find("input", attrs={"name": "watching[in_cinema]"}) is not None,
        has_episode_review=form.find("textarea", attrs={"name": "watching[review]"}) is not None,
    )


def description_list_contains_text(html: str, needle: str) -> bool:
    """Return whether a leirasok list/page HTML contains the given text.

    :param str html: HTML from GET /filmek/<slug>/leirasok or /leirasok/<id>.
    :param str needle: Substring to look for.
    :rtype: bool
    """
    return needle in html


def extract_leirasok_ids(html: str) -> list[str]:
    """Return /leirasok/<id> paths found on a descriptions list page.

    :param str html: HTML from GET /filmek/<slug>/leirasok.
    :rtype: list[str]
    """
    return sorted(set(re.findall(r'href="(/leirasok/\d+)"', html)))
