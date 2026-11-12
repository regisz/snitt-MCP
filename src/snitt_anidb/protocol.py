"""Encode/decode AniDB UDP API command strings and replies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote


def encode_command(command: str, params: dict[str, Any] | None = None) -> str:
    """Build a UDP command string ``CMD key=value&...``.

    Values are percent-encoded; keys and the command verb are not.

    :param str command: Command verb (AUTH, ANIME, MYLIST, …).
    :param dict[str, Any] | None params: Optional parameters.
    :rtype: str
    """
    if not params:
        return command
    # AniDB rejects AUTH when '!' in the website password is percent-encoded as %21
    # (verified live: quote(..., safe='') → 500 LOGIN FAILED; safe='!' → 200 LOGIN ACCEPTED).
    # Letters/digits/'_.-' are never quoted by urllib; keep '!' literal too.
    parts = [f"{key}={quote(str(value), safe='!')}" for key, value in params.items() if value is not None]
    return f"{command} {'&'.join(parts)}"


@dataclass(frozen=True)
class AniDBReply:
    """Parsed AniDB UDP reply.

    :param int code: Three-digit reply code.
    :param str message: Text after the code on the first line.
    :param str data: Remaining payload after the first line (may be empty).
    :param str | None tag: Optional request tag echoed by the server.
    :param list[str] fields: Pipe-split fields from ``data`` (first data line).
    """

    code: int
    message: str
    data: str = ""
    tag: str | None = None
    fields: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return True for 2xx success-class codes.

        :rtype: bool
        """
        return 200 <= self.code < 300

    def to_dict(self) -> dict[str, Any]:
        """Serialize for MCP/tool payloads.

        :rtype: dict[str, Any]
        """
        return {
            "code": self.code,
            "message": self.message,
            "data": self.data,
            "tag": self.tag,
            "fields": list(self.fields),
            "ok": self.ok,
        }


def parse_reply(raw: str) -> AniDBReply:
    """Parse a raw UDP reply body into :class:`AniDBReply`.

    :param str raw: Decoded reply text.
    :rtype: AniDBReply
    :raises ValueError: If the reply has no recognizable code.
    """
    text = raw.strip("\0").strip()
    if not text:
        raise ValueError("Empty AniDB reply")
    lines = text.split("\n")
    first = lines[0].strip()
    data = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    parts = first.split(" ", 2)
    tag: str | None = None
    if len(parts) >= 2 and parts[0].isdigit() and len(parts[0]) == 3:
        code_s = parts[0]
        message = parts[1] if len(parts) == 2 else f"{parts[1]} {parts[2]}".strip()
    elif len(parts) >= 3 and parts[1].isdigit() and len(parts[1]) == 3:
        tag = parts[0]
        code_s = parts[1]
        message = parts[2]
    else:
        raise ValueError(f"Unrecognized AniDB reply header: {first!r}")
    code = int(code_s)
    # classic layout: first line = code + message; next line = pipe fields
    field_source = data.split("\n", 1)[0] if data else ""
    # some replies put a single scalar on the same logical payload line (AUTH session is in message)
    fields = field_source.split("|") if field_source else []
    return AniDBReply(code=code, message=message, data=data, tag=tag, fields=fields)


# Classic ANIME (no amask) field order from the UDP wiki.
ANIME_CLASSIC_FIELDS = (
    "aid",
    "episodes",
    "ep_count",
    "special_cnt",
    "rating",
    "votes",
    "tmprating",
    "tmpvotes",
    "review_rating",
    "reviews",
    "year",
    "type",
    "romaji",
    "kanji",
    "english",
    "other",
    "short_names",
    "synonyms",
    "categories",
)

MYLIST_FIELDS = (
    "lid",
    "fid",
    "eid",
    "aid",
    "gid",
    "date",
    "state",
    "viewdate",
    "storage",
    "source",
    "other",
    "filestate",
)


def map_fields(names: tuple[str, ...], values: list[str]) -> dict[str, str]:
    """Zip field names to pipe values (extra values kept as ``extra_N``).

    :param tuple[str, ...] names: Expected field names.
    :param list[str] values: Pipe-split values.
    :rtype: dict[str, str]
    """
    mapped = {name: values[idx] if idx < len(values) else "" for idx, name in enumerate(names)}
    for idx in range(len(names), len(values)):
        mapped[f"extra_{idx}"] = values[idx]
    return mapped
