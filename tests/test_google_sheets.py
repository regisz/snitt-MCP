# -*- coding: utf-8 -*-
"""Unit tests for the gspread thin wrapper (no live Google API)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from snitt_google_sheets.client import GoogleSheetsClient, GoogleSheetsError, spreadsheet_id_from_url


def test_spreadsheet_id_from_url_helpers() -> None:
    assert spreadsheet_id_from_url("https://docs.google.com/spreadsheets/d/abc-123/edit") == "abc-123"
    assert spreadsheet_id_from_url("abc-123") == "abc-123"


def test_read_all_records_delegates_to_worksheet() -> None:
    worksheet = MagicMock()
    worksheet.get_all_records.return_value = [{"Title": "Demo", "Year": 2024}]
    spreadsheet = MagicMock()
    spreadsheet.worksheet.return_value = worksheet
    gc = MagicMock()
    gc.open_by_key.return_value = spreadsheet
    client = GoogleSheetsClient(gspread_client=gc)
    rows = client.read_all_records("sheet-id", "Anime")
    assert rows == [{"Title": "Demo", "Year": 2024}]
    gc.open_by_key.assert_called_once_with("sheet-id")
    spreadsheet.worksheet.assert_called_once_with("Anime")


def test_append_rows_refuses_without_allow_write() -> None:
    client = GoogleSheetsClient(gspread_client=MagicMock())
    with pytest.raises(GoogleSheetsError, match="allow_write"):
        client.append_rows("sheet-id", "Anime", [["x"]], allow_write=False)


def test_append_rows_writes_when_allowed() -> None:
    worksheet = MagicMock()
    spreadsheet = MagicMock()
    spreadsheet.worksheet.return_value = worksheet
    gc = MagicMock()
    gc.open_by_key.return_value = spreadsheet
    client = GoogleSheetsClient(gspread_client=gc)
    result = client.append_rows("sheet-id", "Anime", [["A", 1], ["B", 2]], allow_write=True)
    assert result == {"ok": True, "appended": 2, "spreadsheet_id": "sheet-id"}
    worksheet.append_rows.assert_called_once()
