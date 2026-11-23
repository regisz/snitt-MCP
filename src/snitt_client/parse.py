"""Parse verified Snitt film-sheet HTML into SheetSnapshot."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from snitt_client.models import EpisodeOption, LinkEntry, SheetSnapshot, StreamingRef, TagRef, WatchingFormSnapshot

BASE_URL = "https://snitt.hu"
_LINK_TITLE_BY_HOST = {
    "anilist.co": "AniList",
    "www.anilist.co": "AniList",
    "anidb.net": "AniDB",
    "www.anidb.net": "AniDB",
    "myanimelist.net": "MyAnimeList",
    "www.myanimelist.net": "MyAnimeList",
    "crunchyroll.com": "Crunchyroll",
    "www.crunchyroll.com": "Crunchyroll",
}
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
_STREAMING_FILTER_RE = re.compile(r"/filmek/streaming\?streaming=(\d+)")
_STREAMING_SERVICE_RE = re.compile(r"/filmek/[^/]+/streaming\?service=(\d+)")
_LINK_ID_RE = re.compile(r"^link_(\d+)$")


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
    links_nav_text = None
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if description_nav_text is None and (href.endswith("/leirasok") or href.rstrip("/").endswith("/leirasok")):
            description_nav_text = anchor.get_text(" ", strip=True)
        if links_nav_text is None and (href.endswith("/linkek") or href.rstrip("/").endswith("/linkek")):
            links_nav_text = anchor.get_text(" ", strip=True)
    streaming = _parse_sheet_streaming(soup)
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
        links_nav_text=links_nav_text,
        streaming=streaming,
        has_add_tag_link=f"/filmek/{slug}/cimkezesek/uj" in html,
        has_add_genre_link=f"/filmek/{slug}/cimkezesek/uj-mufaj" in html,
        has_add_description_link=f"/filmek/{slug}/leirasok/uj" in html,
        has_add_link_link=f"/filmek/{slug}/linkek/uj" in html,
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


def _parse_sheet_streaming(soup: BeautifulSoup) -> list[StreamingRef]:
    """Parse coverbox Streaming links ``/filmek/streaming?streaming=<id>``.

    :param BeautifulSoup soup: Parsed sheet.
    :rtype: list[StreamingRef]
    """
    results: list[StreamingRef] = []
    seen: set[tuple[str, int | None]] = set()
    for strong in soup.find_all("strong"):
        if strong.get_text(strip=True) != "Streaming":
            continue
        parent = strong.parent
        if parent is None:
            continue
        for anchor in parent.find_all("a", href=True):
            href = anchor["href"]
            match = _STREAMING_FILTER_RE.search(href)
            service_id = int(match.group(1)) if match else None
            name = anchor.get_text(" ", strip=True)
            if not name:
                continue
            key = (name, service_id)
            if key in seen:
                continue
            seen.add(key)
            results.append(StreamingRef(name=name, service_id=service_id, already_present=True, can_add=False))
    return results


def parse_linkek_list_html(html: str) -> list[LinkEntry]:
    """Parse GET ``/filmek/<slug>/linkek`` list items (``div.item.link``).

    :param str html: Link list HTML.
    :rtype: list[LinkEntry]
    """
    soup = BeautifulSoup(html, "html.parser")
    entries: list[LinkEntry] = []
    for item in soup.select("div.item.link"):
        item_id = item.get("id") or ""
        id_match = _LINK_ID_RE.match(item_id)
        if not id_match:
            continue
        external = item.select_one("a.external")
        if external is None or not external.get("href"):
            continue
        user = item.select_one("a.user_selector")
        entries.append(
            LinkEntry(
                link_id=int(id_match.group(1)),
                url=external["href"],
                title=external.get_text(" ", strip=True) or None,
                username=user.get_text(" ", strip=True) if user else None,
            )
        )
    return entries


def default_link_title(url: str) -> str:
    """Return a short display title for known anime DB / streaming hosts.

    :param str url: Absolute link URL.
    :rtype: str
    """
    host = (urlparse(url).hostname or "").lower()
    if host in _LINK_TITLE_BY_HOST:
        return _LINK_TITLE_BY_HOST[host]
    return host or url


def parse_link_confirm_form(html: str) -> dict[str, str] | None:
    """Parse the Mentés confirm form returned by POST ``…/linkek/add``.

    Live Snitt flow (2026-11): ``linkek/add`` often responds with ``#new_link``
    posting to ``/filmek/<slug>/linkek`` and requiring ``link[title]``.

    :param str html: Response body from the first add POST.
    :rtype: dict[str, str] | None
    :returns: ``action``, ``link[link]``, ``link[title]`` when a confirm form is present.
    """
    soup = BeautifulSoup(html, "html.parser")
    form = soup.select_one("form#new_link") or soup.select_one("form.new_link")
    if form is None:
        return None
    action = (form.get("action") or "").strip()
    if not action:
        return None
    link_input = form.select_one("input#link_link, input[name='link[link]']")
    title_input = form.select_one("input#link_title, input[name='link[title]']")
    if link_input is None:
        return None
    link_value = (link_input.get("value") or "").strip()
    title_value = ""
    if title_input is not None:
        title_value = (title_input.get("value") or "").strip()
    if not link_value:
        return None
    if not title_value:
        title_value = default_link_title(link_value)
    return {
        "action": action,
        "link[link]": link_value,
        "link[title]": title_value,
        "commit": "Mentés",
        "utf8": "✓",
    }


def parse_streaming_edit_html(html: str) -> list[StreamingRef]:
    """Parse Streaming table on GET ``/filmek/<slug>/szerkesztes``.

    Rows with ``Hozzáadás`` → ``can_add=True`` and ``service_id`` from
    ``…/streaming?service=<id>``. Rows already assigned lack the add button
    (observed as ``div.streaming_*`` wrappers) → ``already_present=True``.

    :param str html: Szerkesztés page HTML.
    :rtype: list[StreamingRef]
    """
    soup = BeautifulSoup(html, "html.parser")
    heading = None
    for tag in soup.find_all("h3"):
        if tag.get_text(" ", strip=True) == "Streaming":
            heading = tag
            break
    scope = heading.find_next("table") if heading is not None else None
    if scope is None:
        # fixture / partial HTML: fall back to any ?service= anchors' nearest table
        sample = soup.find("a", href=_STREAMING_SERVICE_RE)
        scope = sample.find_parent("table") if sample is not None else soup
    results: list[StreamingRef] = []
    seen_names: set[str] = set()
    # include streaming_* divs that may wrap present rows between table rows
    nodes = []
    if scope is not None and getattr(scope, "name", None) == "table":
        nodes.append(scope)
        sibling = scope.next_sibling
        # also scan immediate following streaming divs wrongly nested in table markup
        for child in list(scope.children) + list(scope.find_all("div", class_=re.compile(r"^streaming"))):
            nodes.append(child)
    else:
        nodes = [soup]
    rows: list = []
    for node in nodes:
        if hasattr(node, "find_all"):
            rows.extend(node.find_all("tr"))
    # de-dupe row objects while preserving order
    unique_rows = []
    seen_row_ids: set[int] = set()
    for row in rows:
        row_id = id(row)
        if row_id in seen_row_ids:
            continue
        seen_row_ids.add(row_id)
        unique_rows.append(row)
    for row in unique_rows:
        header = row.find("th")
        if header is None:
            continue
        name = header.get_text(" ", strip=True)
        if not name or name in seen_names:
            continue
        add = None
        for anchor in row.find_all("a", href=True):
            if _STREAMING_SERVICE_RE.search(anchor["href"]):
                add = anchor
                break
        if add is not None:
            match = _STREAMING_SERVICE_RE.search(add["href"])
            service_id = int(match.group(1)) if match else None
            seen_names.add(name)
            results.append(StreamingRef(name=name, service_id=service_id, already_present=False, can_add=True))
            continue
        # present-without-add only when inside Streaming table / streaming_* wrapper
        parent_classes = " ".join(row.parent.get("class") or []) if row.parent else ""
        in_streaming_div = bool(re.search(r"\bstreaming\b", parent_classes))
        in_scope_table = scope is not None and (row.find_parent("table") is scope or row.parent is scope)
        if not (in_streaming_div or in_scope_table):
            continue
        seen_names.add(name)
        results.append(StreamingRef(name=name, service_id=None, already_present=True, can_add=False))
    return results
