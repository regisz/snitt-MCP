"""Thin interactive AniDB CLI helpers (getpass into process memory)."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from snitt_anidb.client import AniDBClient
from snitt_anidb.session import AniDBAuthError


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI argument parser.

    :rtype: argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog="snitt-anidb",
        description=(
            "AniDB helpers. Password is prompted via getpass into process memory "
            "(not written to disk). Prefer omitting ANIDB_PASS from env/mcp.json."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("session-status", help="Print local session status (no UDP)")
    return parser


def _print_json(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def run_session_status(client: AniDBClient) -> int:
    """Ensure password (getpass if missing) then print redacted session status.

    :param AniDBClient client: Interactive client.
    :rtype: int
    """
    status = client.session_status()
    if not status.get("password_in_memory"):
        creds = status.get("credentials") or {}
        if not creds.get("password_set"):
            try:
                client.prompt_password()
            except (EOFError, KeyboardInterrupt) as exc:
                _print_json({"ok": False, "error": f"Password prompt cancelled: {exc}"})
                return 1
            except AniDBAuthError as exc:
                _print_json({"ok": False, "error": str(exc), "error_type": type(exc).__name__})
                return 1
            status = client.session_status()
    _print_json(status)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the AniDB CLI.

    :param list[str] | None argv: Optional argv override.
    :rtype: int
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    # interactive=True → AUTH paths would also getpass once if still missing
    client = AniDBClient(interactive=True, create_socket=False)
    if args.command == "session-status":
        return run_session_status(client)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
