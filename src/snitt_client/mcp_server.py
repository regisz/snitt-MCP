"""Local stdio MCP server over SnittClient (thin adapter)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from snitt_client.client import SnittClient, SnittClientError
from snitt_client.session import SessionConfigError

ClientFactory = Callable[[], SnittClient]
_TOOL_ERRORS = (SessionConfigError, SnittClientError, OSError, httpx.HTTPError)

TOOL_NAMES: tuple[str, ...] = (
    "snitt_fetch_sheet",
    "snitt_resolve_tag",
    "snitt_resolve_genre",
    "snitt_list_tags",
    "snitt_list_genres",
    "snitt_plan_add_tag",
    "snitt_plan_add_genre",
    "snitt_plan_add_description",
    "snitt_apply_tag",
    "snitt_apply_genre",
    "snitt_apply_description",
    "snitt_list_links",
    "snitt_list_streaming",
    "snitt_plan_add_link",
    "snitt_apply_link",
    "snitt_plan_add_streaming",
    "snitt_apply_streaming",
    "snitt_verify_sheet",
    "snitt_list_watchings",
    "snitt_series_watch_span",
    "snitt_list_ratings",
    "snitt_fetch_rating",
    "snitt_fetch_watching_form",
    "snitt_plan_mark_watched",
    "snitt_apply_mark_watched",
    "snitt_plan_favorite",
    "snitt_apply_favorite",
    "snitt_plan_set_rating",
    "snitt_apply_set_rating",
    "snitt_plan_add_review",
    "snitt_apply_review",
    "snitt_plan_delete_watching",
    "snitt_apply_delete_watching",
    "snitt_plan_delete_review",
    "snitt_apply_delete_review",
)


def _client_factory(config_path: Path | None = None) -> ClientFactory:
    def factory() -> SnittClient:
        return SnittClient(config_path=config_path)

    return factory


def _error_payload(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": str(exc), "error_type": type(exc).__name__}


def create_mcp(client_factory: ClientFactory | None = None, config_path: Path | None = None) -> FastMCP:
    """Create a FastMCP server exposing SnittClient operations as tools.

    Session cookies come from ENV/config via SnittClient (never from tool args).

    :param ClientFactory | None client_factory: Optional factory for tests.
    :param Path | None config_path: Optional cookie file override for the default factory.
    :rtype: FastMCP
    """
    factory = client_factory or _client_factory(config_path)
    mcp = FastMCP(
        name="snitt",
        instructions=(
            "Snitt.hu sheet tools. Prefer plan_* dry-runs first. "
            "Writes require allow_save=true and only when Balázs explicitly allowed the change. "
            "Session comes from SNITT_COOKIE or ~/.snitt-hu-downloader.cfg — never from tool args."
        ),
    )

    @mcp.tool(name="snitt_fetch_sheet", description="Fetch and parse a Snitt film sheet by slug (GET only).")
    def snitt_fetch_sheet(slug: str) -> dict[str, Any]:
        try:
            with factory() as client:
                sheet = client.fetch_sheet(slug)
                return {"ok": True, "sheet": sheet.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(name="snitt_resolve_tag", description="Resolve an open tag id via /api/open_tags_with_names.json.")
    def snitt_resolve_tag(name: str) -> dict[str, Any]:
        try:
            with factory() as client:
                tag = client.resolve_open_tag(name, exact_name=name)
                return {"ok": True, "tag": tag.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(name="snitt_resolve_genre", description="Resolve a műfaj id via /api/genres_with_names.json.")
    def snitt_resolve_genre(name: str) -> dict[str, Any]:
        try:
            with factory() as client:
                genre = client.resolve_genre(name, exact_name=name)
                return {"ok": True, "genre": genre.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_list_tags",
        description=(
            "List open-tag autocomplete matches (GET /api/open_tags_with_names.json?q=). "
            "Non-empty q required (empty → 403). Broad prefixes may be capped (~20); no verified pagination."
        ),
    )
    def snitt_list_tags(q: str) -> dict[str, Any]:
        try:
            with factory() as client:
                tags = client.list_open_tags(q)
                return {"ok": True, "q": q.strip(), "count": len(tags), "tags": [tag.to_dict() for tag in tags]}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_list_genres",
        description=(
            "List műfaj autocomplete matches (GET /api/genres_with_names.json?q=). "
            "Non-empty q required (empty → 403). No verified pagination params."
        ),
    )
    def snitt_list_genres(q: str) -> dict[str, Any]:
        try:
            with factory() as client:
                genres = client.list_genres(q)
                return {
                    "ok": True,
                    "q": q.strip(),
                    "count": len(genres),
                    "genres": [genre.to_dict() for genre in genres],
                }
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(name="snitt_plan_add_tag", description="Dry-run plan to add an open tag (no POST).")
    def snitt_plan_add_tag(slug: str, name: str) -> dict[str, Any]:
        try:
            with factory() as client:
                plan = client.plan_add_tag(slug, name)
                return {"ok": True, "dry_run": True, "plan": plan.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(name="snitt_plan_add_genre", description="Dry-run plan to add a műfaj (no POST).")
    def snitt_plan_add_genre(slug: str, name: str) -> dict[str, Any]:
        try:
            with factory() as client:
                plan = client.plan_add_genre(slug, name)
                return {"ok": True, "dry_run": True, "plan": plan.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(name="snitt_plan_add_description", description="Dry-run plan to add a description (no POST).")
    def snitt_plan_add_description(slug: str, text: str) -> dict[str, Any]:
        try:
            with factory() as client:
                plan = client.plan_add_description(slug, text)
                return {"ok": True, "dry_run": True, "plan": plan.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_apply_tag",
        description="POST an open tag only when allow_save=true, then re-fetch verify. Default refuses writes.",
    )
    def snitt_apply_tag(slug: str, name: str, allow_save: bool = False) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use snitt_plan_add_tag first",
            }
        try:
            with factory() as client:
                plan = client.plan_add_tag(slug, name)
                result = client.save_tagging(plan, allow_save=True)
                return {"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_apply_genre",
        description="POST a műfaj only when allow_save=true, then re-fetch verify. Default refuses writes.",
    )
    def snitt_apply_genre(slug: str, name: str, allow_save: bool = False) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use snitt_plan_add_genre first",
            }
        try:
            with factory() as client:
                plan = client.plan_add_genre(slug, name)
                result = client.save_tagging(plan, allow_save=True)
                return {"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_apply_description",
        description="POST a description only when allow_save=true, then verify on leirasok list. Default refuses writes.",
    )
    def snitt_apply_description(slug: str, text: str, allow_save: bool = False) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use snitt_plan_add_description first",
            }
        try:
            with factory() as client:
                plan = client.plan_add_description(slug, text)
                result = client.save_description(plan, allow_save=True)
                return {"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_list_links",
        description="List external links from GET /filmek/<slug>/linkek (read-only).",
    )
    def snitt_list_links(slug: str) -> dict[str, Any]:
        try:
            with factory() as client:
                links = client.list_links(slug)
                return {"ok": True, "count": len(links), "links": [entry.to_dict() for entry in links]}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_list_streaming",
        description=(
            "List Streaming catalog from szerkesztés (Hozzáadás ?service= ids) merged with sheet coverbox. "
            "Read-only GET."
        ),
    )
    def snitt_list_streaming(slug: str) -> dict[str, Any]:
        try:
            with factory() as client:
                services = client.list_streaming_services(slug)
                return {"ok": True, "count": len(services), "streaming": [item.to_dict() for item in services]}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_plan_add_link",
        description="Dry-run plan to add an external link (POST …/linkek/add; no POST until apply).",
    )
    def snitt_plan_add_link(slug: str, url: str, title: str | None = None) -> dict[str, Any]:
        try:
            with factory() as client:
                plan = client.plan_add_link(slug, url, title=title)
                return {"ok": True, "dry_run": True, "plan": plan.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_apply_link",
        description=(
            "POST a link only when allow_save=true, then verify on linkek list. "
            "Handles Snitt Mentés confirm (link[title]). Default refuses writes."
        ),
    )
    def snitt_apply_link(
        slug: str, url: str, allow_save: bool = False, title: str | None = None
    ) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use snitt_plan_add_link first",
            }
        try:
            with factory() as client:
                plan = client.plan_add_link(slug, url, title=title)
                result = client.save_link(plan, allow_save=True)
                return {"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_plan_add_streaming",
        description=(
            "Dry-run plan to add a Streaming service (POST …/streaming?service=<id>). "
            "Pass service_id and/or exact service_name from snitt_list_streaming."
        ),
    )
    def snitt_plan_add_streaming(
        slug: str, service_id: int | None = None, service_name: str | None = None
    ) -> dict[str, Any]:
        try:
            with factory() as client:
                plan = client.plan_add_streaming(slug, service_id=service_id, service_name=service_name)
                return {"ok": True, "dry_run": True, "plan": plan.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_apply_streaming",
        description="POST streaming only when allow_save=true, then verify on sheet. Default refuses writes.",
    )
    def snitt_apply_streaming(
        slug: str,
        service_id: int | None = None,
        service_name: str | None = None,
        allow_save: bool = False,
    ) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use snitt_plan_add_streaming first",
            }
        try:
            with factory() as client:
                plan = client.plan_add_streaming(slug, service_id=service_id, service_name=service_name)
                result = client.save_streaming(plan, allow_save=True)
                return {"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_verify_sheet",
        description="Re-fetch a sheet and optionally check that an expected tag/műfaj name is present (GET only).",
    )
    def snitt_verify_sheet(slug: str, expected_tag: str | None = None) -> dict[str, Any]:
        try:
            with factory() as client:
                sheet = client.fetch_sheet(slug)
                payload: dict[str, Any] = {"ok": True, "sheet": sheet.to_dict()}
                if expected_tag is not None:
                    present = sheet.has_tag_named(expected_tag)
                    payload["expected_tag"] = expected_tag
                    payload["expected_tag_present"] = present
                    payload["ok"] = present
                return payload
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_list_watchings",
        description="List Balázs filmnézések rows (GET /tagok/<user>/filmnezesek). Optional year/type/tag/place filters.",
    )
    def snitt_list_watchings(
        year: int | None = None,
        watching_type: str | None = None,
        tag: str | None = None,
        place: str | None = None,
        username: str = "balage",
    ) -> dict[str, Any]:
        try:
            with factory() as client:
                events = client.list_watchings(
                    username=username,
                    year=year,
                    watching_type=watching_type,
                    tag=tag,
                    place=place,
                )
                return {"ok": True, "count": len(events), "watchings": [event.to_dict() for event in events]}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_series_watch_span",
        description="First/latest watch times for a series slug from filmnézések year pages. finished_at not available on site.",
    )
    def snitt_series_watch_span(
        slug: str,
        years: list[int],
        watching_type: str = "series",
        username: str = "balage",
    ) -> dict[str, Any]:
        try:
            with factory() as client:
                span = client.series_watch_span(
                    slug,
                    username=username,
                    years=years,
                    watching_type=watching_type,
                )
                return {"ok": True, "span": span.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_list_ratings",
        description="List Balázs értékelések: personal stars (and stars_percent=stars*10) plus review text when present.",
    )
    def snitt_list_ratings(
        page: int = 1,
        order: str | None = None,
        rating: int | None = None,
        is_reviewed: bool | None = None,
        username: str = "balage",
    ) -> dict[str, Any]:
        try:
            with factory() as client:
                entries, meta = client.list_ratings(
                    username=username,
                    page=page,
                    order=order,
                    rating=rating,
                    is_reviewed=is_reviewed,
                )
                return {
                    "ok": True,
                    "count": len(entries),
                    "meta": meta,
                    "ratings": [entry.to_dict() for entry in entries],
                }
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_fetch_rating",
        description="Fetch one értékelés by id: stars, optional review text, rated_at; community_average_percent is site average.",
    )
    def snitt_fetch_rating(review_id: int) -> dict[str, Any]:
        try:
            with factory() as client:
                entry = client.fetch_rating(review_id)
                return {"ok": True, "rating": entry.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_fetch_watching_form",
        description="GET mark-watched modal: series episode options or movie in_cinema fields (no POST).",
    )
    def snitt_fetch_watching_form(slug: str) -> dict[str, Any]:
        try:
            with factory() as client:
                form = client.fetch_watching_form(slug)
                return {"ok": True, "form": form.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_plan_mark_watched",
        description="Dry-run plan for Most néztem… (POST filmnezesek). Series needs episode_id or episode_label.",
    )
    def snitt_plan_mark_watched(
        slug: str,
        episode_id: int | None = None,
        episode_label: str | None = None,
        season_number: int | None = None,
        episode_number: int | None = None,
        review: str | None = None,
        spoiler: bool = False,
        in_cinema: bool = False,
    ) -> dict[str, Any]:
        try:
            with factory() as client:
                plan = client.plan_mark_watched(
                    slug,
                    episode_id=episode_id,
                    episode_label=episode_label,
                    season_number=season_number,
                    episode_number=episode_number,
                    review=review,
                    spoiler=spoiler,
                    in_cinema=in_cinema,
                )
                return {"ok": True, "dry_run": True, "plan": plan.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_apply_mark_watched",
        description="POST mark-watched only when allow_save=true, then verify filmnézések. Default refuses writes.",
    )
    def snitt_apply_mark_watched(
        slug: str,
        episode_id: int | None = None,
        episode_label: str | None = None,
        season_number: int | None = None,
        episode_number: int | None = None,
        review: str | None = None,
        spoiler: bool = False,
        in_cinema: bool = False,
        allow_save: bool = False,
    ) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use snitt_plan_mark_watched first",
            }
        try:
            with factory() as client:
                plan = client.plan_mark_watched(
                    slug,
                    episode_id=episode_id,
                    episode_label=episode_label,
                    season_number=season_number,
                    episode_number=episode_number,
                    review=review,
                    spoiler=spoiler,
                    in_cinema=in_cinema,
                )
                result = client.save_watching(plan, allow_save=True)
                return {"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_plan_favorite",
        description="Dry-run favorite heart plan (add POST …/kedvenc-filmek or remove POST /kedvenc-filmek/<id> _method=delete).",
    )
    def snitt_plan_favorite(slug: str, want_favorite: bool) -> dict[str, Any]:
        try:
            with factory() as client:
                plan = client.plan_favorite(slug, want_favorite)
                return {"ok": True, "dry_run": True, "plan": plan.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_apply_favorite",
        description="POST favorite heart only when allow_save=true, then re-fetch verify. Default refuses writes.",
    )
    def snitt_apply_favorite(slug: str, want_favorite: bool, allow_save: bool = False) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use snitt_plan_favorite first",
            }
        try:
            with factory() as client:
                plan = client.plan_favorite(slug, want_favorite)
                result = client.save_favorite(plan, allow_save=True)
                return {"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_plan_set_rating",
        description="Dry-run personal 1–10 star rating via POST /ertekelesek/set_rating?book_id=… (_method=patch).",
    )
    def snitt_plan_set_rating(slug: str, stars: int) -> dict[str, Any]:
        try:
            with factory() as client:
                plan = client.plan_set_rating(slug, stars)
                return {"ok": True, "dry_run": True, "plan": plan.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_apply_set_rating",
        description="POST personal stars only when allow_save=true, then re-fetch verify. Default refuses writes.",
    )
    def snitt_apply_set_rating(slug: str, stars: int, allow_save: bool = False) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use snitt_plan_set_rating first",
            }
        try:
            with factory() as client:
                plan = client.plan_set_rating(slug, stars)
                result = client.save_rating(plan, allow_save=True)
                return {"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_plan_add_review",
        description="Dry-run Új értékelés text review (POST /ertekelesek). No POST.",
    )
    def snitt_plan_add_review(slug: str, text: str, spoiler: bool = False) -> dict[str, Any]:
        try:
            with factory() as client:
                plan = client.plan_add_review(slug, text, spoiler=spoiler)
                return {"ok": True, "dry_run": True, "plan": plan.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_apply_review",
        description="POST text review only when allow_save=true, then verify film értékelések list. Default refuses writes.",
    )
    def snitt_apply_review(slug: str, text: str, spoiler: bool = False, allow_save: bool = False) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use snitt_plan_add_review first",
            }
        try:
            with factory() as client:
                plan = client.plan_add_review(slug, text, spoiler=spoiler)
                result = client.save_review(plan, allow_save=True)
                return {"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_plan_delete_watching",
        description="Dry-run delete one filmnézés (POST /filmnezesek/<id> _method=delete). No POST.",
    )
    def snitt_plan_delete_watching(watching_id: int) -> dict[str, Any]:
        try:
            with factory() as client:
                plan = client.plan_delete_watching(watching_id)
                return {"ok": True, "dry_run": True, "plan": plan.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_apply_delete_watching",
        description="Delete filmnézés only when allow_save=true, then verify detail gone. Default refuses writes.",
    )
    def snitt_apply_delete_watching(watching_id: int, allow_save: bool = False) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use snitt_plan_delete_watching first",
            }
        try:
            with factory() as client:
                plan = client.plan_delete_watching(watching_id)
                result = client.save_delete_watching(plan, allow_save=True)
                return {"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_plan_delete_review",
        description="Dry-run delete one értékelés (POST /ertekelesek/<id> _method=delete). No POST.",
    )
    def snitt_plan_delete_review(review_id: int) -> dict[str, Any]:
        try:
            with factory() as client:
                plan = client.plan_delete_review(review_id)
                return {"ok": True, "dry_run": True, "plan": plan.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="snitt_apply_delete_review",
        description="Delete értékelés only when allow_save=true, then verify detail gone. Default refuses writes.",
    )
    def snitt_apply_delete_review(review_id: int, allow_save: bool = False) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use snitt_plan_delete_review first",
            }
        try:
            with factory() as client:
                plan = client.plan_delete_review(review_id)
                result = client.save_delete_review(plan, allow_save=True)
                return {"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    return mcp


def list_tool_names(mcp: FastMCP | None = None) -> list[str]:
    """Return registered tool names for docs/tests.

    :param FastMCP | None mcp: Optional server; creates a default one when omitted.
    :rtype: list[str]
    """
    server = mcp or create_mcp(client_factory=lambda: SnittClient(cookie_header="browser=test"))
    return sorted(tool.name for tool in server._tool_manager.list_tools())


def main() -> None:
    """Run the Snitt MCP server on stdio."""
    create_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()
