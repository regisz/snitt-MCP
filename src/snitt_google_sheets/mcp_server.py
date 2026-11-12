"""Local stdio MCP server over GoogleSheetsClient (thin adapter)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from snitt_google_sheets.client import GoogleSheetsClient, GoogleSheetsError
from snitt_google_sheets.session import SheetsAuthError

ClientFactory = Callable[[], GoogleSheetsClient]
_TOOL_ERRORS = (SheetsAuthError, GoogleSheetsError, OSError)

TOOL_NAMES: tuple[str, ...] = (
    "sheets_list_worksheets",
    "sheets_read_records",
    "sheets_append_rows",
)


def _client_factory(credentials_path: Path | None = None) -> ClientFactory:
    def factory() -> GoogleSheetsClient:
        return GoogleSheetsClient(credentials_path=credentials_path)

    return factory


def _error_payload(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": str(exc), "error_type": type(exc).__name__}


def create_mcp(
    client_factory: ClientFactory | None = None,
    credentials_path: Path | None = None,
) -> FastMCP:
    """Create a FastMCP server for Google Sheets read/gated write.

    Credentials come from ENV/local JSON via GoogleSheetsClient (never tool args).

    :param ClientFactory | None client_factory: Optional factory for tests.
    :param Path | None credentials_path: Optional service-account JSON path.
    :rtype: FastMCP
    """
    factory = client_factory or _client_factory(credentials_path)
    mcp = FastMCP(
        name="snitt-sheets",
        instructions=(
            "Google Sheets tools for Balázs anime/watch tables (direct API via gspread; no CSV export). "
            "Prefer sheets_read_records before any write. "
            "Writes require allow_write=true only with explicit permission. "
            "Auth: browser OAuth token at ~/.config/snitt/google-oauth-token.json "
            "(run snitt-sheets-auth once); optional service-account fallback. "
            "Snitt.hu auth is separate cookie/session — not Google browser OAuth."
        ),
    )

    @mcp.tool(
        name="sheets_list_worksheets",
        description="List worksheet/tab titles for a Google Spreadsheet (id or URL).",
    )
    def sheets_list_worksheets(spreadsheet: str) -> dict[str, Any]:
        try:
            client = factory()
            titles = client.list_worksheet_titles(spreadsheet)
            return {"ok": True, "worksheets": titles, "count": len(titles)}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)
        except Exception as exc:  # noqa: BLE001 — surface gspread/API failures to the agent
            return _error_payload(exc)

    @mcp.tool(
        name="sheets_read_records",
        description="Read all records from a worksheet (header row required). spreadsheet = id or URL.",
    )
    def sheets_read_records(spreadsheet: str, worksheet_title: str) -> dict[str, Any]:
        try:
            client = factory()
            rows = client.read_all_records(spreadsheet, worksheet_title)
            return {"ok": True, "count": len(rows), "records": rows}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)
        except Exception as exc:  # noqa: BLE001
            return _error_payload(exc)

    @mcp.tool(
        name="sheets_append_rows",
        description="Append rows only when allow_write=true. rows is a list of row value lists.",
    )
    def sheets_append_rows(
        spreadsheet: str,
        worksheet_title: str,
        rows: list[list[Any]],
        allow_write: bool = False,
    ) -> dict[str, Any]:
        if not allow_write:
            return {
                "ok": False,
                "error": "Refusing write without allow_write=true",
                "dry_run_hint": "Use sheets_read_records first; only append after explicit permission",
            }
        try:
            client = factory()
            result = client.append_rows(spreadsheet, worksheet_title, rows, allow_write=True)
            return {"ok": True, **result}
        except _TOOL_ERRORS as exc:
            return _error_payload(exc)
        except Exception as exc:  # noqa: BLE001
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
    """Run the Sheets MCP server on stdio."""
    create_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()
