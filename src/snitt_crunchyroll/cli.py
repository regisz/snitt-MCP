"""Thin Crunchyroll CLI: etp_rt login into local token file + session status."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from typing import Any

from snitt_crunchyroll.client import CrunchyrollClient, CrunchyrollClientError
from snitt_crunchyroll.http import CrunchyrollHttpError
from snitt_crunchyroll.session import CrunchyrollAuthError, etp_rt_from_env


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI argument parser.

    :rtype: argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog="snitt-crunchyroll",
        description=(
            "Crunchyroll helpers. Prefer login-etp-rt once (stores tokens under "
            "~/.config/snitt/crunchyroll.json). Do not put passwords in mcp.json."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("session-status", help="Print local token status (no network unless refreshing)")
    login = sub.add_parser(
        "login-etp-rt",
        help="Exchange etp_rt cookie for tokens and save ~/.config/snitt/crunchyroll.json",
    )
    login.add_argument(
        "--etp-rt",
        default="",
        help="etp_rt cookie value (prefer prompt / CRUNCHYROLL_ETP_RT; avoid shell history)",
    )
    login.add_argument("--locale", default="", help="Optional locale override (default hu-HU)")
    sub.add_parser("logout", help="Delete local token file")
    return parser


def _print_json(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def run_login_etp_rt(client: CrunchyrollClient, etp_rt: str, locale: str) -> int:
    """Login with etp_rt and print redacted status.

    :param CrunchyrollClient client: Client instance.
    :param str etp_rt: Cookie value or empty to prompt/env.
    :param str locale: Optional locale override.
    :rtype: int
    """
    value = (etp_rt or etp_rt_from_env() or "").strip()
    if not value:
        try:
            value = getpass.getpass("Crunchyroll etp_rt cookie: ").strip()
        except (EOFError, KeyboardInterrupt) as exc:
            _print_json({"ok": False, "error": f"etp_rt prompt cancelled: {exc}"})
            return 1
    try:
        result = client.login_with_etp_rt(value, locale=locale or None)
    except (CrunchyrollAuthError, CrunchyrollClientError, CrunchyrollHttpError) as exc:
        _print_json({"ok": False, "error": str(exc), "error_type": type(exc).__name__})
        return 1
    _print_json(result)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the Crunchyroll CLI.

    :param list[str] | None argv: Optional argv override.
    :rtype: int
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    client = CrunchyrollClient(create_http=True)
    try:
        if args.command == "session-status":
            _print_json(client.session_status())
            return 0
        if args.command == "login-etp-rt":
            return run_login_etp_rt(client, args.etp_rt, args.locale)
        if args.command == "logout":
            _print_json(client.logout())
            return 0
    except (CrunchyrollAuthError, CrunchyrollClientError, CrunchyrollHttpError) as exc:
        _print_json({"ok": False, "error": str(exc), "error_type": type(exc).__name__})
        return 1
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
