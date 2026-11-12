"""Snitt HTTP client: fetch, resolve, dry-run plans, gated save, verify."""

from __future__ import annotations

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
    DescriptionPlan,
    RatingEntry,
    SaveResult,
    SeriesWatchSpan,
    SheetSnapshot,
    TaggingPlan,
    TagRef,
    WatchingEvent,
)
from snitt_client.parse import description_list_contains_text, extract_leirasok_ids, parse_sheet_html
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

    def _resolve_catalog(self, api_path: str, query: str, exact_name: str | None, csrf_token: str | None) -> TagRef:
        headers = {"Accept": JSON_ACCEPT, "X-Requested-With": "XMLHttpRequest"}
        if csrf_token:
            headers["X-CSRF-Token"] = csrf_token
        response = self._client.get(api_path, params={"q": query}, headers=headers)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise SnittClientError(f"Unexpected autocomplete payload from {api_path}")
        target = exact_name or query
        matches = [item for item in payload if isinstance(item, dict) and item.get("name") == target]
        if not matches:
            raise SnittClientError(f"No exact autocomplete match for {target!r} in {api_path}?q={quote(query)}")
        item = matches[0]
        return TagRef(name=str(item["name"]), tag_id=int(item["id"]), href=None)

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
