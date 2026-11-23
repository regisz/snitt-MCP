"""Snitt HTTP client: fetch, resolve, dry-run plans, gated save, verify."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from snitt_client.history_parse import (
    build_series_watch_span,
    parse_ertekeles_detail_html,
    parse_ertekelesek_list_html,
    parse_filmnezesek_list_html,
)
from snitt_client.models import (
    DeletePlan,
    DescriptionPlan,
    FavoritePlan,
    LinkEntry,
    LinkPlan,
    RatingEntry,
    RatingPlan,
    ReviewPlan,
    SaveResult,
    SeriesWatchSpan,
    SheetSnapshot,
    StreamingPlan,
    StreamingRef,
    TaggingPlan,
    TagRef,
    WatchingEvent,
    WatchingFormSnapshot,
    WatchingPlan,
)
from snitt_client.parse import (
    default_link_title,
    description_list_contains_text,
    extract_leirasok_ids,
    parse_link_confirm_form,
    parse_linkek_list_html,
    parse_sheet_html,
    parse_streaming_edit_html,
    parse_watching_form_html,
)
from snitt_client.session import cookie_header_to_httpx_cookies, load_cookie_header

BASE_URL = "https://snitt.hu"
OPEN_TAGS_API = "/api/open_tags_with_names.json"
GENRES_API = "/api/genres_with_names.json"
JS_ACCEPT = "text/javascript, application/javascript, application/ecmascript, application/x-ecmascript, */*; q=0.01"
JSON_ACCEPT = "application/json, text/javascript, */*; q=0.01"
DEFAULT_USERNAME = "balage"


class SnittClientError(RuntimeError):
    """Raised for client-side validation or unexpected HTTP failures."""


class SnittClient:
    """HTTP client for verified Snitt sheet read/edit flows.

    Live writes require ``allow_save=True``. Prefer dry-run plans in tests and
    automation unless Balázs explicitly allows a save.
    """

    def __init__(
        self,
        cookie_header: str | None = None,
        config_path: Path | None = None,
        base_url: str = BASE_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Create a client with session cookies from ENV/config or an explicit header.

        :param str | None cookie_header: Optional raw Cookie header (tests/fixtures).
        :param Path | None config_path: Optional cookie file path override.
        :param str base_url: Site origin.
        :param httpx.BaseTransport | None transport: Optional httpx transport (tests).
        """
        header = cookie_header if cookie_header is not None else load_cookie_header(config_path)
        cookies = cookie_header_to_httpx_cookies(header)
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            cookies=cookies,
            headers={"User-Agent": "snitt-client/0.1"},
            follow_redirects=True,
            timeout=40.0,
            transport=transport,
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> SnittClient:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def fetch_sheet(self, slug: str) -> SheetSnapshot:
        """GET /filmek/<slug> and parse a sheet snapshot.

        :param str slug: Film slug.
        :rtype: SheetSnapshot
        """
        response = self._client.get(f"/filmek/{slug}")
        response.raise_for_status()
        return parse_sheet_html(response.text, slug=slug, base_url=self.base_url)

    def resolve_open_tag(self, query: str, exact_name: str | None = None, csrf_token: str | None = None) -> TagRef:
        """Resolve an open tag via GET /api/open_tags_with_names.json.

        :param str query: Autocomplete query string.
        :param str | None exact_name: Optional exact display name to select.
        :param str | None csrf_token: Optional CSRF token for XHR header.
        :rtype: TagRef
        """
        return self._resolve_catalog(OPEN_TAGS_API, query, exact_name, csrf_token)

    def resolve_genre(self, query: str, exact_name: str | None = None, csrf_token: str | None = None) -> TagRef:
        """Resolve a műfaj via GET /api/genres_with_names.json.

        :param str query: Autocomplete query string.
        :param str | None exact_name: Optional exact display name to select.
        :param str | None csrf_token: Optional CSRF token for XHR header.
        :rtype: TagRef
        """
        return self._resolve_catalog(GENRES_API, query, exact_name, csrf_token)

    def list_open_tags(self, query: str, csrf_token: str | None = None) -> list[TagRef]:
        """List open-tag autocomplete matches via GET /api/open_tags_with_names.json?q=.

        Snitt requires a non-empty ``q`` (empty/whitespace returns 403). Broad prefixes
        may return a capped result set (observed ~20); no pagination params are verified.

        :param str query: Autocomplete query (``q`` API param; non-empty after strip).
        :param str | None csrf_token: Optional CSRF token for XHR header.
        :rtype: list[TagRef]
        """
        return self._list_catalog(OPEN_TAGS_API, query, csrf_token)

    def list_genres(self, query: str, csrf_token: str | None = None) -> list[TagRef]:
        """List műfaj autocomplete matches via GET /api/genres_with_names.json?q=.

        Snitt requires a non-empty ``q`` (empty/whitespace returns 403). No pagination
        params are verified on this endpoint.

        :param str query: Autocomplete query (``q`` API param; non-empty after strip).
        :param str | None csrf_token: Optional CSRF token for XHR header.
        :rtype: list[TagRef]
        """
        return self._list_catalog(GENRES_API, query, csrf_token)

    def plan_add_tag(self, slug: str, name: str, sheet: SheetSnapshot | None = None) -> TaggingPlan:
        """Build a dry-run plan to add an open tag (cimke).

        :param str slug: Film slug.
        :param str name: Exact tag display name.
        :param SheetSnapshot | None sheet: Optional pre-fetched sheet.
        :rtype: TaggingPlan
        """
        snapshot = sheet or self.fetch_sheet(slug)
        resolved = self.resolve_open_tag(name, exact_name=name, csrf_token=snapshot.csrf_token)
        return self._tagging_plan(kind="open_tag", slug=slug, name=name, tag_id=resolved.tag_id or 0, sheet=snapshot)

    def plan_add_genre(self, slug: str, name: str, sheet: SheetSnapshot | None = None) -> TaggingPlan:
        """Build a dry-run plan to add a műfaj.

        :param str slug: Film slug.
        :param str name: Exact genre display name.
        :param SheetSnapshot | None sheet: Optional pre-fetched sheet.
        :rtype: TaggingPlan
        """
        snapshot = sheet or self.fetch_sheet(slug)
        resolved = self.resolve_genre(name, exact_name=name, csrf_token=snapshot.csrf_token)
        return self._tagging_plan(kind="genre", slug=slug, name=name, tag_id=resolved.tag_id or 0, sheet=snapshot)

    def list_watchings(
        self,
        *,
        username: str = DEFAULT_USERNAME,
        year: int | None = None,
        watching_type: str | None = None,
        tag: str | None = None,
        place: str | None = None,
    ) -> list[WatchingEvent]:
        """GET ``/tagok/<user>/filmnezesek`` and parse watching rows (read-only).

        Verified query params from the page filters: ``year``, ``type``
        (movies|shortfilms|series|miniseries|talkshows), ``tag``, ``place``
        (cinema|other).

        :param str username: Profile slug (default balage).
        :param int | None year: Optional year filter.
        :param str | None watching_type: Optional type filter value.
        :param str | None tag: Optional tag name filter.
        :param str | None place: Optional place filter.
        :rtype: list[WatchingEvent]
        """
        params: dict[str, str] = {}
        if year is not None:
            params["year"] = str(year)
        if watching_type:
            params["type"] = watching_type
        if tag:
            params["tag"] = tag
        if place:
            params["place"] = place
        response = self._client.get(f"/tagok/{username}/filmnezesek", params=params or None)
        response.raise_for_status()
        return parse_filmnezesek_list_html(response.text, year=year)

    def series_watch_span(
        self,
        slug: str,
        *,
        username: str = DEFAULT_USERNAME,
        years: list[int] | None = None,
        watching_type: str = "series",
    ) -> SeriesWatchSpan:
        """Aggregate started/latest watch times for a series slug from filmnézések.

        Fetches one or more year pages (default: current list year pages given in
        ``years``). ``finished_at`` is not exposed by Snitt on these pages.

        :param str slug: Film slug.
        :param str username: Profile slug.
        :param list[int] | None years: Years to scan; required for a useful span.
        :param str watching_type: Type filter (default series).
        :rtype: SeriesWatchSpan
        """
        if not years:
            raise SnittClientError("series_watch_span requires years=[YYYY, …] to scan filmnézések pages.")
        events: list[WatchingEvent] = []
        for year in years:
            events.extend(
                self.list_watchings(username=username, year=year, watching_type=watching_type)
            )
        return build_series_watch_span(events, slug)

    def list_ratings(
        self,
        *,
        username: str = DEFAULT_USERNAME,
        page: int = 1,
        order: str | None = None,
        rating: int | None = None,
        is_reviewed: bool | None = None,
    ) -> tuple[list[RatingEntry], dict[str, Any]]:
        """GET ``/tagok/<user>/ertekelesek`` and parse personal star ratings.

        Filters verified on the form: ``order``, ``rating`` (1–10), ``is_reviewed``
        (1=text reviews only, 0=stars-only), ``page``.

        :param str username: Profile slug.
        :param int page: Pagination page (1-based).
        :param str | None order: Optional order value from the select.
        :param int | None rating: Optional exact star filter.
        :param bool | None is_reviewed: Optional text-review filter.
        :rtype: tuple[list[RatingEntry], dict[str, Any]]
        """
        params: dict[str, str] = {}
        if page and page != 1:
            params["page"] = str(page)
        if order:
            params["order"] = order
        if rating is not None:
            params["rating"] = str(rating)
        if is_reviewed is True:
            params["is_reviewed"] = "1"
        elif is_reviewed is False:
            params["is_reviewed"] = "0"
        response = self._client.get(f"/tagok/{username}/ertekelesek", params=params or None)
        response.raise_for_status()
        return parse_ertekelesek_list_html(response.text)

    def fetch_rating(self, review_id: int) -> RatingEntry:
        """GET ``/ertekelesek/<id>`` for stars, optional review text, and rated_at.

        :param int review_id: Review id from the értékelések list.
        :rtype: RatingEntry
        """
        response = self._client.get(f"/ertekelesek/{review_id}")
        response.raise_for_status()
        try:
            return parse_ertekeles_detail_html(response.text)
        except ValueError as exc:
            raise SnittClientError(str(exc)) from exc

    def plan_add_description(self, slug: str, text: str) -> DescriptionPlan:
        """Build a dry-run plan to POST a new description.

        :param str slug: Film slug.
        :param str text: Hungarian description body.
        :rtype: DescriptionPlan
        """
        if not text.strip():
            raise SnittClientError("Description text is empty.")
        return DescriptionPlan(
            kind="description",
            slug=slug,
            method="POST",
            path=f"/filmek/{slug}/leirasok",
            fields={
                "utf8": "✓",
                "description[description]": text,
                "commit": "Mentés",
            },
            text_length=len(text),
            notes=(
                "Verified path: POST /filmek/<slug>/leirasok creates a new Description.",
                "Primary sheet synopsis may not switch until editorial approval.",
                "Verify via /filmek/<slug>/leirasok list and /leirasok/<id>.",
            ),
        )

    def list_links(self, slug: str) -> list[LinkEntry]:
        """GET ``/filmek/<slug>/linkek`` and parse external link entries.

        :param str slug: Film slug.
        :rtype: list[LinkEntry]
        """
        response = self._client.get(f"/filmek/{slug}/linkek")
        response.raise_for_status()
        return parse_linkek_list_html(response.text)

    def list_streaming_services(self, slug: str, *, sheet: SheetSnapshot | None = None) -> list[StreamingRef]:
        """GET szerkesztés Streaming table and merge sheet service ids when present.

        :param str slug: Film slug.
        :param SheetSnapshot | None sheet: Optional pre-fetched sheet for ids/csrf.
        :rtype: list[StreamingRef]
        """
        snapshot = sheet or self.fetch_sheet(slug)
        response = self._client.get(f"/filmek/{slug}/szerkesztes")
        response.raise_for_status()
        catalog = parse_streaming_edit_html(response.text)
        sheet_by_name = {item.name: item for item in snapshot.streaming}
        merged: list[StreamingRef] = []
        for item in catalog:
            sheet_hit = sheet_by_name.get(item.name)
            service_id = item.service_id
            if service_id is None and sheet_hit is not None:
                service_id = sheet_hit.service_id
            already = item.already_present or sheet_hit is not None
            merged.append(
                StreamingRef(
                    name=item.name,
                    service_id=service_id,
                    already_present=already,
                    can_add=item.can_add and not already,
                )
            )
        return merged

    def plan_add_link(self, slug: str, url: str, *, title: str | None = None) -> LinkPlan:
        """Build a dry-run plan to POST a new external link.

        Verified flow: GET ``/filmek/<slug>/linkek/uj`` → POST ``…/linkek/add``
        (``link[link]``, ``commit=Hozzáad``) → often a Mentés confirm form posting
        to ``…/linkek`` with required ``link[title]``.

        :param str slug: Film slug.
        :param str url: Absolute http(s) URL to add.
        :param str | None title: Optional display title for the Mentés step.
        :rtype: LinkPlan
        """
        cleaned = url.strip()
        if not cleaned:
            raise SnittClientError("Link URL is empty.")
        if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
            raise SnittClientError("Link URL must start with http:// or https://.")
        existing = self.list_links(slug)
        already = any(entry.url.rstrip("/") == cleaned.rstrip("/") for entry in existing)
        resolved_title = (title or "").strip() or default_link_title(cleaned)
        notes = [
            "Verified GET /filmek/<slug>/linkek/uj → POST /filmek/<slug>/linkek/add.",
            "Fields (step 1): utf8, link[link], commit=Hozzáad (data-remote).",
            "Often followed by Mentés confirm: POST /filmek/<slug>/linkek with link[title].",
            "Súgó: only lawful sources; illegal torrent/download links are not tolerated.",
        ]
        if already:
            notes.append("Exact URL already on linkek list; save would be refused.")
        return LinkPlan(
            kind="link",
            slug=slug,
            method="POST",
            path=f"/filmek/{slug}/linkek/add",
            fields={
                "utf8": "✓",
                "link[link]": cleaned,
                "commit": "Hozzáad",
                "link[title]": resolved_title,
            },
            url=cleaned,
            already_present=already,
            notes=tuple(notes),
        )

    def plan_add_streaming(
        self,
        slug: str,
        *,
        service_id: int | None = None,
        service_name: str | None = None,
        sheet: SheetSnapshot | None = None,
    ) -> StreamingPlan:
        """Build a dry-run plan to POST a streaming service assignment.

        Verified UI: szerkesztés Streaming table → ``Hozzáadás`` is
        ``POST /filmek/<slug>/streaming?service=<id>`` (``data-remote`` / ``data-method=post``).

        :param str slug: Film slug.
        :param int | None service_id: Numeric service id from ``?service=``.
        :param str | None service_name: Exact display name (e.g. Netflix).
        :param SheetSnapshot | None sheet: Optional pre-fetched sheet.
        :rtype: StreamingPlan
        """
        if service_id is None and not (service_name and service_name.strip()):
            raise SnittClientError("Pass service_id or service_name for streaming add.")
        snapshot = sheet or self.fetch_sheet(slug)
        catalog = self.list_streaming_services(slug, sheet=snapshot)
        match: StreamingRef | None = None
        if service_id is not None:
            for item in catalog:
                if item.service_id == service_id:
                    match = item
                    break
            if match is None:
                # allow planning by id even if name-only present rows lack id
                for item in snapshot.streaming:
                    if item.service_id == service_id:
                        match = StreamingRef(
                            name=item.name, service_id=service_id, already_present=True, can_add=False
                        )
                        break
            if match is None and service_name:
                pass  # fall through to name
            elif match is None:
                raise SnittClientError(f"Unknown streaming service_id={service_id} on szerkesztés for {slug!r}.")
        if match is None and service_name:
            needle = service_name.strip()
            exact = [item for item in catalog if item.name == needle]
            if len(exact) != 1:
                raise SnittClientError(
                    f"service_name {needle!r} matched {len(exact)} catalog rows; pass service_id instead."
                )
            match = exact[0]
        assert match is not None
        resolved_id = match.service_id if match.service_id is not None else service_id
        if resolved_id is None:
            raise SnittClientError(f"Streaming service {match.name!r} has no service_id (already present without add link).")
        already = match.already_present or snapshot.has_streaming_named(match.name)
        notes = [
            "Verified: szerkesztés Streaming «Hozzáadás» → POST /filmek/<slug>/streaming?service=<id>.",
            "Rails UJS: data-remote=true data-method=post; empty body + X-CSRF-Token.",
            "Plain-user MVP: add only; no verified remove control on present rows.",
        ]
        if already:
            notes.append("Service already on sheet/szerkesztés; save would be refused.")
        return StreamingPlan(
            kind="streaming",
            slug=slug,
            method="POST",
            path=f"/filmek/{slug}/streaming?service={resolved_id}",
            fields={},
            service_id=resolved_id,
            service_name=match.name,
            already_present=already,
            notes=tuple(notes),
        )

    def fetch_watching_form(self, slug: str, *, sheet: SheetSnapshot | None = None) -> WatchingFormSnapshot:
        """GET the mark-watched modal and parse episode options / movie fields.

        :param str slug: Film slug.
        :param SheetSnapshot | None sheet: Optional sheet for CSRF header.
        :rtype: WatchingFormSnapshot
        """
        snapshot = sheet or self.fetch_sheet(slug)
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "X-Modal": "true",
            "Accept": "text/html, */*; q=0.01",
        }
        if snapshot.csrf_token:
            headers["X-CSRF-Token"] = snapshot.csrf_token
        response = self._client.get(f"/filmek/{slug}/filmnezesek/uj", headers=headers)
        response.raise_for_status()
        try:
            return parse_watching_form_html(response.text, slug)
        except ValueError as exc:
            raise SnittClientError(str(exc)) from exc

    def plan_mark_watched(
        self,
        slug: str,
        *,
        episode_id: int | None = None,
        episode_label: str | None = None,
        season_number: int | None = None,
        episode_number: int | None = None,
        review: str | None = None,
        spoiler: bool = False,
        in_cinema: bool = False,
        sheet: SheetSnapshot | None = None,
        form: WatchingFormSnapshot | None = None,
    ) -> WatchingPlan:
        """Build a dry-run plan for ``Most néztem…`` (POST filmnezesek).

        Series sheets require ``episode_id``, ``episode_label`` substring match, or
        ``season_number``+``episode_number`` free-text fields from the modal.

        :param str slug: Film slug.
        :param int | None episode_id: Exact episode id from the select.
        :param str | None episode_label: Substring to match against option labels.
        :param int | None season_number: Optional free-text season when no select id.
        :param int | None episode_number: Optional free-text episode when no select id.
        :param str | None review: Optional per-episode opinion (series modal).
        :param bool spoiler: Series spoiler checkbox.
        :param bool in_cinema: Movie cinema checkbox.
        :param SheetSnapshot | None sheet: Optional pre-fetched sheet.
        :param WatchingFormSnapshot | None form: Optional pre-fetched modal.
        :rtype: WatchingPlan
        """
        snapshot = sheet or self.fetch_sheet(slug)
        watching_form = form or self.fetch_watching_form(slug, sheet=snapshot)
        resolved_id = episode_id
        resolved_label = None
        notes = [
            "Verified POST /filmek/<slug>/filmnezesek (data-remote script); commit=Mentés.",
            "UI: series «Most néztem egy részt», movie «Most néztem meg».",
        ]
        fields: dict[str, str] = {
            "utf8": "✓",
            "watching[is_earlier]": "false",
            "enable_stream": "0",
            "commit": "Mentés",
        }
        if watching_form.is_series:
            if resolved_id is None and episode_label:
                needle = episode_label.strip().lower()
                matches = [item for item in watching_form.episodes if needle in item.label.lower()]
                if len(matches) != 1:
                    raise SnittClientError(
                        f"episode_label {episode_label!r} matched {len(matches)} options; pass episode_id instead."
                    )
                resolved_id = matches[0].episode_id
                resolved_label = matches[0].label
            if resolved_id is not None:
                match = next((item for item in watching_form.episodes if item.episode_id == resolved_id), None)
                if match is None:
                    raise SnittClientError(f"episode_id {resolved_id} not in watching modal options.")
                resolved_label = match.label
                fields["watching[episode_id]"] = str(resolved_id)
                fields["watching[season_number]"] = ""
                fields["watching[episode_number]"] = ""
            elif season_number is not None and episode_number is not None:
                fields["watching[episode_id]"] = ""
                fields["watching[season_number]"] = str(season_number)
                fields["watching[episode_number]"] = str(episode_number)
                resolved_label = f"{season_number}. évad {episode_number}. rész"
                notes.append("Using free-text season/episode fields (no select id).")
            else:
                raise SnittClientError("Series mark-watched requires episode_id, episode_label, or season_number+episode_number.")
            fields["watching[review]"] = review or ""
            fields["watching[spoiler]"] = "1" if spoiler else "0"
            fields["watching[cowatchers]"] = ""
        else:
            if episode_id or episode_label or season_number is not None or episode_number is not None:
                raise SnittClientError("Movie mark-watched does not take episode selectors.")
            fields["watching[cowatchers]"] = ""
            fields["watching[in_cinema]"] = "1" if in_cinema else "0"
            notes.append("Movie form fields: watching[in_cinema], watching[cowatchers].")
        return WatchingPlan(
            kind="mark_watched",
            slug=slug,
            method="POST",
            path=watching_form.path,
            fields=fields,
            is_series=watching_form.is_series,
            episode_id=resolved_id,
            episode_label=resolved_label,
            notes=tuple(notes),
        )

    def plan_favorite(self, slug: str, want_favorite: bool, sheet: SheetSnapshot | None = None) -> FavoritePlan:
        """Build a dry-run plan to add or remove the sheet favorite heart.

        Add: POST ``/filmek/<slug>/kedvenc-filmek`` (no ``_method``).
        Remove: POST ``/kedvenc-filmek/<id>`` with ``_method=delete`` (from ``rel=delete``).

        :param str slug: Film slug.
        :param bool want_favorite: Desired heart state after save.
        :param SheetSnapshot | None sheet: Optional pre-fetched sheet.
        :rtype: FavoritePlan
        """
        snapshot = sheet or self.fetch_sheet(slug)
        currently = snapshot.is_favorite
        notes = [
            "Verified JS: click a.favorite → POST href with data._method = rel attr.",
            "Add href=/filmek/<slug>/kedvenc-filmek; remove href=/kedvenc-filmek/<id> rel=delete.",
        ]
        if want_favorite == currently:
            notes.append("Already in desired state; save would be a no-op refuse.")
        if want_favorite:
            path = f"/filmek/{slug}/kedvenc-filmek"
            fields: dict[str, str] = {}
        else:
            if not snapshot.favorite_id or not snapshot.favorite_href:
                raise SnittClientError("Sheet is not favorited; cannot plan favorite remove.")
            path = snapshot.favorite_href
            fields = {"_method": "delete"}
        return FavoritePlan(
            kind="favorite",
            slug=slug,
            method="POST",
            path=path,
            fields=fields,
            want_favorite=want_favorite,
            currently_favorite=currently,
            favorite_id=snapshot.favorite_id,
            notes=tuple(notes),
        )

    def plan_set_rating(self, slug: str, stars: int, sheet: SheetSnapshot | None = None) -> RatingPlan:
        """Build a dry-run plan for the 1–10 personal star rater.

        Verified application.js: POST ``postHref`` with ``_method=patch``,
        ``rating=<1..10>``, ``authenticity_token``.

        :param str slug: Film slug.
        :param int stars: Personal score on the site 10-star scale.
        :param SheetSnapshot | None sheet: Optional pre-fetched sheet.
        :rtype: RatingPlan
        """
        if stars < 1 or stars > 10:
            raise SnittClientError("stars must be an integer from 1 to 10 (Snitt rater units=10).")
        snapshot = sheet or self.fetch_sheet(slug)
        if not snapshot.book_id:
            raise SnittClientError("Missing book_id on sheet; cannot plan set_rating.")
        path = snapshot.set_rating_path or f"/ertekelesek/set_rating?book_id={snapshot.book_id}"
        if not snapshot.csrf_token:
            raise SnittClientError("Missing csrf-token meta on sheet; cannot plan set_rating.")
        return RatingPlan(
            kind="set_rating",
            slug=slug,
            method="POST",
            path=path,
            fields={
                "_method": "patch",
                "authenticity_token": snapshot.csrf_token,
                "rating": str(stars),
            },
            book_id=snapshot.book_id,
            stars=stars,
            previous_stars=snapshot.personal_stars,
            notes=(
                "Verified $.fn.rater ajax: POST postHref, data=_method:patch + rating + authenticity_token.",
                "Defaults units=10 step=1 size=16px; stars_percent = stars * 10.",
            ),
        )

    def plan_delete_watching(self, watching_id: int) -> DeletePlan:
        """Build a dry-run plan to delete one filmnézés row.

        Verified UI: ``/filmnezesek/<id>/szerkesztes`` → Törlés link
        ``href=/filmnezesek/<id>`` ``data-method=delete``.

        :param int watching_id: Watching id from filmnézések / detail URL.
        :rtype: DeletePlan
        """
        if watching_id <= 0:
            raise SnittClientError("watching_id must be a positive integer.")
        return DeletePlan(
            kind="delete_watching",
            resource_id=watching_id,
            method="POST",
            path=f"/filmnezesek/{watching_id}",
            fields={"_method": "delete"},
            notes=(
                "Verified menu: GET /filmnezesek/<id>/szerkesztes → Törlés data-method=delete.",
                "POST /filmnezesek/<id> with _method=delete (Rails UJS).",
                "Verify: detail GET gone/404 or id absent from filmnézések list.",
            ),
        )

    def plan_delete_review(self, review_id: int) -> DeletePlan:
        """Build a dry-run plan to delete one értékelés / review.

        Verified UI: ``/ertekelesek/<id>/szerkesztes`` → Törlés link
        ``href=/ertekelesek/<id>`` ``data-method=delete``.

        :param int review_id: Review id from értékelések list / detail URL.
        :rtype: DeletePlan
        """
        if review_id <= 0:
            raise SnittClientError("review_id must be a positive integer.")
        return DeletePlan(
            kind="delete_review",
            resource_id=review_id,
            method="POST",
            path=f"/ertekelesek/{review_id}",
            fields={"_method": "delete"},
            notes=(
                "Verified menu: GET /ertekelesek/<id>/szerkesztes → Törlés data-method=delete.",
                "POST /ertekelesek/<id> with _method=delete (Rails UJS).",
                "Verify: detail GET gone/404 or id absent from értékelések list.",
            ),
        )

    def plan_add_review(
        self,
        slug: str,
        text: str,
        *,
        spoiler: bool = False,
        sheet: SheetSnapshot | None = None,
    ) -> ReviewPlan:
        """Build a dry-run plan for «Új értékelés» text review POST ``/ertekelesek``.

        :param str slug: Film slug.
        :param str text: Review body.
        :param bool spoiler: Spoiler checkbox.
        :param SheetSnapshot | None sheet: Optional pre-fetched sheet.
        :rtype: ReviewPlan
        """
        if not text.strip():
            raise SnittClientError("Review text is empty.")
        snapshot = sheet or self.fetch_sheet(slug)
        book_id = snapshot.book_id
        if book_id is None:
            # modal also carries review[book_id]; fetch modal if sheet lacked bookmark/rater
            headers = {
                "X-Requested-With": "XMLHttpRequest",
                "X-Modal": "true",
                "Accept": "text/html, */*; q=0.01",
            }
            if snapshot.csrf_token:
                headers["X-CSRF-Token"] = snapshot.csrf_token
            modal = self._client.get(f"/filmek/{slug}/ertekelesek/uj", headers=headers)
            modal.raise_for_status()
            match = re.search(r'name="review\[book_id\]"[^>]*value="(\d+)"', modal.text)
            if not match:
                raise SnittClientError("Could not resolve review[book_id] from sheet or modal.")
            book_id = int(match.group(1))
        return ReviewPlan(
            kind="review",
            slug=slug,
            method="POST",
            path="/ertekelesek",
            fields={
                "utf8": "✓",
                "review[book_id]": str(book_id),
                "review[review]": text,
                "review[spoiler]": "1" if spoiler else "0",
                "enable_stream": "0",
                "commit": "Mentés",
            },
            book_id=book_id,
            text_length=len(text),
            notes=(
                "Verified GET /filmek/<slug>/ertekelesek/uj → POST /ertekelesek.",
                "Fields: review[book_id], review[review], review[spoiler], commit=Mentés.",
                "Verify via /filmek/<slug>/ertekelesek or /tagok/<user>/ertekelesek.",
            ),
        )

    def save_tagging(self, plan: TaggingPlan, *, allow_save: bool, sheet: SheetSnapshot | None = None) -> SaveResult:
        """POST a tagging plan only when allow_save is True, then re-fetch verify.

        :param TaggingPlan plan: Dry-run tagging plan.
        :param bool allow_save: Explicit write gate; False refuses the POST.
        :param SheetSnapshot | None sheet: Sheet used for CSRF; fetched if omitted.
        :rtype: SaveResult
        """
        if not allow_save:
            raise SnittClientError("Refusing save: pass allow_save=True only with explicit permission.")
        if plan.already_present:
            raise SnittClientError(f"Refusing save: {plan.name!r} already present on sheet.")
        snapshot = sheet or self.fetch_sheet(plan.slug)
        if not snapshot.csrf_token:
            raise SnittClientError("Missing csrf-token meta on sheet; cannot POST.")
        response = self._client.post(
            plan.path,
            data=plan.fields,
            headers=self._write_headers(snapshot.csrf_token),
        )
        body = response.text
        verified = None
        details: dict[str, Any] = {}
        if response.status_code == 200:
            after = self.fetch_sheet(plan.slug)
            verified = after.has_tag_named(plan.name)
            details = {
                "after_has_name": verified,
                "matching_hrefs": [tag.href for tag in after.all_tags if tag.name == plan.name],
            }
        return SaveResult(
            ok=response.status_code == 200 and bool(verified),
            status_code=response.status_code,
            response_content_type=response.headers.get("content-type"),
            response_body=body[:4000],
            verified=verified,
            verify_details=details,
        )

    def save_description(
        self,
        plan: DescriptionPlan,
        *,
        allow_save: bool,
        sheet: SheetSnapshot | None = None,
        verify_substring: str | None = None,
    ) -> SaveResult:
        """POST a description plan only when allow_save is True, then verify on leirasok list.

        :param DescriptionPlan plan: Dry-run description plan.
        :param bool allow_save: Explicit write gate.
        :param SheetSnapshot | None sheet: Sheet used for CSRF.
        :param str | None verify_substring: Text that must appear on the leirasok list after save.
        :rtype: SaveResult
        """
        if not allow_save:
            raise SnittClientError("Refusing save: pass allow_save=True only with explicit permission.")
        snapshot = sheet or self.fetch_sheet(plan.slug)
        if not snapshot.csrf_token:
            raise SnittClientError("Missing csrf-token meta on sheet; cannot POST.")
        response = self._client.post(
            plan.path,
            data=plan.fields,
            headers=self._write_headers(snapshot.csrf_token),
        )
        body = response.text
        verified = None
        details: dict[str, Any] = {}
        if response.status_code == 200:
            list_response = self._client.get(f"/filmek/{plan.slug}/leirasok")
            list_response.raise_for_status()
            needle = verify_substring or plan.fields["description[description]"][:80]
            verified = description_list_contains_text(list_response.text, needle)
            details = {
                "leirasok_ids": extract_leirasok_ids(list_response.text),
                "list_contains_verify_substring": verified,
                "sheet_after_nav": self.fetch_sheet(plan.slug).description_nav_text,
            }
        return SaveResult(
            ok=response.status_code == 200 and bool(verified),
            status_code=response.status_code,
            response_content_type=response.headers.get("content-type"),
            response_body=body[:4000],
            verified=verified,
            verify_details=details,
        )

    def save_link(self, plan: LinkPlan, *, allow_save: bool, sheet: SheetSnapshot | None = None) -> SaveResult:
        """POST a link plan only when allow_save is True, then verify on linkek list.

        Step 1 posts ``…/linkek/add``. If Snitt returns the Mentés confirm form,
        step 2 posts ``…/linkek`` with ``link[title]``.

        :param LinkPlan plan: Dry-run link plan.
        :param bool allow_save: Explicit write gate.
        :param SheetSnapshot | None sheet: Sheet used for CSRF.
        :rtype: SaveResult
        """
        if not allow_save:
            raise SnittClientError("Refusing save: pass allow_save=True only with explicit permission.")
        if plan.already_present:
            raise SnittClientError(f"Refusing save: link URL already present: {plan.url!r}")
        snapshot = sheet or self.fetch_sheet(plan.slug)
        if not snapshot.csrf_token:
            raise SnittClientError("Missing csrf-token meta on sheet; cannot POST.")
        step1_fields = {
            "utf8": plan.fields.get("utf8", "✓"),
            "link[link]": plan.fields.get("link[link]", plan.url),
            "commit": plan.fields.get("commit", "Hozzáad"),
        }
        response = self._client.post(
            plan.path,
            data=step1_fields,
            headers=self._write_headers(snapshot.csrf_token),
        )
        body = response.text
        confirm = parse_link_confirm_form(body) if response.status_code == 200 else None
        if confirm is not None:
            preferred_title = (plan.fields.get("link[title]") or "").strip()
            if preferred_title:
                confirm["link[title]"] = preferred_title
            elif not confirm.get("link[title]"):
                confirm["link[title]"] = default_link_title(plan.url)
            response = self._client.post(
                confirm["action"],
                data={
                    "utf8": confirm.get("utf8", "✓"),
                    "link[link]": confirm["link[link]"],
                    "link[title]": confirm["link[title]"],
                    "commit": confirm.get("commit", "Mentés"),
                },
                headers=self._write_headers(snapshot.csrf_token),
            )
            body = response.text
        verified = None
        details: dict[str, Any] = {}
        if response.status_code == 200:
            after = self.list_links(plan.slug)
            verified = any(entry.url.rstrip("/") == plan.url.rstrip("/") for entry in after)
            details = {
                "link_count": len(after),
                "matching_ids": [entry.link_id for entry in after if entry.url.rstrip("/") == plan.url.rstrip("/")],
                "links_nav_after": self.fetch_sheet(plan.slug).links_nav_text,
                "used_confirm_step": confirm is not None,
            }
        return SaveResult(
            ok=response.status_code == 200 and bool(verified),
            status_code=response.status_code,
            response_content_type=response.headers.get("content-type"),
            response_body=body[:4000],
            verified=verified,
            verify_details=details,
        )

    def save_streaming(
        self, plan: StreamingPlan, *, allow_save: bool, sheet: SheetSnapshot | None = None
    ) -> SaveResult:
        """POST a streaming plan only when allow_save is True, then verify on sheet.

        :param StreamingPlan plan: Dry-run streaming plan.
        :param bool allow_save: Explicit write gate.
        :param SheetSnapshot | None sheet: Sheet used for CSRF.
        :rtype: SaveResult
        """
        if not allow_save:
            raise SnittClientError("Refusing save: pass allow_save=True only with explicit permission.")
        if plan.already_present:
            raise SnittClientError(f"Refusing save: streaming {plan.service_name!r} already present.")
        snapshot = sheet or self.fetch_sheet(plan.slug)
        if not snapshot.csrf_token:
            raise SnittClientError("Missing csrf-token meta on sheet; cannot POST.")
        response = self._client.post(
            plan.path,
            data=plan.fields or None,
            headers=self._write_headers(snapshot.csrf_token),
        )
        body = response.text
        verified = None
        details: dict[str, Any] = {}
        if response.status_code == 200:
            after = self.fetch_sheet(plan.slug)
            verified = after.has_streaming_named(plan.service_name)
            details = {
                "streaming_after": [item.to_dict() for item in after.streaming],
                "expected_name": plan.service_name,
                "expected_service_id": plan.service_id,
            }
        return SaveResult(
            ok=response.status_code == 200 and bool(verified),
            status_code=response.status_code,
            response_content_type=response.headers.get("content-type"),
            response_body=body[:4000],
            verified=verified,
            verify_details=details,
        )

    def save_watching(
        self,
        plan: WatchingPlan,
        *,
        allow_save: bool,
        sheet: SheetSnapshot | None = None,
        verify_year: int | None = None,
    ) -> SaveResult:
        """POST a mark-watched plan only when allow_save is True, then verify filmnézések.

        :param WatchingPlan plan: Dry-run watching plan.
        :param bool allow_save: Explicit write gate.
        :param SheetSnapshot | None sheet: Sheet used for CSRF.
        :param int | None verify_year: Year page to scan after save (default: current year).
        :rtype: SaveResult
        """
        if not allow_save:
            raise SnittClientError("Refusing save: pass allow_save=True only with explicit permission.")
        snapshot = sheet or self.fetch_sheet(plan.slug)
        if not snapshot.csrf_token:
            raise SnittClientError("Missing csrf-token meta on sheet; cannot POST.")
        response = self._client.post(
            plan.path,
            data=plan.fields,
            headers=self._write_headers(snapshot.csrf_token),
        )
        body = response.text
        verified = None
        details: dict[str, Any] = {}
        if response.status_code == 200:
            year = verify_year or date.today().year
            events = self.list_watchings(year=year)
            matched = [event for event in events if event.slug == plan.slug]
            if plan.episode_label:
                matched = [
                    event
                    for event in matched
                    if event.episode and plan.episode_label.split(" · ")[0].lower() in event.episode.lower()
                ]
            verified = bool(matched)
            details = {
                "verify_year": year,
                "matched_count": len(matched),
                "matched_watching_ids": [event.watching_id for event in matched[:5]],
            }
        return SaveResult(
            ok=response.status_code == 200 and bool(verified),
            status_code=response.status_code,
            response_content_type=response.headers.get("content-type"),
            response_body=body[:4000],
            verified=verified,
            verify_details=details,
        )

    def save_favorite(self, plan: FavoritePlan, *, allow_save: bool, sheet: SheetSnapshot | None = None) -> SaveResult:
        """POST a favorite plan only when allow_save is True, then re-fetch heart state.

        :param FavoritePlan plan: Dry-run favorite plan.
        :param bool allow_save: Explicit write gate.
        :param SheetSnapshot | None sheet: Sheet used for CSRF.
        :rtype: SaveResult
        """
        if not allow_save:
            raise SnittClientError("Refusing save: pass allow_save=True only with explicit permission.")
        if plan.want_favorite == plan.currently_favorite:
            raise SnittClientError("Refusing save: favorite already in desired state.")
        snapshot = sheet or self.fetch_sheet(plan.slug)
        if not snapshot.csrf_token:
            raise SnittClientError("Missing csrf-token meta on sheet; cannot POST.")
        response = self._client.post(
            plan.path,
            data=plan.fields or None,
            headers=self._write_headers(snapshot.csrf_token),
        )
        body = response.text
        verified = None
        details: dict[str, Any] = {}
        if response.status_code == 200:
            after = self.fetch_sheet(plan.slug)
            verified = after.is_favorite == plan.want_favorite
            details = {
                "is_favorite": after.is_favorite,
                "favorite_href": after.favorite_href,
                "favorite_id": after.favorite_id,
            }
        return SaveResult(
            ok=response.status_code == 200 and bool(verified),
            status_code=response.status_code,
            response_content_type=response.headers.get("content-type"),
            response_body=body[:4000],
            verified=verified,
            verify_details=details,
        )

    def save_rating(self, plan: RatingPlan, *, allow_save: bool, sheet: SheetSnapshot | None = None) -> SaveResult:
        """POST a set_rating plan only when allow_save is True, then re-fetch stars.

        :param RatingPlan plan: Dry-run rating plan.
        :param bool allow_save: Explicit write gate.
        :param SheetSnapshot | None sheet: Sheet used for CSRF.
        :rtype: SaveResult
        """
        if not allow_save:
            raise SnittClientError("Refusing save: pass allow_save=True only with explicit permission.")
        snapshot = sheet or self.fetch_sheet(plan.slug)
        if not snapshot.csrf_token:
            raise SnittClientError("Missing csrf-token meta on sheet; cannot POST.")
        response = self._client.post(
            plan.path,
            data=plan.fields,
            headers=self._write_headers(snapshot.csrf_token),
        )
        body = response.text
        verified = None
        details: dict[str, Any] = {}
        if response.status_code == 200:
            after = self.fetch_sheet(plan.slug)
            verified = after.personal_stars is not None and float(after.personal_stars) == float(plan.stars)
            details = {
                "personal_stars": after.personal_stars,
                "set_rating_path": after.set_rating_path,
                "book_id": after.book_id,
            }
        return SaveResult(
            ok=response.status_code == 200 and bool(verified),
            status_code=response.status_code,
            response_content_type=response.headers.get("content-type"),
            response_body=body[:4000],
            verified=verified,
            verify_details=details,
        )

    def save_review(
        self,
        plan: ReviewPlan,
        *,
        allow_save: bool,
        sheet: SheetSnapshot | None = None,
        verify_substring: str | None = None,
    ) -> SaveResult:
        """POST a review plan only when allow_save is True, then verify on film értékelések.

        :param ReviewPlan plan: Dry-run review plan.
        :param bool allow_save: Explicit write gate.
        :param SheetSnapshot | None sheet: Sheet used for CSRF.
        :param str | None verify_substring: Text that must appear after save.
        :rtype: SaveResult
        """
        if not allow_save:
            raise SnittClientError("Refusing save: pass allow_save=True only with explicit permission.")
        snapshot = sheet or self.fetch_sheet(plan.slug)
        if not snapshot.csrf_token:
            raise SnittClientError("Missing csrf-token meta on sheet; cannot POST.")
        response = self._client.post(
            plan.path,
            data=plan.fields,
            headers=self._write_headers(snapshot.csrf_token),
        )
        body = response.text
        verified = None
        details: dict[str, Any] = {}
        if response.status_code == 200:
            list_response = self._client.get(f"/filmek/{plan.slug}/ertekelesek")
            list_response.raise_for_status()
            needle = verify_substring or plan.fields["review[review]"][:80]
            verified = needle in list_response.text
            details = {
                "list_contains_verify_substring": verified,
                "sheet_ertekelesek_path": f"/filmek/{plan.slug}/ertekelesek",
            }
        return SaveResult(
            ok=response.status_code == 200 and bool(verified),
            status_code=response.status_code,
            response_content_type=response.headers.get("content-type"),
            response_body=body[:4000],
            verified=verified,
            verify_details=details,
        )

    def save_delete_watching(self, plan: DeletePlan, *, allow_save: bool) -> SaveResult:
        """POST a watching delete only when allow_save is True, then verify detail is gone.

        :param DeletePlan plan: Dry-run delete plan (kind delete_watching).
        :param bool allow_save: Explicit write gate.
        :rtype: SaveResult
        """
        if plan.kind != "delete_watching":
            raise SnittClientError(f"Expected delete_watching plan, got {plan.kind!r}.")
        return self._save_delete(plan, allow_save=allow_save, csrf_path=plan.path)

    def save_delete_review(self, plan: DeletePlan, *, allow_save: bool) -> SaveResult:
        """POST a review delete only when allow_save is True, then verify detail is gone.

        :param DeletePlan plan: Dry-run delete plan (kind delete_review).
        :param bool allow_save: Explicit write gate.
        :rtype: SaveResult
        """
        if plan.kind != "delete_review":
            raise SnittClientError(f"Expected delete_review plan, got {plan.kind!r}.")
        return self._save_delete(plan, allow_save=allow_save, csrf_path=plan.path)

    def _save_delete(self, plan: DeletePlan, *, allow_save: bool, csrf_path: str) -> SaveResult:
        if not allow_save:
            raise SnittClientError("Refusing save: pass allow_save=True only with explicit permission.")
        csrf_token = self._csrf_from_path(csrf_path)
        if not csrf_token:
            raise SnittClientError(f"Missing csrf-token on {csrf_path}; cannot POST delete.")
        response = self._client.post(
            plan.path,
            data=plan.fields,
            headers=self._write_headers(csrf_token),
        )
        body = response.text
        verified = None
        details: dict[str, Any] = {}
        if response.status_code in (200, 302):
            check = self._client.get(plan.path)
            # after destroy Snitt typically 404 or redirects away from the resource
            gone = check.status_code == 404 or (
                check.status_code == 200 and f"/{plan.resource_id}" not in check.url.path and plan.path not in str(check.url)
            )
            if check.status_code == 200 and plan.path.rstrip("/") in str(check.url):
                # still on detail URL — treat as not deleted unless body clearly missing resource chrome
                gone = False
            verified = gone or check.status_code == 404
            details = {
                "verify_get_status": check.status_code,
                "verify_get_url": str(check.url),
                "resource_gone": verified,
            }
        return SaveResult(
            ok=response.status_code in (200, 302) and bool(verified),
            status_code=response.status_code,
            response_content_type=response.headers.get("content-type"),
            response_body=body[:4000],
            verified=verified,
            verify_details=details,
        )

    def _csrf_from_path(self, path: str) -> str | None:
        """GET a page and return meta csrf-token content.

        :param str path: Absolute path that should include CSRF meta when logged in.
        :rtype: str | None
        """
        response = self._client.get(path)
        if response.status_code != 200:
            # try szerkesztes modal parent list is not needed; sheet home as fallback
            return None
        match = re.search(r'name="csrf-token"\s+content="([^"]+)"', response.text)
        if match:
            return match.group(1)
        match = re.search(r'content="([^"]+)"\s+name="csrf-token"', response.text)
        return match.group(1) if match else None

    def _list_catalog(self, api_path: str, query: str, csrf_token: str | None) -> list[TagRef]:
        # Snitt autocomplete: GET …_with_names.json?q=<query>; empty/whitespace q → 403.
        stripped = query.strip()
        if not stripped:
            raise SnittClientError(
                f"Autocomplete catalog requires non-empty q (empty/whitespace returns 403): {api_path}"
            )
        headers = {"Accept": JSON_ACCEPT, "X-Requested-With": "XMLHttpRequest"}
        if csrf_token:
            headers["X-CSRF-Token"] = csrf_token
        response = self._client.get(api_path, params={"q": stripped}, headers=headers)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise SnittClientError(f"Unexpected autocomplete payload from {api_path}")
        results: list[TagRef] = []
        for item in payload:
            if not isinstance(item, dict) or "id" not in item or "name" not in item:
                continue
            results.append(TagRef(name=str(item["name"]), tag_id=int(item["id"]), href=None))
        return results

    def _resolve_catalog(self, api_path: str, query: str, exact_name: str | None, csrf_token: str | None) -> TagRef:
        matches = self._list_catalog(api_path, query, csrf_token)
        target = exact_name or query.strip()
        exact = [item for item in matches if item.name == target]
        if not exact:
            raise SnittClientError(f"No exact autocomplete match for {target!r} in {api_path}?q={quote(query.strip())}")
        return exact[0]

    def _tagging_plan(self, *, kind: str, slug: str, name: str, tag_id: int, sheet: SheetSnapshot) -> TaggingPlan:
        if not tag_id:
            raise SnittClientError(f"Missing tag id for {name!r}")
        already = sheet.has_tag_named(name)
        notes = [
            "Verified POST path: /filmek/<slug>/cimkezesek with tagging[tag_id] and commit=Hozzáadás.",
            "CSRF via X-CSRF-Token from sheet meta csrf-token (no authenticity_token in modal).",
            "No tag/genre remove in plain-user MVP.",
        ]
        if kind == "genre":
            notes.append("Genre UI uses /cimkezesek/uj-mufaj and /api/genres_with_names.json.")
        else:
            notes.append("Open tag UI uses /cimkezesek/uj and /api/open_tags_with_names.json.")
        if already:
            notes.append("Name already visible on sheet; save would be refused.")
        return TaggingPlan(
            kind=kind,
            slug=slug,
            name=name,
            tag_id=tag_id,
            method="POST",
            path=f"/filmek/{slug}/cimkezesek",
            fields={
                "utf8": "✓",
                "tagging[tag_id]": str(tag_id),
                "commit": "Hozzáadás",
            },
            already_present=already,
            notes=tuple(notes),
        )

    def _write_headers(self, csrf_token: str) -> dict[str, str]:
        return {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": csrf_token,
            "Accept": JS_ACCEPT,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }


def absolute_url(base_url: str, path: str) -> str:
    """Join base URL and path.

    :param str base_url: Origin.
    :param str path: Absolute path.
    :rtype: str
    """
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
