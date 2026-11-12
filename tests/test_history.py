# -*- coding: utf-8 -*-
"""Fixture tests for filmnézések / értékelések parsers (no live HTTP)."""

from __future__ import annotations

from pathlib import Path

import httpx

from snitt_client.client import SnittClient
from snitt_client.history_parse import (
    build_series_watch_span,
    parse_ertekeles_detail_html,
    parse_ertekelesek_list_html,
    parse_filmnezesek_list_html,
    stars_from_rater_width,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_stars_from_rater_width() -> None:
    assert stars_from_rater_width("width: 160px;") == 10.0
    assert stars_from_rater_width("width: 80px;") == 5.0
    assert stars_from_rater_width("width: 144px;") == 9.0
    assert stars_from_rater_width("width: 40px;") == 2.5


def test_parse_filmnezesek_list_fragment() -> None:
    html = (FIXTURES / "filmnezesek_balage_2025_fragment.html").read_text(encoding="utf-8")
    events = parse_filmnezesek_list_html(html)
    assert len(events) >= 3
    first = events[0]
    assert first.slug == "grancrest-senki"
    assert first.watching_id == 28981587
    assert first.episode and "21. rész" in first.episode
    assert first.watched_at == "2025-12-31 17:16"
    movie = next(event for event in events if event.slug == "twisters-vegzetes-vihar-2024")
    assert movie.episode is None
    assert movie.watched_at == "2024-12-30 20:37"


def test_series_watch_span_from_events() -> None:
    html = (FIXTURES / "filmnezesek_balage_2025_fragment.html").read_text(encoding="utf-8")
    events = parse_filmnezesek_list_html(html)
    span = build_series_watch_span(events, "grancrest-senki")
    assert span.watching_count >= 2
    assert span.started_at is not None
    assert span.latest_watched_at is not None
    assert span.started_at <= span.latest_watched_at
    assert span.finished_at is None
    assert span.finished_at_available is False


def test_parse_ertekelesek_list_and_detail() -> None:
    list_html = (FIXTURES / "ertekelesek_balage_fragment.html").read_text(encoding="utf-8")
    entries, meta = parse_ertekelesek_list_html(list_html)
    assert meta["total_counter"] == 894
    assert len(entries) >= 2
    with_text = next(entry for entry in entries if entry.review_text)
    assert with_text.stars == 5.0
    assert with_text.stars_percent == 50.0
    assert "gáz" in (with_text.review_text or "")

    detail_html = (FIXTURES / "ertekeles_detail_fragment.html").read_text(encoding="utf-8")
    detail = parse_ertekeles_detail_html(detail_html)
    assert detail.review_id == 2317943
    assert detail.stars == 5.0
    assert detail.stars_percent == 50.0
    assert detail.rated_at and detail.rated_at.startswith("2026-09-23")
    assert detail.community_average_percent == 66
    assert detail.review_text and "gáz" in detail.review_text


def test_client_list_watchings_uses_get_only() -> None:
    html = (FIXTURES / "filmnezesek_balage_2025_fragment.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/tagok/balage/filmnezesek"
        assert request.url.params.get("year") == "2025"
        return httpx.Response(200, text=html)

    with SnittClient(cookie_header="browser=test", transport=httpx.MockTransport(handler)) as client:
        events = client.list_watchings(year=2025, watching_type="series")
        assert events[0].slug == "grancrest-senki"
