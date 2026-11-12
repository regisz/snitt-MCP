"""Google Sheets auth: browser OAuth (preferred) or service-account fallback.

Tokens and client secrets stay on disk / ENV — never paste into chat.
Snitt.hu auth is separate (cookie/session file), not browser OAuth.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)

OAUTH_CLIENT_SECRETS_ENV = "GOOGLE_SHEETS_OAUTH_CLIENT_SECRETS"
OAUTH_TOKEN_ENV = "GOOGLE_SHEETS_OAUTH_TOKEN"
SERVICE_ACCOUNT_ENV = "GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE"

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "snitt"
DEFAULT_OAUTH_CLIENT_SECRETS = DEFAULT_CONFIG_DIR / "google-oauth-client.json"
DEFAULT_OAUTH_TOKEN = DEFAULT_CONFIG_DIR / "google-oauth-token.json"
DEFAULT_SERVICE_ACCOUNT = DEFAULT_CONFIG_DIR / "google-service-account.json"

Credentials = UserCredentials | ServiceAccountCredentials


class SheetsAuthError(RuntimeError):
    """Raised when Google Sheets credentials are missing or unreadable."""


def oauth_client_secrets_path(explicit: Path | None = None) -> Path:
    """Return the OAuth installed-app client secrets JSON path.

    :param Path | None explicit: Optional override.
    :rtype: Path
    """
    if explicit is not None:
        return explicit
    env_path = os.environ.get(OAUTH_CLIENT_SECRETS_ENV, "").strip()
    return Path(env_path) if env_path else DEFAULT_OAUTH_CLIENT_SECRETS


def oauth_token_path(explicit: Path | None = None) -> Path:
    """Return the stored user OAuth token JSON path.

    :param Path | None explicit: Optional override.
    :rtype: Path
    """
    if explicit is not None:
        return explicit
    env_path = os.environ.get(OAUTH_TOKEN_ENV, "").strip()
    return Path(env_path) if env_path else DEFAULT_OAUTH_TOKEN


def service_account_path(explicit: Path | None = None) -> Path:
    """Return the service-account JSON path.

    :param Path | None explicit: Optional override.
    :rtype: Path
    """
    if explicit is not None:
        return explicit
    env_path = os.environ.get(SERVICE_ACCOUNT_ENV, "").strip()
    return Path(env_path) if env_path else DEFAULT_SERVICE_ACCOUNT


def load_oauth_credentials(
    *,
    token_path: Path | None = None,
    client_secrets_path: Path | None = None,
    interactive: bool = False,
) -> UserCredentials | None:
    """Load user OAuth credentials from the token file; optionally run browser login.

    When ``interactive`` is False (MCP/runtime default), only an existing token is
    used (refresh if expired). When True, opens the system browser via loopback
    OAuth if no usable token exists.

    :param Path | None token_path: Stored token JSON path.
    :param Path | None client_secrets_path: Installed-app client secrets JSON.
    :param bool interactive: Allow browser OAuth when token is missing.
    :rtype: UserCredentials | None
    :raises SheetsAuthError: If interactive login is requested but secrets are missing.
    """
    token_file = oauth_token_path(token_path)
    secrets_file = oauth_client_secrets_path(client_secrets_path)
    creds: UserCredentials | None = None
    if token_file.is_file():
        creds = UserCredentials.from_authorized_user_file(str(token_file), scopes=list(SCOPES))
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_oauth_token(creds, token_file)
        return creds
    if not interactive:
        return None
    if not secrets_file.is_file():
        raise SheetsAuthError(
            f"Missing OAuth client secrets for browser login: set {OAUTH_CLIENT_SECRETS_ENV} "
            f"or place Desktop client JSON at {secrets_file}."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_file), scopes=list(SCOPES))
    creds = flow.run_local_server(port=0, open_browser=True, prompt="consent")
    _save_oauth_token(creds, token_file)
    return creds


def load_service_account_credentials(credentials_path: Path | None = None) -> ServiceAccountCredentials:
    """Return service-account credentials (optional fallback).

    :param Path | None credentials_path: Optional explicit JSON key path.
    :rtype: ServiceAccountCredentials
    :raises SheetsAuthError: If the key file is missing.
    """
    path = service_account_path(credentials_path)
    if not path.is_file():
        raise SheetsAuthError(
            f"No Google service-account JSON: set {SERVICE_ACCOUNT_ENV} or create {path}."
        )
    return ServiceAccountCredentials.from_service_account_file(str(path), scopes=list(SCOPES))


def load_credentials(
    *,
    oauth_token_path_arg: Path | None = None,
    oauth_client_secrets_path_arg: Path | None = None,
    service_account_path_arg: Path | None = None,
    interactive: bool = False,
) -> Credentials:
    """Return Google credentials: OAuth user token first, then service account.

    :param Path | None oauth_token_path_arg: Optional OAuth token path.
    :param Path | None oauth_client_secrets_path_arg: Optional client secrets path.
    :param Path | None service_account_path_arg: Optional service-account path.
    :param bool interactive: Allow browser OAuth when no token exists.
    :rtype: Credentials
    :raises SheetsAuthError: If neither OAuth nor service-account auth is available.
    """
    oauth = load_oauth_credentials(
        token_path=oauth_token_path_arg,
        client_secrets_path=oauth_client_secrets_path_arg,
        interactive=interactive,
    )
    if oauth is not None:
        return oauth
    sa_path = service_account_path(service_account_path_arg)
    if sa_path.is_file():
        return load_service_account_credentials(sa_path)
    token_file = oauth_token_path(oauth_token_path_arg)
    secrets_file = oauth_client_secrets_path(oauth_client_secrets_path_arg)
    raise SheetsAuthError(
        "No Google Sheets credentials. Run `snitt-sheets-auth` once (browser OAuth), "
        f"or place a token at {token_file}, or a service-account JSON at {sa_path}. "
        f"Client secrets for first login: {secrets_file} (or {OAUTH_CLIENT_SECRETS_ENV}). "
        "Note: Snitt.hu still uses SNITT_COOKIE / ~/.snitt-hu-downloader.cfg — not browser OAuth."
    )


def run_browser_oauth(
    *,
    client_secrets_path: Path | None = None,
    token_path: Path | None = None,
) -> Path:
    """Run installed-app loopback OAuth in the default browser and store the token.

    :param Path | None client_secrets_path: Desktop OAuth client secrets JSON.
    :param Path | None token_path: Where to write the refresh token JSON.
    :rtype: Path
    :raises SheetsAuthError: If secrets are missing or login fails.
    """
    creds = load_oauth_credentials(
        token_path=token_path,
        client_secrets_path=client_secrets_path,
        interactive=True,
    )
    if creds is None:
        raise SheetsAuthError("Browser OAuth did not return credentials.")
    out = oauth_token_path(token_path)
    return out


def auth_status(
    *,
    token_path: Path | None = None,
    client_secrets_path: Path | None = None,
    service_account_path_arg: Path | None = None,
) -> dict[str, Any]:
    """Return a redacted auth status dict for CLI/docs (no secrets).

    :rtype: dict[str, Any]
    """
    token_file = oauth_token_path(token_path)
    secrets_file = oauth_client_secrets_path(client_secrets_path)
    sa_file = service_account_path(service_account_path_arg)
    return {
        "oauth_client_secrets_present": secrets_file.is_file(),
        "oauth_client_secrets_path": str(secrets_file),
        "oauth_token_present": token_file.is_file(),
        "oauth_token_path": str(token_file),
        "service_account_present": sa_file.is_file(),
        "service_account_path": str(sa_file),
        "scopes": list(SCOPES),
        "snitt_auth_note": "Snitt uses cookie/session file (SNITT_COOKIE), not Google browser OAuth.",
    }


def _save_oauth_token(creds: UserCredentials, token_file: Path) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    try:
        token_file.chmod(0o600)
    except OSError:
        pass


def main_auth(argv: list[str] | None = None) -> int:
    """CLI entry: run browser OAuth or print auth status.

    :param list[str] | None argv: Optional argv (without program name).
    :rtype: int
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="snitt-sheets-auth",
        description="Google Sheets browser OAuth for snitt-sheets (stores refresh token locally).",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print redacted auth status JSON and exit (no browser).",
    )
    parser.add_argument("--client-secrets", type=Path, help="Path to OAuth Desktop client JSON")
    parser.add_argument("--token", type=Path, help="Path to write/read the user token JSON")
    args = parser.parse_args(argv)
    if args.status:
        print(json.dumps(auth_status(token_path=args.token, client_secrets_path=args.client_secrets), indent=2))
        return 0
    try:
        out = run_browser_oauth(client_secrets_path=args.client_secrets, token_path=args.token)
    except SheetsAuthError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "token_path": str(out), "message": "OAuth token stored locally (not for chat)."}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main_auth())
