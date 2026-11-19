# -*- coding: utf-8 -*-
"""Unit tests for the Snitt stdio MCP adapter (fixture HTTP only; no live POST)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from snitt_client.client import SnittClient
from snitt_client.mcp_server import TOOL_NAMES, create_mcp, list_tool_names

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_factory() -> SnittClient:
    html = (FIXTURES / "sheet_nyarido_fragment.html").read_text(encoding="utf-8")
    genres = (FIXTURES / "genres_thriller.json").read_text(encoding="utf-8")
    open_tags = json.dumps([{"id": 42, "name": "politika"}])

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            raise AssertionError(f"Unexpected live POST in MCP unit test: {path}")
        if path == "/filmek/nyarido-szamitas":
            return httpx.Response(200, text=html)
        if path == "/api/genres_with_names.json":
            return httpx.Response(200, text=genres, headers={"content-type": "application/json"})
        if path == "/api/open_tags_with_names.json":
            return httpx.Response(200, text=open_tags, headers={"content-type": "application/json"})
        return httpx.Response(404, text="missing")

    return SnittClient(cookie_header="browser=test", transport=httpx.MockTransport(handler))


def _call(mcp, name: str, arguments: dict) -> dict:
    result = asyncio.run(mcp._tool_manager.call_tool(name, arguments))
    assert isinstance(result, dict)
    return result


def test_registered_tool_names_match_contract() -> None:
    names = list_tool_names(create_mcp(client_factory=_fixture_factory))
    assert set(TOOL_NAMES).issubset(set(names))
    assert names == sorted(TOOL_NAMES)


def test_fetch_and_plan_genre_via_mcp_tools() -> None:
    mcp = create_mcp(client_factory=_fixture_factory)
    fetched = _call(mcp, "snitt_fetch_sheet", {"slug": "nyarido-szamitas"})
    assert fetched["ok"] is True
    assert fetched["sheet"]["slug"] == "nyarido-szamitas"
    assert fetched["sheet"]["csrf_token_present"] is True

    plan = _call(mcp, "snitt_plan_add_genre", {"slug": "nyarido-szamitas", "name": "thriller"})
    assert plan["ok"] is True
    assert plan["dry_run"] is True
    assert plan["plan"]["fields"]["tagging[tag_id]"] == "84"
    assert plan["plan"]["fields"]["commit"] == "Hozzáadás"


def test_apply_tools_refuse_without_allow_save() -> None:
    mcp = create_mcp(client_factory=_fixture_factory)
    for tool_name, args in (
        ("snitt_apply_tag", {"slug": "nyarido-szamitas", "name": "politika"}),
        ("snitt_apply_genre", {"slug": "nyarido-szamitas", "name": "thriller"}),
        ("snitt_apply_description", {"slug": "nyarido-szamitas", "text": "példa"}),
        ("snitt_apply_mark_watched", {"slug": "nyarido-szamitas"}),
        ("snitt_apply_favorite", {"slug": "nyarido-szamitas", "want_favorite": True}),
        ("snitt_apply_set_rating", {"slug": "nyarido-szamitas", "stars": 7}),
        ("snitt_apply_review", {"slug": "nyarido-szamitas", "text": "példa"}),
        ("snitt_apply_delete_watching", {"watching_id": 1}),
        ("snitt_apply_delete_review", {"review_id": 1}),
    ):
        result = _call(mcp, tool_name, args)
        assert result["ok"] is False
        assert "allow_save" in result["error"]


def test_verify_sheet_checks_expected_tag() -> None:
    mcp = create_mcp(client_factory=_fixture_factory)
    present = _call(mcp, "snitt_verify_sheet", {"slug": "nyarido-szamitas", "expected_tag": "anime"})
    assert present["ok"] is True
    assert present["expected_tag_present"] is True

    missing = _call(mcp, "snitt_verify_sheet", {"slug": "nyarido-szamitas", "expected_tag": "thriller"})
    assert missing["ok"] is False
    assert missing["expected_tag_present"] is False


def test_session_not_accepted_as_tool_argument() -> None:
    mcp = create_mcp(client_factory=_fixture_factory)
    tool = mcp._tool_manager.get_tool("snitt_fetch_sheet")
    assert tool is not None
    props = tool.parameters.get("properties", {})
    assert "cookie" not in props
    assert "session" not in props
    assert "SNITT_COOKIE" not in props
