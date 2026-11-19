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
    assert worksheet.append_rows.call_args.kwargs["value_input_option"] == "USER_ENTERED"


def test_update_cells_refuses_without_allow_write() -> None:
    client = GoogleSheetsClient(gspread_client=MagicMock())
    with pytest.raises(GoogleSheetsError, match="allow_write"):
        client.update_cells("sheet-id", "Anime", [{"row": 2, "col": 3, "value": "x"}], allow_write=False)


def test_update_cells_writes_plain_values_and_inherits_format() -> None:
    worksheet = MagicMock()
    worksheet.id = 93001
    worksheet.title = "Anime"
    spreadsheet = MagicMock()
    spreadsheet.id = "sheet-id"
    spreadsheet.worksheet.return_value = worksheet
    # Column C rows 1..: only row 3 has Times; target row 2 needs inherit from row 3.
    spreadsheet.client.request.return_value.json.return_value = {
        "sheets": [
            {
                "data": [
                    {
                        "startRow": 0,
                        "startColumn": 2,
                        "rowData": [
                            {"values": [{}]},
                            {"values": [{}]},
                            {
                                "values": [
                                    {
                                        "userEnteredFormat": {
                                            "textFormat": {"fontFamily": "Times New Roman", "fontSize": 10}
                                        }
                                    }
                                ]
                            },
                        ],
                    }
                ]
            }
        ]
    }
    gc = MagicMock()
    gc.open_by_key.return_value = spreadsheet
    client = GoogleSheetsClient(gspread_client=gc)
    result = client.update_cells(
        "sheet-id",
        "Anime",
        [{"row": 2, "col": 3, "value": "vélemény szöveg"}, {"a1": "C4", "value": "másik"}],
        allow_write=True,
    )
    assert result["ok"] is True
    assert result["updated"] == 2
    assert result["format_inherited"] == 2
    worksheet.update_cells.assert_called_once()
    assert worksheet.update_cells.call_args.kwargs["value_input_option"] == "USER_ENTERED"
    written = worksheet.update_cells.call_args.args[0]
    assert all(not hasattr(cell, "userEnteredFormat") for cell in written)
    assert written[0].value == "vélemény szöveg"
    body = spreadsheet.batch_update.call_args.args[0]
    assert "requests" in body
    for req in body["requests"]:
        assert "copyPaste" in req
        assert req["copyPaste"]["pasteType"] == "PASTE_FORMAT"
        assert "userEnteredFormat" not in req
        assert "fontFamily" not in str(req)
