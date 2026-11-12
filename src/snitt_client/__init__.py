"""Shared Snitt.hu client library for verified sheet fetch and gated edits."""

from snitt_client.client import SnittClient
from snitt_client.models import DescriptionPlan, SheetSnapshot, TaggingPlan, TagRef

__all__ = [
    "DescriptionPlan",
    "SheetSnapshot",
    "SnittClient",
    "TagRef",
    "TaggingPlan",
]

__version__ = "0.1.0"
