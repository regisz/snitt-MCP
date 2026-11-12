"""Parse verified Snitt filmnézések and értékelések HTML (read-only)."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from snitt_client.models import RatingEntry, SeriesWatchSpan, WatchingEvent

BASE_URL = "https://snitt.hu"
RATER_FULL_WIDTH_PX = 160.0
RATER_MAX_STARS = 10.0

_HU_MONTHS = {
    "január": 1,
    "február": 2,
    "március": 3,
    "április": 4,
    "május": 5,
    "június": 6,
    "július": 7,
    "augusztus": 8,
    "szeptember": 9,
    "október": 10,
    "november": 11,
    "december": 12,
}

_HU_DATETIME_RE = re.compile(
    r"(?P<year>\d{4})\.\s*(?P<month>[a-záéíóöőúüű]+)\s+(?P<day>\d{1,2})\.,\s*"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})",
    re.IGNORECASE,
)
_WIDTH_RE = re.compile(r"width:\s*([\d.]+)px", re.IGNORECASE)


def parse_hungarian_datetime(text: str) -> datetime | None:
    """Parse Snitt list timestamps like ``2025. december 31., 17:16``.

    :param str text: Display timestamp from a filmnézések table cell.
    :rtype: datetime | None
    """
    match = _HU_DATETIME_RE.search(" ".join(text.split()))
    if not match:
        return None
    month = _HU_MONTHS.get(match.group("month").lower())
    if month is None:
        return None
    return datetime(
        int(match.group("year")),
        month,
        int(match.group("day")),
        int(match.group("hour")),
        int(match.group("minute")),
    )


def stars_from_rater_width(style: str | None) -> float | None:
    """Convert ``.rater-on`` inline width to a 0–10 star value (160px = 10).

    Verified CSS: ``.rater-off,.rater-on{…width:160px}``.

    :param str | None style: Inline style attribute of ``.rater-on``.
    :rtype: float | None
    """
    if not style:
        return None
    match = _WIDTH_RE.search(style)
    if not match:
        return None
    width = float(match.group(1))
    return round(width / (RATER_FULL_WIDTH_PX / RATER_MAX_STARS), 2)


def slug_from_film_href(href: str | None) -> str | None:
    """Extract film slug from ``/filmek/<slug>`` href.

    :param str | None href: Anchor href.
    :rtype: str | None
    """
    if not href:
        return None
    path = urlparse(href).path if "://" in href else href
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "filmek":
        return parts[1]
    return None


def parse_filmnezesek_list_html(html: str, *, year: int | None = None) -> list[WatchingEvent]:
    """Parse ``/tagok/<user>/filmnezesek`` table rows into watching events.

    Observed columns: title link (``.book_selector``), optional episode text,
    ``td.nowrap`` Hungarian datetime, link to ``/filmnezesek/<id>``.

    :param str html: Raw HTML.
    :param int | None year: Optional year hint when the hidden input is missing.
    :rtype: list[WatchingEvent]
    """
    soup = BeautifulSoup(html, "html.parser")
    year_input = soup.find(id="watching_year")
    list_year = year
    if year_input and year_input.get("value"):
        try:
            list_year = int(year_input["value"])
        except ValueError:
            list_year = year
    events: list[WatchingEvent] = []
    for row in soup.find_all("tr", id=True):
        row_id = str(row.get("id") or "")
        if not row_id.startswith("watching_"):
            continue
        suffix = row_id.split("_", 1)[-1]
        if not suffix.isdigit():
            continue
        watching_id = int(suffix)
        book = row.select_one("a.book_selector")
        if book is None:
            continue
        title = book.get_text(" ", strip=True)
        href = book.get("href")
        slug = slug_from_film_href(href)
        book_id = None
        if book.get("data-id") and str(book["data-id"]).isdigit():
            book_id = int(book["data-id"])
        cells = row.find_all("td")
        episode = None
        if len(cells) >= 2:
            episode_text = cells[1].get_text(" ", strip=True)
            episode = episode_text or None
        watched_display = None
        watched_at = None
        nowrap = row.select_one("td.nowrap")
        if nowrap is not None:
            watched_display = nowrap.get_text(" ", strip=True)
            watched_at = parse_hungarian_datetime(watched_display)
        events.append(
            WatchingEvent(
                watching_id=watching_id,
                slug=slug or "",
                title=title,
                book_id=book_id,
                episode=episode,
                watched_at=watched_at.strftime("%Y-%m-%d %H:%M") if watched_at else None,
                watched_at_display=watched_display,
                detail_path=f"/filmnezesek/{watching_id}",
                year=list_year,
            )
        )
    return events


def parse_ertekelesek_list_html(html: str) -> tuple[list[RatingEntry], dict]:
    """Parse ``/tagok/<user>/ertekelesek`` rating cards.

    Personal stars come from ``.rater-on`` width (160px = 10). Optional review
    text is under ``.user_review .atom``. List cards do not expose ISO dates;
    use the detail page for ``rated_at``.

    :param str html: Raw HTML.
    :rtype: tuple[list[RatingEntry], dict]
    """
    soup = BeautifulSoup(html, "html.parser")
    counter_el = soup.select_one("h1 .counter")
    total = None
    if counter_el is not None:
        digits = "".join(ch for ch in counter_el.get_text() if ch.isdigit())
        total = int(digits) if digits else None
    next_page = None
    for anchor in soup.select(".pagination a"):
        if "Következő" in anchor.get_text() or anchor.get_text(strip=True) == "»":
            next_page = anchor.get("href")
            break
    entries: list[RatingEntry] = []
    for card in soup.find_all("div", class_="paragraph", id=True):
        card_id = str(card.get("id") or "")
        if not card_id.startswith("review_"):
            continue
        suffix = card_id.split("_", 1)[-1]
        if not suffix.isdigit():
            continue
        review_id = int(suffix)
        book = card.select_one("a.book_selector")
        if book is None:
            continue
        rater = card.select_one(".rater-on")
        stars = stars_from_rater_width(rater.get("style") if rater else None)
        review_text = _extract_review_text(card)
        entries.append(
            RatingEntry(
                review_id=review_id,
                slug=slug_from_film_href(book.get("href")) or "",
                title=book.get_text(" ", strip=True),
                book_id=int(book["data-id"]) if book.get("data-id") and str(book["data-id"]).isdigit() else None,
                stars=stars,
                max_stars=RATER_MAX_STARS,
                stars_percent=(round(stars * 10.0, 2) if stars is not None else None),
                review_text=review_text,
                detail_path=f"/ertekelesek/{review_id}",
                rated_at=None,
                community_average_percent=None,
                notes=(
                    "stars from .rater-on width (160px=10); stars_percent=stars*10 (personal scale).",
                    "Community % is not on list cards; see rating detail like_count.",
                ),
            )
        )
    meta = {"total_counter": total, "next_page_path": next_page, "page_count": len(entries)}
    return entries, meta


def parse_ertekeles_detail_html(html: str) -> RatingEntry:
    """Parse ``/ertekelesek/<id>`` into a rating entry with timestamp and review body.

    The ``.like_count`` percent is the community average (title: Értékelések átlaga),
    not Balázs's personal score.

    :param str html: Raw HTML.
    :rtype: RatingEntry
    """
    soup = BeautifulSoup(html, "html.parser")
    item = soup.select_one(".item.review")
    if item is None:
        raise ValueError("No .item.review block found on értékelés detail page.")
    review_id = None
    for cls in item.get("class") or []:
        if cls.startswith("review_") and cls.split("_", 1)[-1].isdigit():
            review_id = int(cls.split("_", 1)[-1])
            break
    if review_id is None and item.get("id", "").startswith("review_"):
        review_id = int(str(item["id"]).split("_", 1)[-1])
    if review_id is None:
        raise ValueError("Missing review id on értékelés detail page.")
    book = item.select_one("a.book_selector, a.fn.book_selector, h3.item a")
    if book is None:
        book = soup.select_one("a.book_selector")
    title = book.get_text(" ", strip=True) if book else ""
    slug = slug_from_film_href(book.get("href") if book else None) or ""
    book_id = None
    if book is not None and book.get("data-id") and str(book["data-id"]).isdigit():
        book_id = int(book["data-id"])
    rater = item.select_one(".rater-on") or soup.select_one(".rater-on")
    stars = stars_from_rater_width(rater.get("style") if rater else None)
    time_el = item.select_one("time.date")
    rated_at = time_el.get("datetime") if time_el is not None else None
    community = None
    like = item.select_one(".like_count") or soup.select_one("h3.item .like_count, h2 .like_count")
    if like is not None:
        digits = "".join(ch for ch in like.get_text() if ch.isdigit())
        community = int(digits) if digits else None
    review_text = None
    atom = item.select_one(".atom")
    if atom is not None:
        # watching-style atoms may mix date · episode; review detail uses <p>
        paragraphs = [p.get_text("\n", strip=True) for p in atom.find_all("p")]
        if paragraphs:
            review_text = "\n\n".join(paragraphs).strip() or None
        else:
            text = atom.get_text("\n", strip=True)
            review_text = text or None
    return RatingEntry(
        review_id=review_id,
        slug=slug,
        title=title,
        book_id=book_id,
        stars=stars,
        max_stars=RATER_MAX_STARS,
        stars_percent=(round(stars * 10.0, 2) if stars is not None else None),
        review_text=review_text,
        detail_path=f"/ertekelesek/{review_id}",
        rated_at=rated_at,
        community_average_percent=community,
        notes=(
            "Personal score: stars from .rater-on (160px=10); stars_percent=stars*10.",
            "community_average_percent from .like_count (site average, not personal).",
        ),
    )


def build_series_watch_span(events: list[WatchingEvent], slug: str) -> SeriesWatchSpan:
    """Aggregate first/latest watch timestamps for a slug from watching events.

    No dedicated finished field was found on filmnézések pages; ``finished_at``
    stays null unless a future verified marker appears.

    :param list[WatchingEvent] events: Watching events (any years).
    :param str slug: Film slug.
    :rtype: SeriesWatchSpan
    """
    matched = [event for event in events if event.slug == slug]
    if not matched:
        return SeriesWatchSpan(
            slug=slug,
            title=None,
            book_id=None,
            started_at=None,
            latest_watched_at=None,
            finished_at=None,
            finished_at_available=False,
            watching_count=0,
            episode_labels=[],
            notes=("No watching events for slug in provided pages.",),
        )
    dated = [event for event in matched if event.watched_at]
    dated.sort(key=lambda event: event.watched_at or "")
    started = dated[0].watched_at if dated else None
    latest = dated[-1].watched_at if dated else None
    episodes = [event.episode for event in matched if event.episode]
    return SeriesWatchSpan(
        slug=slug,
        title=matched[0].title,
        book_id=matched[0].book_id,
        started_at=started,
        latest_watched_at=latest,
        finished_at=None,
        finished_at_available=False,
        watching_count=len(matched),
        episode_labels=episodes,
        notes=(
            "started_at/latest_watched_at derived from /tagok/<user>/filmnezesek rows.",
            "No verified finished_at field on list/detail; left null.",
        ),
    )


def _extract_review_text(card: Tag) -> str | None:
    block = card.select_one(".user_review .atom")
    if block is None:
        return None
    paragraphs = [p.get_text("\n", strip=True) for p in block.find_all("p")]
    if paragraphs:
        text = "\n\n".join(paragraphs).strip()
        return text or None
    text = block.get_text("\n", strip=True).strip()
    return text or None
