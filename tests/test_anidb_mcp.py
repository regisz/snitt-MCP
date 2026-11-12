# -*- coding: utf-8 -*-
"""Unit tests for AniDB stdio MCP adapter (mocked UDP; no live AniDB)."""

from __future__ import annotations

import asyncio

from snitt_anidb.client import AniDBClient
from snitt_anidb.mcp_server import TOOL_NAMES, create_mcp, list_tool_names
from snitt_anidb.rate_limit import FloodRateLimiter
from snitt_anidb.session import AniDBCredentials
from snitt_anidb.transport import MockUdpTransport


def _creds() -> AniDBCredentials:
    return AniDBCredentials(user="testuser", password="secret", client="snittanidb", clientver=1)


def _factory(transport: MockUdpTransport):
    limiter = FloodRateLimiter(sleeper=lambda _s: None)

    def factory() -> AniDBClient:
        return AniDBClient(
            credentials=_creds(),
            transport=transport,
            rate_limiter=limiter,
            create_socket=False,
        )

    return factory


def _call(mcp, name: str, arguments: dict) -> dict:
    result = asyncio.run(mcp._tool_manager.call_tool(name, arguments))
    assert isinstance(result, dict)
    return result


def test_registered_tool_names() -> None:
    transport = MockUdpTransport()
    mcp = create_mcp(client_factory=_factory(transport))
    assert list_tool_names(mcp) == sorted(TOOL_NAMES)


def test_session_status_no_udp() -> None:
    transport = MockUdpTransport()
    mcp = create_mcp(client_factory=_factory(transport))
    result = _call(mcp, "anidb_session_status", {})
    assert result["ok"] is True
    assert result["authenticated"] is False
    assert result["credentials"]["user"] == "testuser"
    assert result["credentials"]["password"] == "***"
    assert transport.sent == []


def test_plan_and_refuse_write() -> None:
    transport = MockUdpTransport()
    mcp = create_mcp(client_factory=_factory(transport))
    plan = _call(mcp, "anidb_plan_mark_watched", {"aid": 42, "epno": 1})
    assert plan["ok"] is True
    assert plan["dry_run"] is True
    refused = _call(mcp, "anidb_mark_watched", {"aid": 42, "epno": 1})
    assert refused["ok"] is False
    assert "allow_save" in refused["error"]
    assert transport.sent == []


def test_lookup_via_mcp() -> None:
    transport = MockUdpTransport()
    transport.queue(
        "200 sess LOGIN ACCEPTED",
        "230 ANIME\n42|1|1|0|0|0|0|0|0|0|2020|TV|Title|||||||",
    )
    # shared factory must return SAME client so session persists — recreate pattern used by sheets tests
    limiter = FloodRateLimiter(sleeper=lambda _s: None)
    client = AniDBClient(
        credentials=_creds(),
        transport=transport,
        rate_limiter=limiter,
        create_socket=False,
    )
    mcp = create_mcp(client_factory=lambda: client)
    result = _call(mcp, "anidb_lookup_anime", {"aid": 42})
    assert result["ok"] is True
    assert result["anime"]["aid"] == "42"
    assert result["anime"]["romaji"] == "Title"


def test_reset_ban_latch_tool() -> None:
    transport = MockUdpTransport()
    transport.queue("504 CLIENT BANNED - x")
    limiter = FloodRateLimiter(sleeper=lambda _s: None)
    client = AniDBClient(
        credentials=_creds(),
        transport=transport,
        rate_limiter=limiter,
        create_socket=False,
    )
    mcp = create_mcp(client_factory=lambda: client)
    failed = _call(mcp, "anidb_lookup_anime", {"aid": 1})
    assert failed["ok"] is False
    assert failed["error_type"] == "AniDBBannedError"
    reset = _call(mcp, "anidb_reset_ban_latch", {})
    assert reset["ok"] is True
    assert reset["banned"] is False


def test_set_password_tool_does_not_echo() -> None:
    limiter = FloodRateLimiter(sleeper=lambda _s: None)
    client = AniDBClient(
        credentials=AniDBCredentials(user="testuser", password="", client="snittanidb", clientver=1),
        transport=MockUdpTransport(),
        rate_limiter=limiter,
        create_socket=False,
    )
    mcp = create_mcp(client_factory=lambda: client)
    missing = _call(mcp, "anidb_lookup_anime", {"aid": 1})
    assert missing["ok"] is False
    assert missing["error_type"] == "AniDBAuthError"
    assert "anidb_set_password" in missing["error"]
    secret = "super-secret-pass"
    result = _call(mcp, "anidb_set_password", {"password": secret})
    assert result == {"ok": True, "ready": True}
    assert secret not in str(result)
    status = _call(mcp, "anidb_session_status", {})
    assert status["password_in_memory"] is True
    assert secret not in str(status)
    cleared = _call(mcp, "anidb_clear_credentials", {})
    assert cleared["ok"] is True
    assert cleared["password_in_memory"] is False
    assert client.password_in_memory is False
