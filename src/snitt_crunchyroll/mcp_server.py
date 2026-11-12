"""Local stdio MCP server over CrunchyrollClient (thin adapter; gated writes)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from snitt_crunchyroll.client import CrunchyrollClient, CrunchyrollClientError
from snitt_crunchyroll.http import CrunchyrollHttpError
from snitt_crunchyroll.session import CrunchyrollAuthError

ClientFactory = Callable[[], CrunchyrollClient]
_TOOL_ERRORS = (CrunchyrollAuthError, CrunchyrollClientError, CrunchyrollHttpError, OSError, TimeoutError)

TOOL_NAMES: tuple[str, ...] = (
    "crunchyroll_session_status",
    "crunchyroll_search",
    "crunchyroll_get_series",
    "crunchyroll_get_seasons",
    "crunchyroll_get_episodes",
    "crunchyroll_get_watchlist",
    "crunchyroll_plan_watchlist_add",
    "crunchyroll_watchlist_add",
    "crunchyroll_plan_watchlist_remove",
    "crunchyroll_watchlist_remove",
    "crunchyroll_get_custom_lists",
    "crunchyroll_get_custom_list_items",
    "crunchyroll_plan_custom_list_create",
    "crunchyroll_custom_list_create",
    "crunchyroll_plan_custom_list_add_item",
    "crunchyroll_custom_list_add_item",
    "crunchyroll_plan_custom_list_remove_item",
    "crunchyroll_custom_list_remove_item",
    "crunchyroll_plan_mark_watched",
    "crunchyroll_mark_watched",
    "crunchyroll_plan_set_playhead",
    "crunchyroll_set_playhead",
    "crunchyroll_plan_rate_series",
    "crunchyroll_rate_series",
    "crunchyroll_logout",
)

_SHARED_CLIENT: CrunchyrollClient | None = None


def _default_shared_factory() -> ClientFactory:
    def factory() -> CrunchyrollClient:
        global _SHARED_CLIENT
        if _SHARED_CLIENT is None:
            _SHARED_CLIENT = CrunchyrollClient()
        return _SHARED_CLIENT

    return factory


def _error_payload(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": str(exc), "error_type": type(exc).__name__}


def create_mcp(client_factory: ClientFactory | None = None) -> FastMCP:
    """Create a FastMCP server for unofficial Crunchyroll tools.

    Auth: local token file from ``snitt-crunchyroll login-etp-rt`` (never paste
    secrets into chat / mcp.json). Writes require ``allow_save=true``. Sheet is
    the rating source (computed 5★); this MCP only writes to Crunchyroll.

    :param ClientFactory | None client_factory: Optional factory for tests.
    :rtype: FastMCP
    """
    factory = client_factory or _default_shared_factory()
    mcp = FastMCP(
        name="snitt-crunchyroll",
        instructions=(
            "Unofficial Crunchyroll tools (ToS/breakage risk; personal best-effort). "
            "Auth via ~/.config/snitt/crunchyroll.json from snitt-crunchyroll login-etp-rt — "
            "do not put passwords in mcp.json or chat. "
            "Prefer plan_* dry-runs first. Writes need allow_save=true. "
            "Finished series → mark_watched level=series only. "
            "In-progress → episode mark and/or playhead. "
            "Watchlist + custom lists: prefer plan_* then allow_save writes. "
            "Series rating stars 1–5 come from the sheet computed 5★ column."
        ),
    )

    @mcp.tool(
        name="crunchyroll_session_status",
        description="Local Crunchyroll token status (no network). Secrets redacted.",
    )
    def crunchyroll_session_status() -> dict[str, Any]:
        try:
            return factory().session_status()
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_search",
        description="Search Crunchyroll series/movies by text query.",
    )
    def crunchyroll_search(query: str, limit: int = 20) -> dict[str, Any]:
        try:
            return factory().search(query, limit=limit)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_get_series",
        description="Fetch one series by Crunchyroll series id.",
    )
    def crunchyroll_get_series(series_id: str) -> dict[str, Any]:
        try:
            return factory().get_series(series_id)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_get_seasons",
        description="List seasons for a series id.",
    )
    def crunchyroll_get_seasons(series_id: str) -> dict[str, Any]:
        try:
            return factory().get_seasons(series_id)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_get_episodes",
        description="List episodes for a season id.",
    )
    def crunchyroll_get_episodes(season_id: str) -> dict[str, Any]:
        try:
            return factory().get_episodes(season_id)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_get_watchlist",
        description="List the Crunchyroll watchlist (paginated).",
    )
    def crunchyroll_get_watchlist(limit: int = 50, start: int = 0) -> dict[str, Any]:
        try:
            return factory().get_watchlist(limit=limit, start=start)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_plan_watchlist_add",
        description="Dry-run add-to-watchlist preview (no HTTP).",
    )
    def crunchyroll_plan_watchlist_add(content_id: str) -> dict[str, Any]:
        try:
            return factory().plan_watchlist_add(content_id)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_watchlist_add",
        description="Add series/movie to watchlist only when allow_save=true.",
    )
    def crunchyroll_watchlist_add(content_id: str, allow_save: bool = False) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use crunchyroll_plan_watchlist_add first",
            }
        try:
            return factory().watchlist_add(content_id, allow_save=True)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_plan_watchlist_remove",
        description="Dry-run remove-from-watchlist preview (no HTTP).",
    )
    def crunchyroll_plan_watchlist_remove(content_id: str) -> dict[str, Any]:
        try:
            return factory().plan_watchlist_remove(content_id)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_watchlist_remove",
        description="Remove from watchlist only when allow_save=true.",
    )
    def crunchyroll_watchlist_remove(content_id: str, allow_save: bool = False) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use crunchyroll_plan_watchlist_remove first",
            }
        try:
            return factory().watchlist_remove(content_id, allow_save=True)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_get_custom_lists",
        description="List custom (private) Crunchyroll lists.",
    )
    def crunchyroll_get_custom_lists() -> dict[str, Any]:
        try:
            return factory().get_custom_lists()
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_get_custom_list_items",
        description="List items in one custom list.",
    )
    def crunchyroll_get_custom_list_items(
        list_id: str, page: int = 1, page_size: int = 50
    ) -> dict[str, Any]:
        try:
            return factory().get_custom_list_items(list_id, page=page, page_size=page_size)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_plan_custom_list_create",
        description="Dry-run create custom list preview (no HTTP).",
    )
    def crunchyroll_plan_custom_list_create(title: str) -> dict[str, Any]:
        try:
            return factory().plan_custom_list_create(title)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_custom_list_create",
        description="Create custom list only when allow_save=true.",
    )
    def crunchyroll_custom_list_create(title: str, allow_save: bool = False) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use crunchyroll_plan_custom_list_create first",
            }
        try:
            return factory().custom_list_create(title, allow_save=True)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_plan_custom_list_add_item",
        description="Dry-run add item to custom list preview (no HTTP).",
    )
    def crunchyroll_plan_custom_list_add_item(list_id: str, content_id: str) -> dict[str, Any]:
        try:
            return factory().plan_custom_list_add_item(list_id, content_id)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_custom_list_add_item",
        description="Add item to custom list only when allow_save=true.",
    )
    def crunchyroll_custom_list_add_item(
        list_id: str, content_id: str, allow_save: bool = False
    ) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use crunchyroll_plan_custom_list_add_item first",
            }
        try:
            return factory().custom_list_add_item(list_id, content_id, allow_save=True)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_plan_custom_list_remove_item",
        description="Dry-run remove item from custom list preview (no HTTP).",
    )
    def crunchyroll_plan_custom_list_remove_item(list_id: str, content_id: str) -> dict[str, Any]:
        try:
            return factory().plan_custom_list_remove_item(list_id, content_id)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_custom_list_remove_item",
        description="Remove item from custom list only when allow_save=true.",
    )
    def crunchyroll_custom_list_remove_item(
        list_id: str, content_id: str, allow_save: bool = False
    ) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use crunchyroll_plan_custom_list_remove_item first",
            }
        try:
            return factory().custom_list_remove_item(list_id, content_id, allow_save=True)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_plan_mark_watched",
        description="Dry-run mark-as-watched preview (no HTTP). level=series|episode.",
    )
    def crunchyroll_plan_mark_watched(content_id: str, level: str = "series") -> dict[str, Any]:
        try:
            return factory().plan_mark_watched(content_id, level=level)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_mark_watched",
        description="Mark series/episode watched only when allow_save=true. Finished→series; in-progress→episode.",
    )
    def crunchyroll_mark_watched(
        content_id: str,
        allow_save: bool = False,
        level: str = "series",
    ) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use crunchyroll_plan_mark_watched first",
            }
        try:
            return factory().mark_watched(content_id, allow_save=True, level=level)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_plan_set_playhead",
        description="Dry-run playhead update preview for in-progress episodes (no HTTP).",
    )
    def crunchyroll_plan_set_playhead(content_id: str, playhead_seconds: int) -> dict[str, Any]:
        try:
            return factory().plan_set_playhead(content_id, playhead_seconds)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_set_playhead",
        description="Update episode playhead only when allow_save=true (in-progress use).",
    )
    def crunchyroll_set_playhead(
        content_id: str,
        playhead_seconds: int,
        allow_save: bool = False,
    ) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use crunchyroll_plan_set_playhead first",
            }
        try:
            return factory().set_playhead(content_id, playhead_seconds, allow_save=True)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_plan_rate_series",
        description="Dry-run series 1–5 star rating preview. Prefer sheet computed 5★ value.",
    )
    def crunchyroll_plan_rate_series(series_id: str, stars: int) -> dict[str, Any]:
        try:
            return factory().plan_rate_series(series_id, stars)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_rate_series",
        description="Set series rating 1–5 only when allow_save=true. Stars from sheet 5★ column.",
    )
    def crunchyroll_rate_series(series_id: str, stars: int, allow_save: bool = False) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use crunchyroll_plan_rate_series first",
            }
        try:
            return factory().rate_series(series_id, stars, allow_save=True)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="crunchyroll_logout",
        description="Delete local Crunchyroll token file and clear in-memory tokens.",
    )
    def crunchyroll_logout() -> dict[str, Any]:
        try:
            return factory().logout()
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    return mcp


def list_tool_names(mcp: FastMCP | None = None) -> list[str]:
    """Return registered tool names for docs/tests.

    :param FastMCP | None mcp: Optional server; defaults to ``TOOL_NAMES``.
    :rtype: list[str]
    """
    if mcp is None:
        return sorted(TOOL_NAMES)
    return sorted(tool.name for tool in mcp._tool_manager.list_tools())


def main() -> None:
    """Run the Crunchyroll MCP server on stdio."""
    create_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()
