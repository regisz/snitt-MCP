"""Local stdio MCP server over AniDBClient (thin adapter; gated writes)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from snitt_anidb.client import AniDBBannedError, AniDBClient, AniDBClientError
from snitt_anidb.session import AniDBAuthError

ClientFactory = Callable[[], AniDBClient]
_TOOL_ERRORS = (AniDBAuthError, AniDBClientError, AniDBBannedError, OSError, TimeoutError)

TOOL_NAMES: tuple[str, ...] = (
    "anidb_session_status",
    "anidb_set_password",
    "anidb_clear_credentials",
    "anidb_lookup_anime",
    "anidb_mylist_get",
    "anidb_mylist_stats",
    "anidb_plan_mark_watched",
    "anidb_mark_watched",
    "anidb_plan_vote",
    "anidb_vote",
    "anidb_reset_ban_latch",
)

# One shared client per MCP process so rate-limit + session + ban latch persist.
_SHARED_CLIENT: AniDBClient | None = None


def _default_shared_factory() -> ClientFactory:
    def factory() -> AniDBClient:
        global _SHARED_CLIENT
        if _SHARED_CLIENT is None:
            _SHARED_CLIENT = AniDBClient()
        return _SHARED_CLIENT

    return factory


def _error_payload(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": str(exc), "error_type": type(exc).__name__}


def create_mcp(client_factory: ClientFactory | None = None) -> FastMCP:
    """Create a FastMCP server for AniDB session / mylist tools.

    Non-secret identity comes from ENV/local config. Website password is set
    once via ``anidb_set_password`` into shared process memory (never disk;
    tool result never echoes it). ``ANIDB_PASS`` remains an optional fallback.
    Writes require ``allow_save=true``. Prefer plan_* dry-runs first.

    :param ClientFactory | None client_factory: Optional factory for tests.
    :rtype: FastMCP
    """
    factory = client_factory or _default_shared_factory()
    mcp = FastMCP(
        name="snitt-anidb",
        instructions=(
            "AniDB UDP tools (paced client; IP ban risk if flooded). "
            "Prefer anidb_session_status and dry-run anidb_plan_mark_watched / anidb_plan_vote first. "
            "Before AUTH tools: call anidb_set_password once (password stays in MCP process "
            "memory only; result is ok/ready — never echoed). Optional anidb_clear_credentials "
            "clears password + session. "
            "Identity: ANIDB_USER/CLIENT/CLIENTVER or ~/.config/snitt/anidb.cfg — omit ANIDB_PASS "
            "from mcp.json. Writes require allow_save=true only with explicit permission. "
            "Permanent Vote is anidb_vote stars 1–10 (UDP VOTE type=1, value=stars*100). "
            "Client name must be registered with AniDB. "
            "On ban, tools stop until anidb_reset_ban_latch after the ban window."
        ),
    )

    @mcp.tool(
        name="anidb_session_status",
        description="Local AniDB session/rate-limit/ban status (no UDP). Redacted credentials only.",
    )
    def anidb_session_status() -> dict[str, Any]:
        try:
            return factory().session_status()
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="anidb_set_password",
        description=(
            "Store AniDB website password in this MCP process memory only (never disk). "
            "Result is ok/ready only — password is never echoed. Call once before AUTH tools."
        ),
    )
    def anidb_set_password(password: str) -> dict[str, Any]:
        try:
            result = factory().set_password(password)
            # never include password (or any echo) in the tool result
            return {"ok": bool(result.get("ok")), "ready": bool(result.get("ready"))}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="anidb_clear_credentials",
        description="Clear in-memory AniDB password and session (local logout; no password echo).",
    )
    def anidb_clear_credentials() -> dict[str, Any]:
        try:
            return factory().clear_credentials()
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="anidb_lookup_anime",
        description="Look up one anime by aid or exact aname (ANIME; paced). No fuzzy search.",
    )
    def anidb_lookup_anime(aid: int | None = None, aname: str | None = None) -> dict[str, Any]:
        try:
            return factory().lookup_anime(aid=aid, aname=aname)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="anidb_mylist_get",
        description="Bounded MYLIST get by lid, fid, aid, or exact aname (+ optional epno). Not a full dump.",
    )
    def anidb_mylist_get(
        lid: int | None = None,
        fid: int | None = None,
        aid: int | None = None,
        aname: str | None = None,
        epno: int | None = None,
    ) -> dict[str, Any]:
        try:
            return factory().mylist_get(lid=lid, fid=fid, aid=aid, aname=aname, epno=epno)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="anidb_mylist_stats",
        description="MYLISTSTATS summary (one paced packet).",
    )
    def anidb_mylist_stats() -> dict[str, Any]:
        try:
            return factory().mylist_stats()
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="anidb_plan_mark_watched",
        description="Dry-run MYLISTADD preview for mark watched (no UDP).",
    )
    def anidb_plan_mark_watched(
        aid: int,
        epno: int,
        viewed: bool = True,
        state: int = 1,
        edit: bool = False,
        lid: int | None = None,
    ) -> dict[str, Any]:
        try:
            return factory().plan_mark_watched(
                aid=aid, epno=epno, viewed=viewed, state=state, edit=edit, lid=lid
            )
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="anidb_mark_watched",
        description="MYLISTADD mark watched only when allow_save=true. Default refuses writes.",
    )
    def anidb_mark_watched(
        aid: int,
        epno: int,
        allow_save: bool = False,
        viewed: bool = True,
        state: int = 1,
        edit: bool = False,
        lid: int | None = None,
    ) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use anidb_plan_mark_watched first",
            }
        try:
            return factory().mark_watched(
                aid=aid,
                epno=epno,
                allow_save=True,
                viewed=viewed,
                state=state,
                edit=edit,
                lid=lid,
            )
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="anidb_plan_vote",
        description=(
            "Dry-run VOTE preview for Permanent/Temporary Vote (no UDP). "
            "stars=1–10 maps to value=stars*100; temporary=false is Permanent Vote."
        ),
    )
    def anidb_plan_vote(aid: int, stars: float, temporary: bool = False) -> dict[str, Any]:
        try:
            return factory().plan_vote(aid=aid, stars=stars, temporary=temporary)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="anidb_vote",
        description=(
            "VOTE anime score only when allow_save=true. stars=1–10 (Permanent Vote by default; "
            "temporary=true for Temporary Vote). Default refuses writes."
        ),
    )
    def anidb_vote(
        aid: int,
        stars: float,
        allow_save: bool = False,
        temporary: bool = False,
    ) -> dict[str, Any]:
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=true",
                "dry_run_hint": "Use anidb_plan_vote first",
            }
        try:
            return factory().vote(aid=aid, stars=stars, allow_save=True, temporary=temporary)
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)

    @mcp.tool(
        name="anidb_reset_ban_latch",
        description="Clear local ban latch only (no UDP). Use after ban window; do not spam.",
    )
    def anidb_reset_ban_latch() -> dict[str, Any]:
        try:
            return factory().reset_ban_latch()
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
    """Run the AniDB MCP server on stdio."""
    create_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()
