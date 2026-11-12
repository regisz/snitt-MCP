# -*- coding: utf-8 -*-
"""Fixture tests for sheet parsing and gated dry-run plans (no live POST)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from snitt_client.client import SnittClient, SnittClientError
from snitt_client.parse import parse_sheet_html

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_sheet_separates_header_and_open_tags() -> None:
    html = (FIXTURES / "sheet_nyarido_fragment.html").read_text(encoding="utf-8")
    sheet = parse_sheet_html(html, slug="nyarido-szamitas")
    assert sheet.title.startswith("Nyáridő számítás")
    assert sheet.csrf_token == "TEST_CSRF_TOKEN"
    assert sheet.has_tag_named("anime")
    assert sheet.has_tag_named("időhurok")
    assert {tag.name for tag in sheet.header_tags} >= {"japán", "sorozat", "anime"}
    assert {tag.name for tag in sheet.open_tags} == {"időhurok", "rejtély"}
    assert sheet.has_add_genre_link is True
    assert sheet.description_nav_text == "Leírások 1"


def test_plan_genre_dry_run_uses_verified_fields() -> None:
    html = (FIXTURES / "sheet_nyarido_fragment.html").read_text(encoding="utf-8")
    genres = (FIXTURES / "genres_thriller.json").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/filmek/nyarido-szamitas":
            return httpx.Response(200, text=html)
        if request.url.path == "/api/genres_with_names.json":
            return httpx.Response(200, text=genres, headers={"content-type": "application/json"})
        return httpx.Response(404, text="missing")

    transport = httpx.MockTransport(handler)
    with SnittClient(cookie_header="browser=test", transport=transport) as client:
        plan = client.plan_add_genre("nyarido-szamitas", "thriller")
        assert plan.kind == "genre"
        assert plan.path == "/filmek/nyarido-szamitas/cimkezesek"
        assert plan.fields["tagging[tag_id]"] == "84"
        assert plan.fields["commit"] == "Hozzáadás"
        assert plan.already_present is False
        with pytest.raises(SnittClientError, match="allow_save"):
            client.save_tagging(plan, allow_save=False)


def test_plan_tag_marks_already_present() -> None:
    html = (FIXTURES / "sheet_nyarido_fragment.html").read_text(encoding="utf-8")
    payload = json.dumps([{"id": 1, "name": "időhurok"}])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/filmek/nyarido-szamitas":
            return httpx.Response(200, text=html)
        if request.url.path == "/api/open_tags_with_names.json":
            return httpx.Response(200, text=payload, headers={"content-type": "application/json"})
        return httpx.Response(404, text="missing")

    transport = httpx.MockTransport(handler)
    with SnittClient(cookie_header="browser=test", transport=transport) as client:
        plan = client.plan_add_tag("nyarido-szamitas", "időhurok")
        assert plan.already_present is True
        with pytest.raises(SnittClientError, match="already present"):
            client.save_tagging(plan, allow_save=True)


def test_description_plan_fields() -> None:
    with SnittClient(cookie_header="browser=test", transport=httpx.MockTransport(lambda request: httpx.Response(404))) as client:
        plan = client.plan_add_description("dota-a-sarkany-vere", "Davion tapasztalt sárkánylovag")
        assert plan.path == "/filmek/dota-a-sarkany-vere/leirasok"
        assert plan.fields["commit"] == "Mentés"
        assert "description[description]" in plan.fields
        redacted = plan.to_dict()
        assert redacted["fields"]["description[description]"].startswith("[text len=")
