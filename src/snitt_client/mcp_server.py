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
    "snitt_plan_add_tag",
    "snitt_plan_add_genre",
    "snitt_plan_add_description",
    "snitt_apply_tag",
    "snitt_apply_genre",
    "snitt_apply_description",
    "snitt_verify_sheet",
    "snitt_list_watchings",
    "snitt_series_watch_span",
    "snitt_list_ratings",
    "snitt_fetch_rating",
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
