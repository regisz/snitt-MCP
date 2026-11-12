"""Thin unofficial Crunchyroll client (token file auth; gated writes)."""

from snitt_crunchyroll.client import CrunchyrollClient, CrunchyrollClientError
from snitt_crunchyroll.session import CrunchyrollAuthError, CrunchyrollTokenStore

__all__ = [
    "CrunchyrollAuthError",
    "CrunchyrollClient",
    "CrunchyrollClientError",
    "CrunchyrollTokenStore",
]

__version__ = "0.1.0"
