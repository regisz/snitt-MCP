# -*- coding: utf-8 -*-
"""Fixture tests for sheet parsing and gated dry-run plans (no live POST)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from snitt_client.client import SnittClient, SnittClientError
from snitt_client.parse import parse_linkek_list_html, parse_sheet_html, parse_streaming_edit_html

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
    assert sheet.links_nav_text == "Linkek 4"
    assert sheet.has_add_link_link is True
    assert sheet.has_streaming_named("Disney+")
    assert sheet.streaming[0].service_id == 6


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


def test_list_open_tags_and_genres_use_q_param() -> None:
    open_tags = (FIXTURES / "open_tags_harc.json").read_text(encoding="utf-8")
    genres = (FIXTURES / "genres_a.json").read_text(encoding="utf-8")
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        query = request.url.params.get("q", "")
        seen.append((path, query))
        if path == "/api/open_tags_with_names.json":
            return httpx.Response(200, text=open_tags, headers={"content-type": "application/json"})
        if path == "/api/genres_with_names.json":
            return httpx.Response(200, text=genres, headers={"content-type": "application/json"})
        return httpx.Response(404, text="missing")

    with SnittClient(cookie_header="browser=test", transport=httpx.MockTransport(handler)) as client:
        tags = client.list_open_tags("  harc  ")
        assert [tag.name for tag in tags] == ["harc", "harcművészet"]
        assert tags[0].tag_id == 295
        genres_list = client.list_genres("a")
        assert len(genres_list) == 5
        assert genres_list[0].name == "akció"
        with pytest.raises(SnittClientError, match="non-empty q"):
            client.list_open_tags("")
        with pytest.raises(SnittClientError, match="non-empty q"):
            client.list_genres("   ")
    assert ("/api/open_tags_with_names.json", "harc") in seen
    assert ("/api/genres_with_names.json", "a") in seen


def test_parse_linkek_and_streaming_edit_fixtures() -> None:
    links = parse_linkek_list_html((FIXTURES / "linkek_nyarido_fragment.html").read_text(encoding="utf-8"))
    assert [entry.link_id for entry in links] == [62363, 52943, 52942]
    assert links[1].url.startswith("https://anidb.net/")
    services = parse_streaming_edit_html(
        (FIXTURES / "szerkesztes_streaming_nyarido_fragment.html").read_text(encoding="utf-8")
    )
    by_name = {item.name: item for item in services}
    assert by_name["Netflix"].service_id == 3 and by_name["Netflix"].can_add is True
    assert by_name["Disney+"].already_present is True and by_name["Disney+"].can_add is False
    assert by_name["Crunchyroll"].service_id == 12


def test_plan_link_and_streaming_dry_run() -> None:
    sheet = (FIXTURES / "sheet_nyarido_fragment.html").read_text(encoding="utf-8")
    linkek = (FIXTURES / "linkek_nyarido_fragment.html").read_text(encoding="utf-8")
    szerkesztes = (FIXTURES / "szerkesztes_streaming_nyarido_fragment.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            raise AssertionError(f"Unexpected POST in dry-run test: {path}")
        if path == "/filmek/nyarido-szamitas":
            return httpx.Response(200, text=sheet)
        if path == "/filmek/nyarido-szamitas/linkek":
            return httpx.Response(200, text=linkek)
        if path == "/filmek/nyarido-szamitas/szerkesztes":
            return httpx.Response(200, text=szerkesztes)
        return httpx.Response(404, text="missing")

    with SnittClient(cookie_header="browser=test", transport=httpx.MockTransport(handler)) as client:
        link_plan = client.plan_add_link("nyarido-szamitas", "https://example.com/lawful")
        assert link_plan.path == "/filmek/nyarido-szamitas/linkek/add"
        assert link_plan.fields["link[link]"] == "https://example.com/lawful"
        assert link_plan.fields["commit"] == "Hozzáad"
        assert link_plan.fields["link[title]"] == "example.com"
        assert link_plan.already_present is False
        with pytest.raises(SnittClientError, match="allow_save"):
            client.save_link(link_plan, allow_save=False)
        dup = client.plan_add_link("nyarido-szamitas", "https://anidb.net/anime/16033")
        assert dup.already_present is True
        with pytest.raises(SnittClientError, match="already present"):
            client.save_link(dup, allow_save=True)
        streaming_plan = client.plan_add_streaming("nyarido-szamitas", service_name="Netflix")
        assert streaming_plan.service_id == 3
        assert streaming_plan.path == "/filmek/nyarido-szamitas/streaming?service=3"
        assert streaming_plan.fields == {}
        assert streaming_plan.already_present is False
        with pytest.raises(SnittClientError, match="allow_save"):
            client.save_streaming(streaming_plan, allow_save=False)
        disney = client.plan_add_streaming("nyarido-szamitas", service_name="Disney+")
        assert disney.already_present is True
        with pytest.raises(SnittClientError, match="already present"):
            client.save_streaming(disney, allow_save=True)
