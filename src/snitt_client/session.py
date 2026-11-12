"""Load Snitt session cookies from ENV or local config file (never from chat)."""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_CONFIG_PATH = Path.home() / ".snitt-hu-downloader.cfg"
COOKIE_ENV = "SNITT_COOKIE"
CONFIG_ENV = "SNITT_COOKIE_FILE"


class SessionConfigError(RuntimeError):
    """Raised when no usable Snitt cookie source is configured."""


def load_cookie_header(config_path: Path | None = None) -> str:
    """Return a Cookie request header value from ENV or a one-line config file.

    Priority: ``SNITT_COOKIE`` env, then ``SNITT_COOKIE_FILE`` / default
    ``~/.snitt-hu-downloader.cfg`` first line.

    :param Path | None config_path: Optional explicit config file path.
    :rtype: str
    :raises SessionConfigError: If no cookie can be loaded.
    """
    env_cookie = os.environ.get(COOKIE_ENV, "").strip()
    if env_cookie:
        return env_cookie
    path = config_path
    if path is None:
        env_path = os.environ.get(CONFIG_ENV, "").strip()
        path = Path(env_path) if env_path else DEFAULT_CONFIG_PATH
    if not path.is_file():
        raise SessionConfigError(
            f"No Snitt cookie: set {COOKIE_ENV} or create {path} (first line = Cookie header value)."
        )
    lines = path.read_text(encoding="utf-8").splitlines()
    line = lines[0].strip() if lines else ""
    if not line or line == "IDE_MASOLD_A_BEJELENTKEZESI_SUTIDET":
        raise SessionConfigError(f"Cookie file {path} is empty or still a placeholder.")
    return line


def cookie_header_to_httpx_cookies(cookie_header: str) -> dict[str, str]:
    """Parse a Cookie header string into a name→value mapping for httpx.

    :param str cookie_header: Raw Cookie header (name=value; name2=value2).
    :rtype: dict[str, str]
    """
    cookies: dict[str, str] = {}
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies[name.strip()] = value.strip()
    return cookies
