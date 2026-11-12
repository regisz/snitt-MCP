"""Thin AniDB UDP client library (owned MIT-compatible wrapper; not GPL anidb-client)."""

from snitt_anidb.client import AniDBClient, AniDBClientError, AniDBBannedError
from snitt_anidb.session import AniDBAuthError, AniDBCredentials

__all__ = [
    "AniDBAuthError",
    "AniDBBannedError",
    "AniDBClient",
    "AniDBClientError",
    "AniDBCredentials",
]

__version__ = "0.1.0"
