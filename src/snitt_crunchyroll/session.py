"""Crunchyroll token file at ~/.config/snitt/crunchyroll.json (no password in mcp.json)."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

TOKEN_ENV = "CRUNCHYROLL_TOKEN_FILE"
ETP_RT_ENV = "CRUNCHYROLL_ETP_RT"
DEVICE_ID_ENV = "CRUNCHYROLL_DEVICE_ID"
DEFAULT_TOKEN_PATH = Path.home() / ".config" / "snitt" / "crunchyroll.json"
DEFAULT_LOCALE = "hu-HU"
DEFAULT_DEVICE_TYPE = "Firefox on Linux"

# Public client Basic auth values used by community clients (not user secrets).
# WEB: etp_rt_cookie grant. ANDROID-ish: refresh_token / password grants.
WEB_CLIENT_BASIC = "bm9haWhkZXZtXzZpeWcwYThsMHE6"
REFRESH_CLIENT_BASIC = "aHJobzlxM2F3dnNrMjJ1LXRzNWE6cHROOURteXRBU2Z6QjZvbXVsSzh6cUxzYTczVE1TY1k="
# beta-api is less often Cloudflare-challenged than www for /auth/v1/token.
AUTH_TOKEN_URL = "https://beta-api.crunchyroll.com/auth/v1/token"
API_BASE = "https://beta-api.crunchyroll.com"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:147.0) Gecko/20100101 Firefox/147.0"
)


class CrunchyrollAuthError(RuntimeError):
    """Raised when Crunchyroll tokens are missing or unusable."""


@dataclass
class CrunchyrollTokenStore:
    """Persisted Crunchyroll session tokens (never log access/refresh values).

    :param str access_token: Bearer access token.
    :param str refresh_token: Refresh token (preferred for renew).
    :param str etp_rt: Optional cookie seed used for first login.
    :param str account_id: Account id from token response.
    :param str country: Country code from token response.
    :param str locale: Preferred locale query value.
    :param float expires_at: Unix timestamp when access_token expires.
    :param str token_type: Usually ``Bearer``.
    """

    access_token: str = ""
    refresh_token: str = ""
    etp_rt: str = ""
    account_id: str = ""
    country: str = ""
    locale: str = DEFAULT_LOCALE
    expires_at: float = 0.0
    token_type: str = "Bearer"
    device_id: str = ""
    device_type: str = DEFAULT_DEVICE_TYPE

    def redacted(self) -> dict[str, Any]:
        """Return status-safe dict without token secrets.

        :rtype: dict[str, Any]
        """
        return {
            "account_id": self.account_id,
            "country": self.country,
            "locale": self.locale,
            "token_type": self.token_type,
            "expires_at": self.expires_at,
            "device_id_set": bool(self.device_id),
            "device_type": self.device_type,
            "access_token_set": bool(self.access_token),
            "refresh_token_set": bool(self.refresh_token),
            "etp_rt_set": bool(self.etp_rt),
            "expired": self.is_expired(),
        }

    def is_expired(self, *, skew_seconds: float = 60.0) -> bool:
        """Return whether the access token should be refreshed.

        :param float skew_seconds: Refresh early by this many seconds.
        :rtype: bool
        """
        if not self.access_token:
            return True
        if self.expires_at <= 0:
            return False
        return time.time() >= (self.expires_at - skew_seconds)

    def authorization_header(self) -> str:
        """Return ``Authorization`` header value.

        :rtype: str
        :raises CrunchyrollAuthError: If access token is missing.
        """
        if not self.access_token:
            raise CrunchyrollAuthError(
                f"Crunchyroll access token missing; run snitt-crunchyroll login-etp-rt "
                f"or place tokens at {DEFAULT_TOKEN_PATH}."
            )
        kind = self.token_type or "Bearer"
        return f"{kind} {self.access_token}"


def token_path(explicit: Path | None = None) -> Path:
    """Return the token JSON path.

    :param Path | None explicit: Optional override.
    :rtype: Path
    """
    if explicit is not None:
        return explicit
    env_path = os.environ.get(TOKEN_ENV, "").strip()
    return Path(env_path) if env_path else DEFAULT_TOKEN_PATH


def load_token_store(path: Path | None = None) -> CrunchyrollTokenStore | None:
    """Load token store from disk if present.

    :param Path | None path: Optional file override.
    :rtype: CrunchyrollTokenStore | None
    """
    file_path = token_path(path)
    if not file_path.is_file():
        return None
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CrunchyrollAuthError(f"Invalid Crunchyroll token file (not an object): {file_path}")
    return CrunchyrollTokenStore(
        access_token=str(raw.get("access_token") or ""),
        refresh_token=str(raw.get("refresh_token") or ""),
        etp_rt=str(raw.get("etp_rt") or ""),
        account_id=str(raw.get("account_id") or ""),
        country=str(raw.get("country") or ""),
        locale=str(raw.get("locale") or DEFAULT_LOCALE),
        expires_at=float(raw.get("expires_at") or 0.0),
        token_type=str(raw.get("token_type") or "Bearer"),
        device_id=str(raw.get("device_id") or ""),
        device_type=str(raw.get("device_type") or DEFAULT_DEVICE_TYPE),
    )


def ensure_device_id(existing: str = "") -> str:
    """Return a stable device id (env override, existing value, or new UUID).

    :param str existing: Previously stored device id.
    :rtype: str
    """
    import uuid

    env_id = os.environ.get(DEVICE_ID_ENV, "").strip()
    if env_id:
        return env_id
    if existing.strip():
        return existing.strip()
    return str(uuid.uuid4())


def save_token_store(store: CrunchyrollTokenStore, path: Path | None = None) -> Path:
    """Write token store to disk with restrictive permissions.

    :param CrunchyrollTokenStore store: Tokens to persist.
    :param Path | None path: Optional file override.
    :rtype: Path
    """
    file_path = token_path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(store)
    file_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.chmod(file_path, 0o600)
    except OSError:
        pass
    return file_path


def clear_token_store(path: Path | None = None) -> bool:
    """Delete the token file if it exists.

    :param Path | None path: Optional file override.
    :rtype: bool
    """
    file_path = token_path(path)
    if not file_path.is_file():
        return False
    file_path.unlink()
    return True


def etp_rt_from_env() -> str:
    """Return ``CRUNCHYROLL_ETP_RT`` if set (temporary bootstrap only).

    :rtype: str
    """
    return os.environ.get(ETP_RT_ENV, "").strip()
