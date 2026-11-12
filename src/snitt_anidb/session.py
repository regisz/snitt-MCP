"""Load AniDB UDP identity from ENV/config; password prefers process memory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

USER_ENV = "ANIDB_USER"
PASS_ENV = "ANIDB_PASS"
CLIENT_ENV = "ANIDB_CLIENT"
CLIENTVER_ENV = "ANIDB_CLIENTVER"
PROTOVER_ENV = "ANIDB_PROTOVER"
CONFIG_ENV = "ANIDB_CONFIG_FILE"

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "snitt" / "anidb.cfg"
DEFAULT_PROTOVER = 3

PASSWORD_REQUIRED_MSG = (
    "AniDB password not set in process memory; call anidb_set_password first "
    "(or set ANIDB_PASS as a temporary fallback — prefer omitting it from mcp.json / anidb.cfg)."
)


class AniDBAuthError(RuntimeError):
    """Raised when AniDB credentials are missing or incomplete."""


@dataclass(frozen=True)
class AniDBCredentials:
    """AniDB UDP AUTH parameters (website password, registered client name).

    :param str user: AniDB username.
    :param str password: Website password (empty when not yet set in memory / env).
    :param str client: Registered lowercase client name (a-z, 4–16 chars).
    :param int clientver: Client version integer (start at 1; bump on releases).
    :param int protover: UDP API protover from the wiki (currently 3).
    """

    user: str
    password: str
    client: str
    clientver: int
    protover: int = DEFAULT_PROTOVER

    def redacted(self) -> dict[str, str | int | bool]:
        """Return credentials suitable for status/logs (password omitted).

        :rtype: dict[str, str | int | bool]
        """
        return {
            "user": self.user,
            "client": self.client,
            "clientver": self.clientver,
            "protover": self.protover,
            "password": "***" if self.password else "",
            "password_set": bool(self.password),
        }

    def with_password(self, password: str) -> AniDBCredentials:
        """Return a copy with ``password`` replaced.

        :param str password: Website password to store in the copy.
        :rtype: AniDBCredentials
        """
        return AniDBCredentials(
            user=self.user,
            password=password,
            client=self.client,
            clientver=self.clientver,
            protover=self.protover,
        )


def config_path(explicit: Path | None = None) -> Path:
    """Return the AniDB config file path.

    :param Path | None explicit: Optional override.
    :rtype: Path
    """
    if explicit is not None:
        return explicit
    env_path = os.environ.get(CONFIG_ENV, "").strip()
    return Path(env_path) if env_path else DEFAULT_CONFIG_PATH


def _parse_config_file(path: Path) -> dict[str, str]:
    """Parse a simple ``key=value`` config file (``#`` comments allowed).

    :param Path path: Config file path.
    :rtype: dict[str, str]
    """
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().lower()] = value.strip()
    return values


def _validate_client_name(client: str) -> str:
    client_norm = client.lower()
    if not (4 <= len(client_norm) <= 16 and client_norm.isalpha()):
        raise AniDBAuthError(
            "AniDB client name must be lowercase a-z only, length 4–16 "
            f"(got {client!r}). Register it on the AniDB UDP API Clients page."
        )
    return client_norm


def load_credentials(
    config_path_arg: Path | None = None,
    *,
    require_password: bool = False,
) -> AniDBCredentials:
    """Load AniDB identity from ENV (preferred) or local config file.

    Non-secret fields (user / client / clientver / protover) come from ENV or
    ``~/.config/snitt/anidb.cfg``. Password is optional by default so MCP can
    inject it into process memory via ``anidb_set_password``. ``ANIDB_PASS`` /
    cfg ``pass`` remain a temporary fallback — prefer omitting them from
    ``mcp.json``.

    ENV: ``ANIDB_USER``, ``ANIDB_PASS`` (optional), ``ANIDB_CLIENT``,
    ``ANIDB_CLIENTVER``, optional ``ANIDB_PROTOVER``. File keys match.
    ENV overrides file keys.

    :param Path | None config_path_arg: Optional config file override.
    :param bool require_password: When True, missing password raises.
    :rtype: AniDBCredentials
    :raises AniDBAuthError: If required identity fields (or password) are missing.
    """
    file_values: dict[str, str] = {}
    path = config_path(config_path_arg)
    if path.is_file():
        file_values = _parse_config_file(path)

    def pick(env_name: str, *file_keys: str) -> str:
        env_val = os.environ.get(env_name, "").strip()
        if env_val:
            return env_val
        for key in file_keys:
            if key in file_values and file_values[key]:
                return file_values[key]
        return ""

    user = pick(USER_ENV, "user", "username")
    password = pick(PASS_ENV, "pass", "password")
    client = pick(CLIENT_ENV, "client", "clientname")
    clientver_raw = pick(CLIENTVER_ENV, "clientver", "clientversion")
    protover_raw = pick(PROTOVER_ENV, "protover") or str(DEFAULT_PROTOVER)
    missing = [
        name
        for name, value in (
            (USER_ENV, user),
            (CLIENT_ENV, client),
            (CLIENTVER_ENV, clientver_raw),
        )
        if not value
    ]
    if require_password and not password:
        missing.append(PASS_ENV)
    if missing:
        raise AniDBAuthError(
            "Missing AniDB credentials: set "
            + ", ".join(missing)
            + f" or create {path} (user/client/clientver; password via anidb_set_password). "
            "Register client name with AniDB before AUTH."
        )
    try:
        clientver = int(clientver_raw)
        protover = int(protover_raw)
    except ValueError as exc:
        raise AniDBAuthError("ANIDB_CLIENTVER and ANIDB_PROTOVER must be integers.") from exc
    return AniDBCredentials(
        user=user,
        password=password,
        client=_validate_client_name(client),
        clientver=clientver,
        protover=protover,
    )
