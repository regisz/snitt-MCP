"""Argparse helpers shared by snitt-* CLIs."""

from __future__ import annotations

import argparse
import sys
from typing import Any


def argument_parser(*args: Any, **kwargs: Any) -> argparse.ArgumentParser:
    """Build ``ArgumentParser`` with colored help disabled on Python 3.14+.

    Python 3.14 defaults ``color=True`` and paints help with a dark-background neon
    theme (bright green / magenta) that is hard to read on light terminals. Opt out
    explicitly; older Pythons ignore the kwarg (it does not exist yet).

    :rtype: argparse.ArgumentParser
    """
    if sys.version_info >= (3, 14):
        kwargs.setdefault("color", False)
    return argparse.ArgumentParser(*args, **kwargs)
