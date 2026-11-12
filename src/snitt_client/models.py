"""Dataclasses for sheet snapshots and save plans."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class TagRef:
    """One Snitt cimke/műfaj reference resolved from HTML or autocomplete JSON."""

    name: str
    href: str | None = None
    tag_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        :rtype: dict[str, Any]
        """
        return asdict(self)


@dataclass
class SheetSnapshot:
    """Parsed film sheet state from GET /filmek/<slug>."""

    slug: str
    url: str
    title: str
    csrf_token: str | None
    header_tags: list[TagRef] = field(default_factory=list)
    open_tags: list[TagRef] = field(default_factory=list)
    all_tags: list[TagRef] = field(default_factory=list)
    description_nav_text: str | None = None
    has_add_tag_link: bool = False
    has_add_genre_link: bool = False
    has_add_description_link: bool = False

    def has_tag_named(self, name: str) -> bool:
        """Return whether any visible /cimkek link uses this display name.

        :param str name: Exact display name as on the sheet.
        :rtype: bool
        """
        return any(tag.name == name for tag in self.all_tags)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict without CSRF secret values.

        :rtype: dict[str, Any]
        """
        return {
            "slug": self.slug,
            "url": self.url,
            "title": self.title,
            "csrf_token_present": bool(self.csrf_token),
            "header_tags": [tag.to_dict() for tag in self.header_tags],
            "open_tags": [tag.to_dict() for tag in self.open_tags],
            "all_tags": [tag.to_dict() for tag in self.all_tags],
            "description_nav_text": self.description_nav_text,
            "has_add_tag_link": self.has_add_tag_link,
            "has_add_genre_link": self.has_add_genre_link,
            "has_add_description_link": self.has_add_description_link,
        }


@dataclass(frozen=True)
class TaggingPlan:
    """Dry-run plan for POST /filmek/<slug>/cimkezesek (open tag or műfaj)."""

    kind: str
    slug: str
    name: str
    tag_id: int
    method: str
    path: str
    fields: dict[str, str]
    already_present: bool
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        :rtype: dict[str, Any]
        """
        return {
            "kind": self.kind,
            "slug": self.slug,
            "name": self.name,
            "tag_id": self.tag_id,
            "method": self.method,
            "path": self.path,
            "fields": dict(self.fields),
            "already_present": self.already_present,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class DescriptionPlan:
    """Dry-run plan for POST /filmek/<slug>/leirasok."""

    kind: str
    slug: str
    method: str
    path: str
    fields: dict[str, str]
    text_length: int
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict with description text redacted by default.

        :rtype: dict[str, Any]
        """
        fields = dict(self.fields)
        if "description[description]" in fields:
            fields["description[description]"] = f"[text len={self.text_length}]"
        return {
            "kind": self.kind,
            "slug": self.slug,
            "method": self.method,
            "path": self.path,
            "fields": fields,
            "text_length": self.text_length,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class SaveResult:
    """Outcome of an explicitly allowed save plus optional re-fetch verify."""

    ok: bool
    status_code: int
    response_content_type: str | None
    response_body: str
    verified: bool | None
    verify_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        :rtype: dict[str, Any]
        """
        return {
            "ok": self.ok,
            "status_code": self.status_code,
            "response_content_type": self.response_content_type,
            "response_body": self.response_body,
            "verified": self.verified,
            "verify_details": dict(self.verify_details),
        }


@dataclass(frozen=True)
class WatchingEvent:
    """One row from ``/tagok/<user>/filmnezesek`` (movie watch or episode)."""

    watching_id: int
    slug: str
    title: str
    book_id: int | None
    episode: str | None
    watched_at: str | None
    watched_at_display: str | None
    detail_path: str
    year: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        :rtype: dict[str, Any]
        """
        return asdict(self)


@dataclass(frozen=True)
class SeriesWatchSpan:
    """First/latest watch bounds for a slug derived from filmnézések events."""

    slug: str
    title: str | None
    book_id: int | None
    started_at: str | None
    latest_watched_at: str | None
    finished_at: str | None
    finished_at_available: bool
    watching_count: int
    episode_labels: list[str] = field(default_factory=list)
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        :rtype: dict[str, Any]
        """
        return {
            "slug": self.slug,
            "title": self.title,
            "book_id": self.book_id,
            "started_at": self.started_at,
            "latest_watched_at": self.latest_watched_at,
            "finished_at": self.finished_at,
            "finished_at_available": self.finished_at_available,
            "watching_count": self.watching_count,
            "episode_labels": list(self.episode_labels),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class RatingEntry:
    """Balázs rating from ``/tagok/<user>/ertekelesek`` or ``/ertekelesek/<id>``."""

    review_id: int
    slug: str
    title: str
    book_id: int | None
    stars: float | None
    max_stars: float
    stars_percent: float | None
    review_text: str | None
    detail_path: str
    rated_at: str | None = None
    community_average_percent: int | None = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        :rtype: dict[str, Any]
        """
        return {
            "review_id": self.review_id,
            "slug": self.slug,
            "title": self.title,
            "book_id": self.book_id,
            "stars": self.stars,
            "max_stars": self.max_stars,
            "stars_percent": self.stars_percent,
            "review_text": self.review_text,
            "detail_path": self.detail_path,
            "rated_at": self.rated_at,
            "community_average_percent": self.community_average_percent,
            "notes": list(self.notes),
        }
