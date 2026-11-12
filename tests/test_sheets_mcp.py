# -*- coding: utf-8 -*-
"""Unit tests for the Sheets stdio MCP adapter (mocked gspread; no live Google)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from snitt_google_sheets.client import GoogleSheetsClient, spreadsheet_id_from_url
from snitt_google_sheets.mcp_server import TOOL_NAMES, create_mcp, list_tool_names


def _factory() -> GoogleSheetsClient:
    worksheet = MagicMock()
    worksheet.get_all_records.return_value = [{"Title": "Demo", "Started": "2024-01-01"}]
    worksheet.title = "Anime"
    spreadsheet = MagicMock()
    spreadsheet.worksheet.return_value = worksheet
    spreadsheet.worksheets.return_value = [worksheet]
    gc = MagicMock()
    gc.open_by_key.return_value = spreadsheet
    return GoogleSheetsClient(gspread_client=gc)


def _call(mcp, name: str, arguments: dict) -> dict:
    result = asyncio.run(mcp._tool_manager.call_tool(name, arguments))
    assert isinstance(result, dict)
    return result


def test_spreadsheet_id_from_url() -> None:
    url = "https://docs.google.com/spreadsheets/d/abcXYZ123/edit#gid=0"
    assert spreadsheet_id_from_url(url) == "abcXYZ123"
    assert spreadsheet_id_from_url("abcXYZ123") == "abcXYZ123"


def test_registered_tool_names() -> None:
    mcp = create_mcp(client_factory=_factory)
    assert list_tool_names(mcp) == sorted(TOOL_NAMES)


def test_read_and_list_via_mcp() -> None:
    mcp = create_mcp(client_factory=_factory)
    listed = _call(mcp, "sheets_list_worksheets", {"spreadsheet": "https://docs.google.com/spreadsheets/d/abcXYZ123/edit"})
    assert listed["ok"] is True
    assert listed["worksheets"] == ["Anime"]
    rows = _call(mcp, "sheets_read_records", {"spreadsheet": "abcXYZ123", "worksheet_title": "Anime"})
    assert rows["ok"] is True
    assert rows["count"] == 1
    assert rows["records"][0]["Title"] == "Demo"


def test_append_refuses_without_allow_write() -> None:
    mcp = create_mcp(client_factory=_factory)
    result = _call(
        mcp,
        "sheets_append_rows",
        {"spreadsheet": "abcXYZ123", "worksheet_title": "Anime", "rows": [["x"]]},
    )
    assert result["ok"] is False
    assert "allow_write" in result["error"]
