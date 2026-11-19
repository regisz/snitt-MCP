"""Thin gspread wrapper: open spreadsheet, read rows, gated writes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

import gspread
from gspread import Spreadsheet, Worksheet
from gspread.utils import a1_to_rowcol, rowcol_to_a1

from snitt_google_sheets.session import load_credentials

_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
# How far to search for a same-column format donor when inheriting cell style.
_FORMAT_DONOR_RADIUS = 40


class GoogleSheetsError(RuntimeError):
    """Raised for Sheets client validation or write-gate failures."""


def spreadsheet_id_from_url(url_or_id: str) -> str:
    """Extract a spreadsheet id from a Google Sheets URL, or return a bare id.

    :param str url_or_id: Full Sheets URL or spreadsheet id.
    :rtype: str
    """
    text = url_or_id.strip()
    match = _SHEET_ID_RE.search(text)
    if match:
        return match.group(1)
    path = urlparse(text).path if "://" in text else text
    if "/" not in path.strip("/"):
        return path.strip("/")
    raise GoogleSheetsError(f"Cannot parse spreadsheet id from {url_or_id!r}")


class GoogleSheetsClient:
    """Read/write helper over gspread with an explicit write gate.

    Auth prefers local browser-OAuth refresh token, then optional service account.
    Secrets never come from chat or tool arguments.
    """

    def __init__(
        self,
        credentials_path: Path | None = None,
        *,
        oauth_token_path: Path | None = None,
        oauth_client_secrets_path: Path | None = None,
        interactive: bool = False,
        gspread_client: gspread.Client | None = None,
    ) -> None:
        """Create a client from OAuth/service-account credentials or an injected gspread client.

        :param Path | None credentials_path: Optional service-account JSON (fallback).
        :param Path | None oauth_token_path: Optional stored user token JSON.
        :param Path | None oauth_client_secrets_path: Optional Desktop OAuth client JSON.
        :param bool interactive: Allow browser login when no token (CLI only; MCP keeps False).
        :param gspread.Client | None gspread_client: Optional prebuilt client (tests).
        """
        if gspread_client is not None:
            self._gc = gspread_client
        else:
            creds = load_credentials(
                oauth_token_path_arg=oauth_token_path,
                oauth_client_secrets_path_arg=oauth_client_secrets_path,
                service_account_path_arg=credentials_path,
                interactive=interactive,
            )
            self._gc = gspread.authorize(creds)

    def open_by_key(self, spreadsheet_id: str) -> Spreadsheet:
        """Open a spreadsheet by id.

        :param str spreadsheet_id: Google spreadsheet id from the URL.
        :rtype: Spreadsheet
        """
        return self._gc.open_by_key(spreadsheet_id)

    def open_by_url(self, url: str) -> Spreadsheet:
        """Open a spreadsheet by browser URL.

        :param str url: Full Google Sheets URL.
        :rtype: Spreadsheet
        """
        return self._gc.open_by_url(url)

    def worksheet(self, spreadsheet_id: str, title: str) -> Worksheet:
        """Return a worksheet by spreadsheet id and tab title.

        :param str spreadsheet_id: Spreadsheet id.
        :param str title: Worksheet/tab title.
        :rtype: Worksheet
        """
        return self.open_by_key(spreadsheet_id).worksheet(title)

    def list_worksheet_titles(self, spreadsheet_id_or_url: str) -> list[str]:
        """List worksheet/tab titles for a spreadsheet.

        :param str spreadsheet_id_or_url: Spreadsheet id or Sheets URL.
        :rtype: list[str]
        """
        spreadsheet_id = spreadsheet_id_from_url(spreadsheet_id_or_url)
        book = self.open_by_key(spreadsheet_id)
        return [worksheet.title for worksheet in book.worksheets()]

    def read_all_records(self, spreadsheet_id_or_url: str, worksheet_title: str) -> list[dict[str, Any]]:
        """Read all rows as dicts (header row required).

        :param str spreadsheet_id_or_url: Spreadsheet id or Sheets URL.
        :param str worksheet_title: Tab title.
        :rtype: list[dict[str, Any]]
        """
        spreadsheet_id = spreadsheet_id_from_url(spreadsheet_id_or_url)
        return self.worksheet(spreadsheet_id, worksheet_title).get_all_records()

    def append_rows(
        self,
        spreadsheet_id_or_url: str,
        worksheet_title: str,
        rows: Sequence[Sequence[Any]],
        *,
        allow_write: bool,
    ) -> dict[str, Any]:
        """Append rows only when ``allow_write`` is True.

        Writes plain values only (values.append / USER_ENTERED). Never sends
        ``userEnteredFormat``, ``textFormat``, or ``fontFamily``.

        :param str spreadsheet_id_or_url: Spreadsheet id or Sheets URL.
        :param str worksheet_title: Tab title.
        :param Sequence[Sequence[Any]] rows: Values to append.
        :param bool allow_write: Explicit write gate; False refuses the call.
        :rtype: dict[str, Any]
        """
        if not allow_write:
            raise GoogleSheetsError("Refusing write: pass allow_write=True only with explicit permission.")
        if not rows:
            return {"ok": True, "appended": 0}
        spreadsheet_id = spreadsheet_id_from_url(spreadsheet_id_or_url)
        sheet = self.worksheet(spreadsheet_id, worksheet_title)
        sheet.append_rows(list(rows), value_input_option="USER_ENTERED")
        return {"ok": True, "appended": len(rows), "spreadsheet_id": spreadsheet_id}

    def update_cells(
        self,
        spreadsheet_id_or_url: str,
        worksheet_title: str,
        cells: Sequence[Mapping[str, Any]],
        *,
        allow_write: bool,
    ) -> dict[str, Any]:
        """Update individual cells with plain values only when ``allow_write`` is True.

        Never sends ``userEnteredFormat`` / ``textFormat`` / ``fontFamily`` with the
        value write. After writing, cells that still lack user-entered text format
        inherit formatting from the nearest same-column neighbour (PASTE_FORMAT),
        so e.g. Vélemény text matches neighbouring Times/serif rows.

        Each item is either ``{"row": int, "col": int, "value": ...}`` (1-based) or
        ``{"a1": "L278", "value": ...}``.

        :param str spreadsheet_id_or_url: Spreadsheet id or Sheets URL.
        :param str worksheet_title: Tab title.
        :param Sequence[Mapping[str, Any]] cells: Cells to update.
        :param bool allow_write: Explicit write gate; False refuses the call.
        :rtype: dict[str, Any]
        """
        if not allow_write:
            raise GoogleSheetsError("Refusing write: pass allow_write=True only with explicit permission.")
        if not cells:
            return {"ok": True, "updated": 0}
        spreadsheet_id = spreadsheet_id_from_url(spreadsheet_id_or_url)
        book = self.open_by_key(spreadsheet_id)
        sheet = book.worksheet(worksheet_title)
        parsed: list[tuple[int, int, Any]] = []
        for item in cells:
            if "a1" in item:
                row, col = a1_to_rowcol(str(item["a1"]))
                parsed.append((row, col, item.get("value")))
            else:
                row = int(item["row"])
                col = int(item["col"])
                if row < 1 or col < 1:
                    raise GoogleSheetsError("row and col must be 1-based positive integers.")
                parsed.append((row, col, item.get("value")))
        # Plain values only — no CellFormat / fontFamily in the values write.
        gspread_cells = [
            gspread.Cell(row, col, "" if value is None else value) for row, col, value in parsed
        ]
        sheet.update_cells(gspread_cells, value_input_option="USER_ENTERED")
        inherited = self._inherit_formats_for_cells(book, sheet, [(row, col) for row, col, _ in parsed])
        return {
            "ok": True,
            "updated": len(parsed),
            "format_inherited": inherited,
            "spreadsheet_id": spreadsheet_id,
        }

    def _inherit_formats_for_cells(
        self,
        book: Spreadsheet,
        sheet: Worksheet,
        targets: Sequence[tuple[int, int]],
    ) -> int:
        """Copy PASTE_FORMAT onto targets that lack userEntered text format.

        :param Spreadsheet book: Open spreadsheet.
        :param Worksheet sheet: Target worksheet.
        :param Sequence[tuple[int, int]] targets: 1-based (row, col) pairs.
        :rtype: int
        """
        if not targets:
            return 0
        by_col: dict[int, set[int]] = {}
        for row, col in targets:
            by_col.setdefault(col, set()).add(row)
        ranges: list[str] = []
        for col, rows in by_col.items():
            lo = max(1, min(rows) - _FORMAT_DONOR_RADIUS)
            hi = max(rows) + _FORMAT_DONOR_RADIUS
            start = rowcol_to_a1(lo, col)
            end = rowcol_to_a1(hi, col)
            ranges.append(f"'{sheet.title}'!{start}:{end}")
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{book.id}"
        params = {
            "ranges": ranges,
            "includeGridData": "true",
            "fields": "sheets(data(startRow,startColumn,rowData(values(userEnteredFormat/textFormat))))",
        }
        payload = book.client.request("get", url, params=params).json()
        sheets = payload.get("sheets") or []
        if not sheets:
            return 0
        # col -> {row: has textFormat}
        has_format: dict[int, dict[int, bool]] = {col: {} for col in by_col}
        for block in sheets[0].get("data") or []:
            start_row = int(block.get("startRow") or 0)
            start_col = int(block.get("startColumn") or 0)
            col = start_col + 1
            if col not in has_format:
                continue
            for offset, row_data in enumerate(block.get("rowData") or []):
                row = start_row + offset + 1
                values = row_data.get("values") or []
                cell = values[0] if values else {}
                text_format = ((cell.get("userEnteredFormat") or {}).get("textFormat")) or {}
                has_format[col][row] = bool(text_format.get("fontFamily") or text_format)
        requests: list[dict[str, Any]] = []
        for col, rows in by_col.items():
            flags = has_format.get(col) or {}
            for row in rows:
                if flags.get(row):
                    continue
                donor = _nearest_format_donor(flags, row)
                if donor is None:
                    continue
                requests.append(
                    {
                        "copyPaste": {
                            "source": {
                                "sheetId": sheet.id,
                                "startRowIndex": donor - 1,
                                "endRowIndex": donor,
                                "startColumnIndex": col - 1,
                                "endColumnIndex": col,
                            },
                            "destination": {
                                "sheetId": sheet.id,
                                "startRowIndex": row - 1,
                                "endRowIndex": row,
                                "startColumnIndex": col - 1,
                                "endColumnIndex": col,
                            },
                            "pasteType": "PASTE_FORMAT",
                            "pasteOrientation": "NORMAL",
                        }
                    }
                )
        if not requests:
            return 0
        book.batch_update({"requests": requests})
        return len(requests)


def _nearest_format_donor(flags: Mapping[int, bool], row: int) -> int | None:
    """Return nearest row with format flag True, or None.

    :param Mapping[int, bool] flags: row -> has user-entered text format.
    :param int row: Target 1-based row.
    :rtype: int | None
    """
    for delta in range(1, _FORMAT_DONOR_RADIUS + 1):
        above = row - delta
        if flags.get(above):
            return above
        below = row + delta
        if flags.get(below):
            return below
    return None


__all__ = ["GoogleSheetsClient", "GoogleSheetsError", "spreadsheet_id_from_url"]
