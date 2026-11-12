"""Parse verified Snitt film-sheet HTML into SheetSnapshot."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from snitt_client.models import SheetSnapshot, TagRef

BASE_URL = "https://snitt.hu"


def parse_sheet_html(html: str, slug: str, base_url: str = BASE_URL) -> SheetSnapshot:
    """Parse a film sheet HTML document.

    Uses only structures observed in mapping captures: CSRF meta, /cimkek/ links,
    #tags open-tag block, and add-modal hrefs under /cimkezesek/ and /leirasok/.

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
