# -*- coding: utf-8 -*-
"""Fixture tests for mark-watched / favorite / rating / review gated plans (no live POST)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from snitt_client.client import SnittClient, SnittClientError
from snitt_client.parse import parse_sheet_html, parse_watching_form_html

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_sheet_user_actions_favorite_on_and_rater() -> None:
    html = (FIXTURES / "sheet_grancrest_user_actions_fragment.html").read_text(encoding="utf-8")
    sheet = parse_sheet_html(html, slug="grancrest-senki")
    assert sheet.book_id == 32800
    assert sheet.is_favorite is True
    assert sheet.favorite_id == 555804
    assert sheet.favorite_href == "/kedvenc-filmek/555804"
    assert sheet.personal_stars == 8.0
    assert sheet.set_rating_path == "/ertekelesek/set_rating?book_id=32800"
    assert sheet.has_mark_watched_link is True
    assert sheet.has_add_review_link is True


def test_parse_sheet_user_actions_favorite_off() -> None:
    html = (FIXTURES / "sheet_polip_user_actions_fragment.html").read_text(encoding="utf-8")
    sheet = parse_sheet_html(html, slug="a-fiu-es-a-polip-2024")
    assert sheet.book_id == 101897
    assert sheet.is_favorite is False
    assert sheet.favorite_id is None
    assert sheet.favorite_href == "/filmek/a-fiu-es-a-polip-2024/kedvenc-filmek"
    assert sheet.personal_stars == 8.0


def test_parse_watching_form_series_and_movie() -> None:
    series = parse_watching_form_html(
        (FIXTURES / "filmnezesek_uj_series_fragment.html").read_text(encoding="utf-8"),
        slug="grancrest-senki",
    )
    assert series.is_series is True
    assert series.path == "/filmek/grancrest-senki/filmnezesek"
    assert {item.episode_id for item in series.episodes} >= {274974, 274973, 274972}
    assert series.has_episode_review is True

    movie = parse_watching_form_html(
        (FIXTURES / "filmnezesek_uj_movie_fragment.html").read_text(encoding="utf-8"),
        slug="a-fiu-es-a-polip-2024",
    )
    assert movie.is_series is False
    assert movie.has_in_cinema is True
    assert movie.episodes == []


def _actions_transport() -> httpx.MockTransport:
    sheet = (FIXTURES / "sheet_grancrest_user_actions_fragment.html").read_text(encoding="utf-8")
    polip = (FIXTURES / "sheet_polip_user_actions_fragment.html").read_text(encoding="utf-8")
    series_form = (FIXTURES / "filmnezesek_uj_series_fragment.html").read_text(encoding="utf-8")
    movie_form = (FIXTURES / "filmnezesek_uj_movie_fragment.html").read_text(encoding="utf-8")
    review_form = (FIXTURES / "ertekelesek_uj_fragment.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            raise AssertionError(f"Unexpected live POST in dry-run test: {path}")
        if path == "/filmek/grancrest-senki":
            return httpx.Response(200, text=sheet)
        if path == "/filmek/a-fiu-es-a-polip-2024":
            return httpx.Response(200, text=polip)
        if path == "/filmek/grancrest-senki/filmnezesek/uj":
            return httpx.Response(200, text=series_form)
        if path == "/filmek/a-fiu-es-a-polip-2024/filmnezesek/uj":
            return httpx.Response(200, text=movie_form)
        if path == "/filmek/grancrest-senki/ertekelesek/uj":
            return httpx.Response(200, text=review_form)
        return httpx.Response(404, text="missing")

    return httpx.MockTransport(handler)


def test_plan_mark_watched_series_by_episode_id() -> None:
    with SnittClient(cookie_header="browser=test", transport=_actions_transport()) as client:
        plan = client.plan_mark_watched("grancrest-senki", episode_id=274974)
        assert plan.path == "/filmek/grancrest-senki/filmnezesek"
        assert plan.fields["watching[episode_id]"] == "274974"
        assert plan.fields["commit"] == "Mentés"
        assert plan.episode_label and "24. rész" in plan.episode_label
        with pytest.raises(SnittClientError, match="allow_save"):
            client.save_watching(plan, allow_save=False)


def test_plan_mark_watched_movie() -> None:
    with SnittClient(cookie_header="browser=test", transport=_actions_transport()) as client:
        plan = client.plan_mark_watched("a-fiu-es-a-polip-2024", in_cinema=True)
        assert plan.is_series is False
        assert plan.fields["watching[in_cinema]"] == "1"
        assert "watching[episode_id]" not in plan.fields


def test_plan_favorite_add_and_remove() -> None:
    with SnittClient(cookie_header="browser=test", transport=_actions_transport()) as client:
        add = client.plan_favorite("a-fiu-es-a-polip-2024", want_favorite=True)
        assert add.path == "/filmek/a-fiu-es-a-polip-2024/kedvenc-filmek"
        assert add.fields == {}
        assert add.currently_favorite is False
        remove = client.plan_favorite("grancrest-senki", want_favorite=False)
        assert remove.path == "/kedvenc-filmek/555804"
        assert remove.fields["_method"] == "delete"
        with pytest.raises(SnittClientError, match="allow_save"):
            client.save_favorite(add, allow_save=False)
        with pytest.raises(SnittClientError, match="desired state"):
            client.save_favorite(
                client.plan_favorite("grancrest-senki", want_favorite=True),
                allow_save=True,
            )


def test_plan_set_rating_fields() -> None:
    with SnittClient(cookie_header="browser=test", transport=_actions_transport()) as client:
        plan = client.plan_set_rating("grancrest-senki", 7)
        assert plan.path == "/ertekelesek/set_rating?book_id=32800"
        assert plan.fields["_method"] == "patch"
        assert plan.fields["rating"] == "7"
        assert plan.fields["authenticity_token"] == "TEST_CSRF_TOKEN"
        redacted = plan.to_dict()
        assert redacted["fields"]["authenticity_token"] == "[redacted]"
        with pytest.raises(SnittClientError, match="1 to 10"):
            client.plan_set_rating("grancrest-senki", 11)


def test_plan_add_review_fields() -> None:
    with SnittClient(cookie_header="browser=test", transport=_actions_transport()) as client:
        plan = client.plan_add_review("grancrest-senki", "Rövid próba szöveg", spoiler=True)
        assert plan.path == "/ertekelesek"
        assert plan.fields["review[book_id]"] == "32800"
        assert plan.fields["review[spoiler]"] == "1"
        assert plan.fields["commit"] == "Mentés"
        assert plan.to_dict()["fields"]["review[review]"].startswith("[text len=")
        with pytest.raises(SnittClientError, match="allow_save"):
            client.save_review(plan, allow_save=False)


def test_plan_delete_watching_and_review_fields() -> None:
    with SnittClient(cookie_header="browser=test", transport=httpx.MockTransport(lambda request: httpx.Response(404))) as client:
        watching = client.plan_delete_watching(30530868)
        assert watching.path == "/filmnezesek/30530868"
        assert watching.fields == {"_method": "delete"}
        review = client.plan_delete_review(2333502)
        assert review.path == "/ertekelesek/2333502"
        assert review.fields["_method"] == "delete"
        with pytest.raises(SnittClientError, match="allow_save"):
            client.save_delete_watching(watching, allow_save=False)
        with pytest.raises(SnittClientError, match="allow_save"):
            client.save_delete_review(review, allow_save=False)


def test_save_delete_watching_verify_404() -> None:
    state = {"deleted": False}
    detail = """<!DOCTYPE html><html><head>
<meta name="csrf-token" content="TEST_CSRF_TOKEN" />
<title>balage filmnézése</title></head><body>watching ok</body></html>"""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/filmnezesek/30530868":
            body = request.content.decode("utf-8")
            assert "_method=delete" in body
            assert request.headers.get("x-csrf-token") == "TEST_CSRF_TOKEN"
            state["deleted"] = True
            return httpx.Response(200, text="Turbolinks.visit('/')", headers={"content-type": "text/javascript"})
        if path == "/filmnezesek/30530868":
            if state["deleted"]:
                return httpx.Response(404, text="missing")
            return httpx.Response(200, text=detail)
        return httpx.Response(404, text="missing")

    with SnittClient(cookie_header="browser=test", transport=httpx.MockTransport(handler)) as client:
        plan = client.plan_delete_watching(30530868)
        result = client.save_delete_watching(plan, allow_save=True)
        assert result.ok is True
        assert result.verified is True
        assert result.verify_details["verify_get_status"] == 404


def test_save_rating_verify_with_mock_post() -> None:
    sheet_before = (FIXTURES / "sheet_grancrest_user_actions_fragment.html").read_text(encoding="utf-8")
    sheet_after = sheet_before.replace("rating: 8", "rating: 5").replace("width: 64px;", "width: 80px;")
    state = {"posted": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/ertekelesek/set_rating":
            assert request.url.params.get("book_id") == "32800"
            body = request.content.decode("utf-8")
            assert "_method=patch" in body
            assert "rating=5" in body
            state["posted"] = True
            return httpx.Response(200, text="Turbolinks.visit('/filmek/grancrest-senki')", headers={"content-type": "text/javascript"})
        if request.url.path == "/filmek/grancrest-senki":
            return httpx.Response(200, text=sheet_after if state["posted"] else sheet_before)
        return httpx.Response(404, text="missing")

    with SnittClient(cookie_header="browser=test", transport=httpx.MockTransport(handler)) as client:
        plan = client.plan_set_rating("grancrest-senki", 5)
        result = client.save_rating(plan, allow_save=True)
        assert result.ok is True
        assert result.verified is True
        assert result.verify_details["personal_stars"] == 5.0
