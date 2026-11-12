"""Compatibility shim: intended tool names now live on the real MCP server."""

from __future__ import annotations

from typing import Any

from snitt_client.mcp_server import TOOL_NAMES


def list_intended_tools() -> list[dict[str, Any]]:
    """Return tool name descriptors for documentation/tests.

    :rtype: list[dict[str, Any]]
    """
    return [{"name": name} for name in TOOL_NAMES]
