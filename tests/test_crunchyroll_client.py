# -*- coding: utf-8 -*-
"""Unit tests for CrunchyrollClient (mocked HTTP; no live Crunchyroll)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from snitt_crunchyroll.client import CrunchyrollClient, CrunchyrollClientError
from snitt_crunchyroll.http import HttpResponse, MockHttpTransport
from snitt_crunchyroll.session import CrunchyrollTokenStore, load_token_store


def _token_response(**overrides: object) -> HttpResponse:
    payload = {
        "access_token": "access-1",
        "refresh_token": "refresh-1",
        "expires_in": 3600,
        "token_type": "Bearer",
        "account_id": "acc-1",
        "country": "HU",
    }
    payload.update(overrides)
    return HttpResponse(status_code=200, text=json.dumps(payload), json_data=payload)


def test_login_etp_rt_persists_token_file(tmp_path: Path) -> None:
    transport = MockHttpTransport()
    transport.queue(_token_response())
    token_file = tmp_path / "crunchyroll.json"
    client = CrunchyrollClient(token_file=token_file, transport=transport, create_http=False)
    result = client.login_with_etp_rt("cookie-value")
    assert result["ok"] is True
    assert result["tokens"]["account_id"] == "acc-1"
    assert result["tokens"]["access_token_set"] is True
    assert "access_token" not in result["tokens"]
    stored = load_token_store(token_file)
    assert stored is not None
    assert stored.access_token == "access-1"
    assert stored.etp_rt == "cookie-value"
    assert transport.calls[0].data is not None
    assert transport.calls[0].data.get("grant_type") == "etp_rt_cookie"
    assert transport.calls[0].data.get("device_id")
    assert transport.calls[0].data.get("device_type") == "Firefox on Linux"
    assert transport.calls[0].cookies == {
        "etp_rt": "cookie-value",
        "device_id": transport.calls[0].data["device_id"],
    }
    assert "beta-api.crunchyroll.com" in transport.calls[0].url
    assert stored.device_id == transport.calls[0].data["device_id"]


def test_plan_and_refuse_mark_watched(tmp_path: Path) -> None:
    store = CrunchyrollTokenStore(access_token="a", refresh_token="r", account_id="acc", expires_at=9e12)
    client = CrunchyrollClient(
        token_file=tmp_path / "t.json",
        transport=MockHttpTransport(),
        create_http=False,
        token_store=store,
    )
    plan = client.plan_mark_watched("series-1", level="series")
    assert plan["dry_run"] is True
    with pytest.raises(CrunchyrollClientError, match="allow_save"):
        client.mark_watched("series-1", allow_save=False)


def test_mark_watched_and_rate(tmp_path: Path) -> None:
    transport = MockHttpTransport()
    transport.queue(
        HttpResponse(status_code=200, text="{}", json_data={}),
        HttpResponse(status_code=200, text='{"ok":true}', json_data={"ok": True}),
    )
    store = CrunchyrollTokenStore(access_token="a", refresh_token="r", account_id="acc-9", expires_at=9e12)
    client = CrunchyrollClient(
        token_file=tmp_path / "t.json",
        transport=transport,
        create_http=False,
        token_store=store,
    )
    watched = client.mark_watched("series-9", allow_save=True, level="series")
    assert watched["saved"] is True
    assert "mark_as_watched/series-9" in transport.calls[0].url
    rated = client.rate_series("series-9", 4, allow_save=True)
    assert rated["rating"] == "4s"
    assert transport.calls[1].json_body == {"rating": "4s"}


def test_stars_validation(tmp_path: Path) -> None:
    store = CrunchyrollTokenStore(access_token="a", account_id="acc", expires_at=9e12)
    client = CrunchyrollClient(
        token_file=tmp_path / "t.json",
        transport=MockHttpTransport(),
        create_http=False,
        token_store=store,
    )
    with pytest.raises(CrunchyrollClientError, match="1..5"):
        client.plan_rate_series("s", 0)


def test_ensure_access_token_falls_back_to_etp_rt_when_refresh_client_inactive(tmp_path: Path) -> None:
    transport = MockHttpTransport()
    transport.queue(
        HttpResponse(
            status_code=401,
            text='{"code":"auth.obtain_access_token.client_inactive","error":"invalid_client"}',
            json_data={"code": "auth.obtain_access_token.client_inactive", "error": "invalid_client"},
        ),
        _token_response(access_token="access-from-etp", refresh_token="refresh-2", account_id="acc-2"),
    )
    token_file = tmp_path / "crunchyroll.json"
    store = CrunchyrollTokenStore(
        access_token="old",
        refresh_token="dead-refresh",
        etp_rt="cookie-still-valid",
        account_id="acc-old",
        expires_at=1.0,
        device_id="11111111-1111-1111-1111-111111111111",
        device_type="Firefox on Linux",
    )
    client = CrunchyrollClient(token_file=token_file, transport=transport, create_http=False, token_store=store)
    fresh = client.ensure_access_token()
    assert fresh.access_token == "access-from-etp"
    assert fresh.etp_rt == "cookie-still-valid"
    assert transport.calls[0].data.get("grant_type") == "refresh_token"
    assert transport.calls[1].data.get("grant_type") == "etp_rt_cookie"
    saved = load_token_store(token_file)
    assert saved is not None
    assert saved.access_token == "access-from-etp"


def test_watchlist_plan_add_remove(tmp_path: Path) -> None:
    transport = MockHttpTransport()
    transport.queue(
        HttpResponse(status_code=200, text='{"data":[{"id":"G1"}]}', json_data={"data": [{"id": "G1"}]}),
        HttpResponse(status_code=200, text="{}", json_data={}),
        HttpResponse(status_code=204, text="", json_data=None),
    )
    store = CrunchyrollTokenStore(access_token="a", account_id="acc", expires_at=9e12)
    client = CrunchyrollClient(
        token_file=tmp_path / "t.json",
        transport=transport,
        create_http=False,
        token_store=store,
    )
    listed = client.get_watchlist(limit=10)
    assert listed["count"] == 1
    assert "discover/acc/watchlist" in transport.calls[0].url
    plan = client.plan_watchlist_add("G2")
    assert plan["dry_run"] is True
    with pytest.raises(CrunchyrollClientError, match="allow_save"):
        client.watchlist_add("G2", allow_save=False)
    added = client.watchlist_add("G2", allow_save=True)
    assert added["saved"] is True
    assert transport.calls[1].json_body == {"content_id": "G2"}
    removed = client.watchlist_remove("G2", allow_save=True)
    assert removed["saved"] is True
    assert transport.calls[2].method == "DELETE"


def test_custom_list_create_gated(tmp_path: Path) -> None:
    store = CrunchyrollTokenStore(access_token="a", account_id="acc", expires_at=9e12)
    client = CrunchyrollClient(
        token_file=tmp_path / "t.json",
        transport=MockHttpTransport(),
        create_http=False,
        token_store=store,
    )
    plan = client.plan_custom_list_create("My List")
    assert plan["title"] == "My List"
    with pytest.raises(CrunchyrollClientError, match="allow_save"):
        client.custom_list_create("My List", allow_save=False)


def test_search_parses_buckets(tmp_path: Path) -> None:
    transport = MockHttpTransport()
    payload = {
        "data": [
            {
                "type": "series",
                "items": [{"id": "G1", "title": "Demo", "slug_title": "demo", "type": "series"}],
            }
        ]
    }
    transport.queue(HttpResponse(status_code=200, text=json.dumps(payload), json_data=payload))
    store = CrunchyrollTokenStore(access_token="a", account_id="acc", expires_at=9e12)
    client = CrunchyrollClient(
        token_file=tmp_path / "t.json",
        transport=transport,
        create_http=False,
        token_store=store,
    )
    result = client.search("Demo")
    assert result["count"] == 1
    assert result["items"][0]["id"] == "G1"
