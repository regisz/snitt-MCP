"""Thin Google Sheets helpers built on gspread (separate installable package)."""

from snitt_google_sheets.client import GoogleSheetsClient, GoogleSheetsError, spreadsheet_id_from_url
from snitt_google_sheets.session import SheetsAuthError, run_browser_oauth

__all__ = [
    "GoogleSheetsClient",
    "GoogleSheetsError",
    "SheetsAuthError",
    "run_browser_oauth",
    "spreadsheet_id_from_url",
]

__version__ = "0.1.0"
