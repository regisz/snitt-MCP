# -*- coding: utf-8 -*-
"""Unit tests for Crunchyroll stdio MCP adapter (mocked HTTP; no live Crunchyroll)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from snitt_crunchyroll.client import CrunchyrollClient
from snitt_crunchyroll.http import HttpResponse, MockHttpTransport
from snitt_crunchyroll.mcp_server import TOOL_NAMES, create_mcp, list_tool_names
from snitt_crunchyroll.session import CrunchyrollTokenStore


def _call(mcp, name: str, arguments: dict) -> dict:
    result = asyncio.run(mcp._tool_manager.call_tool(name, arguments))
    assert isinstance(result, dict)
    return result


def _client(tmp_path: Path, transport: MockHttpTransport) -> CrunchyrollClient:
    store = CrunchyrollTokenStore(
        access_token="access",
        refresh_token="refresh",
        account_id="acc-1",
        expires_at=9e12,
    )
    return CrunchyrollClient(
        token_file=tmp_path / "crunchyroll.json",
        transport=transport,
        create_http=False,
        token_store=store,
    )


def test_registered_tool_names(tmp_path: Path) -> None:
    transport = MockHttpTransport()
    mcp = create_mcp(client_factory=lambda: _client(tmp_path, transport))
    assert list_tool_names(mcp) == sorted(TOOL_NAMES)


def test_session_status_no_http(tmp_path: Path) -> None:
    transport = MockHttpTransport()
    mcp = create_mcp(client_factory=lambda: _client(tmp_path, transport))
    result = _call(mcp, "crunchyroll_session_status", {})
    assert result["ok"] is True
    assert result["authenticated"] is True
    assert result["tokens"]["account_id"] == "acc-1"
    assert transport.calls == []


def test_plan_and_refuse_writes(tmp_path: Path) -> None:
    transport = MockHttpTransport()
    mcp = create_mcp(client_factory=lambda: _client(tmp_path, transport))
    plan = _call(mcp, "crunchyroll_plan_mark_watched", {"content_id": "S1", "level": "series"})
    assert plan["dry_run"] is True
    refused = _call(mcp, "crunchyroll_mark_watched", {"content_id": "S1"})
    assert refused["ok"] is False
    assert "allow_save" in refused["error"]
    rate_plan = _call(mcp, "crunchyroll_plan_rate_series", {"series_id": "S1", "stars": 5})
    assert rate_plan["rating"] == "5s"
    refused_rate = _call(mcp, "crunchyroll_rate_series", {"series_id": "S1", "stars": 5})
    assert refused_rate["ok"] is False
    assert transport.calls == []


def test_mark_watched_via_mcp(tmp_path: Path) -> None:
    transport = MockHttpTransport()
    transport.queue(HttpResponse(status_code=204, text="", json_data=None))
    client = _client(tmp_path, transport)
    mcp = create_mcp(client_factory=lambda: client)
    result = _call(
        mcp,
        "crunchyroll_mark_watched",
        {"content_id": "S1", "allow_save": True, "level": "series"},
    )
    assert result["ok"] is True
    assert result["saved"] is True
    assert "mark_as_watched/S1" in transport.calls[0].url


def test_watchlist_tools_via_mcp(tmp_path: Path) -> None:
    transport = MockHttpTransport()
    transport.queue(HttpResponse(status_code=200, text="{}", json_data={"data": []}))
    client = _client(tmp_path, transport)
    mcp = create_mcp(client_factory=lambda: client)
    plan = _call(mcp, "crunchyroll_plan_watchlist_add", {"content_id": "S1"})
    assert plan["dry_run"] is True
    refused = _call(mcp, "crunchyroll_watchlist_add", {"content_id": "S1"})
    assert refused["ok"] is False
    listed = _call(mcp, "crunchyroll_get_watchlist", {"limit": 5})
    assert listed["ok"] is True
    assert listed["count"] == 0


def test_search_via_mcp(tmp_path: Path) -> None:
    transport = MockHttpTransport()
    payload = {"data": [{"type": "series", "items": [{"id": "X", "title": "Title"}]}]}
    transport.queue(HttpResponse(status_code=200, text=json.dumps(payload), json_data=payload))
    client = _client(tmp_path, transport)
    mcp = create_mcp(client_factory=lambda: client)
    result = _call(mcp, "crunchyroll_search", {"query": "Title"})
    assert result["ok"] is True
    assert result["items"][0]["id"] == "X"
