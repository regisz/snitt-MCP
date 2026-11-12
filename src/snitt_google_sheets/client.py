"""Thin gspread wrapper: open spreadsheet, read rows, gated writes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse

import gspread
from gspread import Spreadsheet, Worksheet

from snitt_google_sheets.session import load_credentials

_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


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


__all__ = ["GoogleSheetsClient", "GoogleSheetsError", "spreadsheet_id_from_url"]
