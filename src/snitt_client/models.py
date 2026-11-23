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


@dataclass(frozen=True)
class StreamingRef:
    """One streaming service shown on a sheet or szerkesztés Streaming table."""

    name: str
    service_id: int | None = None
    already_present: bool = False
    can_add: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        :rtype: dict[str, Any]
        """
        return asdict(self)


@dataclass(frozen=True)
class LinkEntry:
    """One external link from GET /filmek/<slug>/linkek."""

    link_id: int
    url: str
    title: str | None = None
    username: str | None = None

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
    links_nav_text: str | None = None
    streaming: list[StreamingRef] = field(default_factory=list)
    has_add_tag_link: bool = False
    has_add_genre_link: bool = False
    has_add_description_link: bool = False
    has_add_link_link: bool = False
    book_id: int | None = None
    is_favorite: bool = False
    favorite_href: str | None = None
    favorite_id: int | None = None
    personal_stars: float | None = None
    set_rating_path: str | None = None
    has_mark_watched_link: bool = False
    has_add_review_link: bool = False

    def has_tag_named(self, name: str) -> bool:
        """Return whether any visible /cimkek link uses this display name.

        :param str name: Exact display name as on the sheet.
        :rtype: bool
        """
        return any(tag.name == name for tag in self.all_tags)

    def has_streaming_named(self, name: str) -> bool:
        """Return whether the coverbox Streaming block lists this service name.

        :param str name: Exact service display name (e.g. Disney+).
        :rtype: bool
        """
        return any(item.name == name for item in self.streaming)

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
            "links_nav_text": self.links_nav_text,
            "streaming": [item.to_dict() for item in self.streaming],
            "has_add_tag_link": self.has_add_tag_link,
            "has_add_genre_link": self.has_add_genre_link,
            "has_add_description_link": self.has_add_description_link,
            "has_add_link_link": self.has_add_link_link,
            "book_id": self.book_id,
            "is_favorite": self.is_favorite,
            "favorite_href": self.favorite_href,
            "favorite_id": self.favorite_id,
            "personal_stars": self.personal_stars,
            "set_rating_path": self.set_rating_path,
            "has_mark_watched_link": self.has_mark_watched_link,
            "has_add_review_link": self.has_add_review_link,
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
class LinkPlan:
    """Dry-run plan for POST /filmek/<slug>/linkek/add."""

    kind: str
    slug: str
    method: str
    path: str
    fields: dict[str, str]
    url: str
    already_present: bool
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        :rtype: dict[str, Any]
        """
        return {
            "kind": self.kind,
            "slug": self.slug,
            "method": self.method,
            "path": self.path,
            "fields": dict(self.fields),
            "url": self.url,
            "already_present": self.already_present,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class StreamingPlan:
    """Dry-run plan for POST /filmek/<slug>/streaming?service=<id> (Rails UJS add)."""

    kind: str
    slug: str
    method: str
    path: str
    fields: dict[str, str]
    service_id: int
    service_name: str
    already_present: bool
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        :rtype: dict[str, Any]
        """
        return {
            "kind": self.kind,
            "slug": self.slug,
            "method": self.method,
            "path": self.path,
            "fields": dict(self.fields),
            "service_id": self.service_id,
            "service_name": self.service_name,
            "already_present": self.already_present,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class EpisodeOption:
    """One ``watching[episode_id]`` select option from the watching modal."""

    episode_id: int
    label: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        :rtype: dict[str, Any]
        """
        return asdict(self)


@dataclass
class WatchingFormSnapshot:
    """Parsed GET ``/filmek/<slug>/filmnezesek/uj`` modal form."""

    slug: str
    title: str | None
    path: str
    is_series: bool
    episodes: list[EpisodeOption] = field(default_factory=list)
    has_in_cinema: bool = False
    has_episode_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        :rtype: dict[str, Any]
        """
        return {
            "slug": self.slug,
            "title": self.title,
            "path": self.path,
            "is_series": self.is_series,
            "episodes": [episode.to_dict() for episode in self.episodes],
            "has_in_cinema": self.has_in_cinema,
            "has_episode_review": self.has_episode_review,
        }


@dataclass(frozen=True)
class WatchingPlan:
    """Dry-run plan for POST ``/filmek/<slug>/filmnezesek`` (mark watched)."""

    kind: str
    slug: str
    method: str
    path: str
    fields: dict[str, str]
    is_series: bool
    episode_id: int | None
    episode_label: str | None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        :rtype: dict[str, Any]
        """
        fields = dict(self.fields)
        if "watching[review]" in fields and fields["watching[review]"]:
            fields["watching[review]"] = f"[text len={len(self.fields['watching[review]'])}]"
        return {
            "kind": self.kind,
            "slug": self.slug,
            "method": self.method,
            "path": self.path,
            "fields": fields,
            "is_series": self.is_series,
            "episode_id": self.episode_id,
            "episode_label": self.episode_label,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class FavoritePlan:
    """Dry-run plan for favorite heart toggle (POST kedvenc-filmek)."""

    kind: str
    slug: str
    method: str
    path: str
    fields: dict[str, str]
    want_favorite: bool
    currently_favorite: bool
    favorite_id: int | None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        :rtype: dict[str, Any]
        """
        return {
            "kind": self.kind,
            "slug": self.slug,
            "method": self.method,
            "path": self.path,
            "fields": dict(self.fields),
            "want_favorite": self.want_favorite,
            "currently_favorite": self.currently_favorite,
            "favorite_id": self.favorite_id,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class RatingPlan:
    """Dry-run plan for personal 1–10 star rating via set_rating."""

    kind: str
    slug: str
    method: str
    path: str
    fields: dict[str, str]
    book_id: int
    stars: int
    previous_stars: float | None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict (authenticity_token redacted).

        :rtype: dict[str, Any]
        """
        fields = dict(self.fields)
        if "authenticity_token" in fields:
            fields["authenticity_token"] = "[redacted]"
        return {
            "kind": self.kind,
            "slug": self.slug,
            "method": self.method,
            "path": self.path,
            "fields": fields,
            "book_id": self.book_id,
            "stars": self.stars,
            "previous_stars": self.previous_stars,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ReviewPlan:
    """Dry-run plan for POST ``/ertekelesek`` text review."""

    kind: str
    slug: str
    method: str
    path: str
    fields: dict[str, str]
    book_id: int
    text_length: int
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict with review text redacted.

        :rtype: dict[str, Any]
        """
        fields = dict(self.fields)
        if "review[review]" in fields:
            fields["review[review]"] = f"[text len={self.text_length}]"
        return {
            "kind": self.kind,
            "slug": self.slug,
            "method": self.method,
            "path": self.path,
            "fields": fields,
            "book_id": self.book_id,
            "text_length": self.text_length,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class DeletePlan:
    """Dry-run plan for Rails UJS destroy (POST path + ``_method=delete``)."""

    kind: str
    resource_id: int
    method: str
    path: str
    fields: dict[str, str]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        :rtype: dict[str, Any]
        """
        return {
            "kind": self.kind,
            "resource_id": self.resource_id,
            "method": self.method,
            "path": self.path,
            "fields": dict(self.fields),
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
