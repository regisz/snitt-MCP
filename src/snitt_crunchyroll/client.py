"""Unofficial Crunchyroll client: token-file auth, search, gated watched/rating writes."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from snitt_crunchyroll.http import (
    CrunchyrollHttpError,
    HttpResponse,
    HttpTransport,
    HttpxTransport,
    absolute_url,
)
from snitt_crunchyroll.session import (
    AUTH_TOKEN_URL,
    DEFAULT_DEVICE_TYPE,
    DEFAULT_LOCALE,
    REFRESH_CLIENT_BASIC,
    WEB_CLIENT_BASIC,
    CrunchyrollAuthError,
    CrunchyrollTokenStore,
    clear_token_store,
    ensure_device_id,
    load_token_store,
    save_token_store,
    token_path,
)

STAR_RATINGS = frozenset({"1s", "2s", "3s", "4s", "5s"})


class CrunchyrollClientError(RuntimeError):
    """Raised for client-side / API logical errors."""


class CrunchyrollClient:
    """Paced-independent unofficial Crunchyroll helper with gated writes.

    Auth prefers ``~/.config/snitt/crunchyroll.json`` (refresh / etp_rt). Live
    network is only used when a real transport is configured. Unit tests inject
    :class:`MockHttpTransport`.

    :param Path | None token_file: Optional token JSON override.
    :param HttpTransport | None transport: Injectable HTTP layer.
    :param bool create_http: When True and transport is None, use httpx.
    """

    def __init__(
        self,
        *,
        token_file: Path | None = None,
        transport: HttpTransport | None = None,
        create_http: bool = True,
        token_store: CrunchyrollTokenStore | None = None,
    ) -> None:
        self._token_file = token_path(token_file)
        self._transport: HttpTransport | None = transport
        if self._transport is None and create_http:
            self._transport = HttpxTransport()
        self._store = token_store if token_store is not None else load_token_store(self._token_file)

    def session_status(self) -> dict[str, Any]:
        """Return local auth status without requiring a network call.

        :rtype: dict[str, Any]
        """
        store = self._store
        return {
            "ok": True,
            "token_file": str(self._token_file),
            "token_file_exists": self._token_file.is_file(),
            "authenticated": bool(store and store.access_token and store.account_id),
            "tokens": store.redacted() if store else None,
            "note": "Unofficial Crunchyroll API; ToS/breakage risk; personal best-effort.",
        }

    def login_with_etp_rt(self, etp_rt: str, *, locale: str | None = None) -> dict[str, Any]:
        """Exchange ``etp_rt`` cookie for tokens and persist the token file.

        :param str etp_rt: Value of the ``etp_rt`` cookie from a logged-in browser.
        :param str | None locale: Optional locale override stored with tokens.
        :rtype: dict[str, Any]
        :raises CrunchyrollAuthError: On empty cookie or auth failure.
        """
        if not isinstance(etp_rt, str) or not etp_rt.strip():
            raise CrunchyrollAuthError("etp_rt cookie value is empty.")
        store = self._exchange_etp_rt(etp_rt.strip(), locale=locale)
        path = save_token_store(store, self._token_file)
        self._store = store
        return {"ok": True, "token_file": str(path), "tokens": store.redacted()}

    def logout(self) -> dict[str, Any]:
        """Clear in-memory tokens and delete the token file.

        :rtype: dict[str, Any]
        """
        self._store = None
        deleted = clear_token_store(self._token_file)
        return {"ok": True, "token_file_deleted": deleted}

    def ensure_access_token(self) -> CrunchyrollTokenStore:
        """Return a usable token store, refreshing when needed.

        :rtype: CrunchyrollTokenStore
        :raises CrunchyrollAuthError: If no tokens can be obtained.
        """
        store = self._store or load_token_store(self._token_file)
        if store is None:
            raise CrunchyrollAuthError(
                f"No Crunchyroll token file at {self._token_file}. "
                "Run: snitt-crunchyroll login-etp-rt"
            )
        self._store = store
        if not store.is_expired():
            return store
        # Prefer refresh_token. Crunchyroll may disable community OAuth clients (401 client_inactive);
        # then fall back to browser etp_rt cookie exchange while that cookie is still valid.
        if store.refresh_token:
            try:
                store = self._refresh_access_token(store)
            except CrunchyrollAuthError:
                if not store.etp_rt:
                    raise
                store = self._exchange_etp_rt(store.etp_rt, locale=store.locale)
        elif store.etp_rt:
            store = self._exchange_etp_rt(store.etp_rt, locale=store.locale)
        else:
            raise CrunchyrollAuthError(
                "Access token expired and no refresh_token/etp_rt available; re-run login-etp-rt."
            )
        save_token_store(store, self._token_file)
        self._store = store
        return store

    def search(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        """Search series/movies by text query.

        :param str query: Search string.
        :param int limit: Max items (capped).
        :rtype: dict[str, Any]
        """
        store = self.ensure_access_token()
        n = max(1, min(int(limit), 50))
        response = self._api(
            "GET",
            "/content/v2/discover/search",
            store=store,
            params={"q": query, "n": n, "type": "series,movie_listing", "locale": store.locale},
        )
        items = self._extract_search_items(response.json_data)
        return {"ok": True, "query": query, "items": items, "count": len(items)}

    def get_series(self, series_id: str) -> dict[str, Any]:
        """Fetch one series by id.

        :param str series_id: Crunchyroll series GUID.
        :rtype: dict[str, Any]
        """
        store = self.ensure_access_token()
        response = self._api(
            "GET",
            f"/content/v2/cms/series/{series_id}",
            store=store,
            params={"locale": store.locale},
        )
        data = self._first_data(response.json_data)
        return {"ok": True, "series_id": series_id, "series": data}

    def get_seasons(self, series_id: str) -> dict[str, Any]:
        """List seasons for a series.

        :param str series_id: Crunchyroll series GUID.
        :rtype: dict[str, Any]
        """
        store = self.ensure_access_token()
        response = self._api(
            "GET",
            f"/content/v2/cms/series/{series_id}/seasons",
            store=store,
            params={"locale": store.locale},
        )
        seasons = self._data_list(response.json_data)
        return {"ok": True, "series_id": series_id, "seasons": seasons, "count": len(seasons)}

    def get_episodes(self, season_id: str) -> dict[str, Any]:
        """List episodes for a season.

        :param str season_id: Crunchyroll season GUID.
        :rtype: dict[str, Any]
        """
        store = self.ensure_access_token()
        response = self._api(
            "GET",
            f"/content/v2/cms/seasons/{season_id}/episodes",
            store=store,
            params={"locale": store.locale},
        )
        episodes = self._data_list(response.json_data)
        return {"ok": True, "season_id": season_id, "episodes": episodes, "count": len(episodes)}

    def get_watchlist(self, *, limit: int = 50, start: int = 0) -> dict[str, Any]:
        """Return the account watchlist (discover view).

        :param int limit: Page size (``n``).
        :param int start: Offset.
        :rtype: dict[str, Any]
        """
        store = self.ensure_access_token()
        account_id = self._require_account_id(store)
        n = max(1, min(int(limit), 200))
        start_n = max(0, int(start))
        response = self._api(
            "GET",
            f"/content/v2/discover/{account_id}/watchlist",
            store=store,
            params={"n": n, "start": start_n, "locale": store.locale},
        )
        items = self._data_list(response.json_data)
        return {
            "ok": True,
            "items": items,
            "count": len(items),
            "limit": n,
            "start": start_n,
        }

    def plan_watchlist_add(self, content_id: str) -> dict[str, Any]:
        """Dry-run watchlist add preview (no HTTP).

        :param str content_id: Series or movie_listing GUID.
        :rtype: dict[str, Any]
        """
        if not content_id:
            raise CrunchyrollClientError("content_id is required")
        return {
            "ok": True,
            "dry_run": True,
            "content_id": content_id,
            "method": "POST",
            "path": "/content/v2/{account_id}/watchlist",
            "body": {"content_id": content_id},
        }

    def watchlist_add(self, content_id: str, *, allow_save: bool = False) -> dict[str, Any]:
        """Add content to the watchlist when ``allow_save`` is true.

        :param str content_id: Series or movie_listing GUID.
        :param bool allow_save: Required gate for live write.
        :rtype: dict[str, Any]
        """
        if not allow_save:
            raise CrunchyrollClientError("Refusing write without allow_save=true")
        if not content_id:
            raise CrunchyrollClientError("content_id is required")
        store = self.ensure_access_token()
        account_id = self._require_account_id(store)
        response = self._api(
            "POST",
            f"/content/v2/{account_id}/watchlist",
            store=store,
            params={"locale": store.locale},
            json_body={"content_id": content_id},
        )
        return {
            "ok": True,
            "saved": True,
            "content_id": content_id,
            "status_code": response.status_code,
            "body": response.json_data,
        }

    def plan_watchlist_remove(self, content_id: str) -> dict[str, Any]:
        """Dry-run watchlist remove preview (no HTTP).

        :param str content_id: Series or movie_listing GUID.
        :rtype: dict[str, Any]
        """
        if not content_id:
            raise CrunchyrollClientError("content_id is required")
        return {
            "ok": True,
            "dry_run": True,
            "content_id": content_id,
            "method": "DELETE",
            "path": f"/content/v2/{{account_id}}/watchlist/{content_id}",
        }

    def watchlist_remove(self, content_id: str, *, allow_save: bool = False) -> dict[str, Any]:
        """Remove content from the watchlist when ``allow_save`` is true.

        :param str content_id: Series or movie_listing GUID.
        :param bool allow_save: Required gate for live write.
        :rtype: dict[str, Any]
        """
        if not allow_save:
            raise CrunchyrollClientError("Refusing write without allow_save=true")
        if not content_id:
            raise CrunchyrollClientError("content_id is required")
        store = self.ensure_access_token()
        account_id = self._require_account_id(store)
        response = self._api(
            "DELETE",
            f"/content/v2/{account_id}/watchlist/{content_id}",
            store=store,
            params={"locale": store.locale},
        )
        return {
            "ok": True,
            "saved": True,
            "content_id": content_id,
            "status_code": response.status_code,
            "body": response.json_data,
        }

    def get_custom_lists(self) -> dict[str, Any]:
        """List custom (private) lists for the account.

        :rtype: dict[str, Any]
        """
        store = self.ensure_access_token()
        account_id = self._require_account_id(store)
        response = self._api(
            "GET",
            f"/content/v2/{account_id}/custom-lists",
            store=store,
            params={"locale": store.locale},
        )
        items = self._data_list(response.json_data)
        return {"ok": True, "lists": items, "count": len(items)}

    def get_custom_list_items(self, list_id: str, *, page: int = 1, page_size: int = 50) -> dict[str, Any]:
        """List items in one custom list.

        :param str list_id: Custom list id.
        :param int page: Page number (>= 1).
        :param int page_size: Page size.
        :rtype: dict[str, Any]
        """
        if not list_id:
            raise CrunchyrollClientError("list_id is required")
        store = self.ensure_access_token()
        account_id = self._require_account_id(store)
        page_n = max(1, int(page))
        size_n = max(1, min(int(page_size), 200))
        response = self._api(
            "GET",
            f"/content/v2/{account_id}/custom-lists/{list_id}",
            store=store,
            params={"locale": store.locale, "page": page_n, "page_size": size_n},
        )
        items = self._data_list(response.json_data)
        return {
            "ok": True,
            "list_id": list_id,
            "items": items,
            "count": len(items),
            "page": page_n,
            "page_size": size_n,
        }

    def plan_custom_list_create(self, title: str) -> dict[str, Any]:
        """Dry-run custom list create preview (no HTTP).

        :param str title: New list title.
        :rtype: dict[str, Any]
        """
        if not title or not title.strip():
            raise CrunchyrollClientError("title is required")
        return {
            "ok": True,
            "dry_run": True,
            "title": title.strip(),
            "method": "POST",
            "path": "/content/v2/{account_id}/custom-lists",
            "body": {"title": title.strip()},
        }

    def custom_list_create(self, title: str, *, allow_save: bool = False) -> dict[str, Any]:
        """Create a custom list when ``allow_save`` is true.

        :param str title: New list title.
        :param bool allow_save: Required gate for live write.
        :rtype: dict[str, Any]
        """
        if not allow_save:
            raise CrunchyrollClientError("Refusing write without allow_save=true")
        if not title or not title.strip():
            raise CrunchyrollClientError("title is required")
        store = self.ensure_access_token()
        account_id = self._require_account_id(store)
        response = self._api(
            "POST",
            f"/content/v2/{account_id}/custom-lists",
            store=store,
            params={"locale": store.locale},
            json_body={"title": title.strip()},
        )
        return {
            "ok": True,
            "saved": True,
            "title": title.strip(),
            "status_code": response.status_code,
            "body": response.json_data,
        }

    def plan_custom_list_add_item(self, list_id: str, content_id: str) -> dict[str, Any]:
        """Dry-run add-to-custom-list preview (no HTTP).

        :param str list_id: Custom list id.
        :param str content_id: Series or movie_listing GUID.
        :rtype: dict[str, Any]
        """
        if not list_id or not content_id:
            raise CrunchyrollClientError("list_id and content_id are required")
        return {
            "ok": True,
            "dry_run": True,
            "list_id": list_id,
            "content_id": content_id,
            "method": "POST",
            "path": f"/content/v2/{{account_id}}/custom-lists/{list_id}",
            "body": {"content_id": content_id},
        }

    def custom_list_add_item(self, list_id: str, content_id: str, *, allow_save: bool = False) -> dict[str, Any]:
        """Add an item to a custom list when ``allow_save`` is true.

        :param str list_id: Custom list id.
        :param str content_id: Series or movie_listing GUID.
        :param bool allow_save: Required gate for live write.
        :rtype: dict[str, Any]
        """
        if not allow_save:
            raise CrunchyrollClientError("Refusing write without allow_save=true")
        if not list_id or not content_id:
            raise CrunchyrollClientError("list_id and content_id are required")
        store = self.ensure_access_token()
        account_id = self._require_account_id(store)
        response = self._api(
            "POST",
            f"/content/v2/{account_id}/custom-lists/{list_id}",
            store=store,
            params={"locale": store.locale},
            json_body={"content_id": content_id},
        )
        return {
            "ok": True,
            "saved": True,
            "list_id": list_id,
            "content_id": content_id,
            "status_code": response.status_code,
            "body": response.json_data,
        }

    def plan_custom_list_remove_item(self, list_id: str, content_id: str) -> dict[str, Any]:
        """Dry-run remove-from-custom-list preview (no HTTP).

        :param str list_id: Custom list id.
        :param str content_id: Series or movie_listing GUID.
        :rtype: dict[str, Any]
        """
        if not list_id or not content_id:
            raise CrunchyrollClientError("list_id and content_id are required")
        return {
            "ok": True,
            "dry_run": True,
            "list_id": list_id,
            "content_id": content_id,
            "method": "DELETE",
            "path": f"/content/v2/{{account_id}}/custom-lists/{list_id}/{content_id}",
        }

    def custom_list_remove_item(self, list_id: str, content_id: str, *, allow_save: bool = False) -> dict[str, Any]:
        """Remove an item from a custom list when ``allow_save`` is true.

        :param str list_id: Custom list id.
        :param str content_id: Series or movie_listing GUID.
        :param bool allow_save: Required gate for live write.
        :rtype: dict[str, Any]
        """
        if not allow_save:
            raise CrunchyrollClientError("Refusing write without allow_save=true")
        if not list_id or not content_id:
            raise CrunchyrollClientError("list_id and content_id are required")
        store = self.ensure_access_token()
        account_id = self._require_account_id(store)
        response = self._api(
            "DELETE",
            f"/content/v2/{account_id}/custom-lists/{list_id}/{content_id}",
            store=store,
            params={"locale": store.locale},
        )
        return {
            "ok": True,
            "saved": True,
            "list_id": list_id,
            "content_id": content_id,
            "status_code": response.status_code,
            "body": response.json_data,
        }

    def plan_mark_watched(self, content_id: str, *, level: str = "series") -> dict[str, Any]:
        """Dry-run preview for mark-as-watched (no HTTP).

        :param str content_id: Series or episode GUID.
        :param str level: ``series`` (finished) or ``episode`` (in progress).
        :rtype: dict[str, Any]
        """
        level_norm = self._normalize_level(level)
        return {
            "ok": True,
            "dry_run": True,
            "level": level_norm,
            "content_id": content_id,
            "method": "POST",
            "path": f"/content/v2/discover/{{account_id}}/mark_as_watched/{content_id}",
            "note": (
                "Finished series → level=series only. In-progress → level=episode "
                "(and/or playhead). No per-episode fan-out when the whole series is done."
            ),
        }

    def mark_watched(self, content_id: str, *, allow_save: bool = False, level: str = "series") -> dict[str, Any]:
        """Mark series or episode watched when ``allow_save`` is true.

        :param str content_id: Series or episode GUID.
        :param bool allow_save: Required gate for live write.
        :param str level: ``series`` or ``episode`` (documentation / plan only).
        :rtype: dict[str, Any]
        """
        if not allow_save:
            raise CrunchyrollClientError("Refusing write without allow_save=true")
        level_norm = self._normalize_level(level)
        if not content_id:
            raise CrunchyrollClientError("content_id is required")
        store = self.ensure_access_token()
        account_id = store.account_id
        if not account_id:
            raise CrunchyrollAuthError("account_id missing from token store; re-login.")
        response = self._api(
            "POST",
            f"/content/v2/discover/{account_id}/mark_as_watched/{content_id}",
            store=store,
            params={"locale": store.locale},
        )
        return {
            "ok": True,
            "saved": True,
            "level": level_norm,
            "content_id": content_id,
            "status_code": response.status_code,
            "body": response.json_data,
        }

    def plan_set_playhead(self, content_id: str, playhead_seconds: int) -> dict[str, Any]:
        """Dry-run playhead update preview (no HTTP).

        :param str content_id: Episode GUID.
        :param int playhead_seconds: Playback position in seconds.
        :rtype: dict[str, Any]
        """
        seconds = self._require_non_negative_seconds(playhead_seconds)
        return {
            "ok": True,
            "dry_run": True,
            "content_id": content_id,
            "playhead_seconds": seconds,
            "method": "POST",
            "path": "/content/v2/{account_id}/playheads",
            "note": "Use for in-progress episodes only; finished series uses mark_watched(level=series).",
        }

    def set_playhead(
        self,
        content_id: str,
        playhead_seconds: int,
        *,
        allow_save: bool = False,
    ) -> dict[str, Any]:
        """Update episode playhead when ``allow_save`` is true.

        :param str content_id: Episode GUID.
        :param int playhead_seconds: Playback position in seconds.
        :param bool allow_save: Required gate for live write.
        :rtype: dict[str, Any]
        """
        if not allow_save:
            raise CrunchyrollClientError("Refusing write without allow_save=true")
        seconds = self._require_non_negative_seconds(playhead_seconds)
        if not content_id:
            raise CrunchyrollClientError("content_id is required")
        store = self.ensure_access_token()
        account_id = store.account_id
        if not account_id:
            raise CrunchyrollAuthError("account_id missing from token store; re-login.")
        response = self._api(
            "POST",
            f"/content/v2/{account_id}/playheads",
            store=store,
            params={"locale": store.locale},
            json_body={"content_id": content_id, "playhead": seconds},
        )
        return {
            "ok": True,
            "saved": True,
            "content_id": content_id,
            "playhead_seconds": seconds,
            "status_code": response.status_code,
            "body": response.json_data,
        }

    def plan_rate_series(self, series_id: str, stars: int) -> dict[str, Any]:
        """Dry-run series star rating (1–5) preview (no HTTP).

        Prefer the sheet computed 5★ column as the source value.

        :param str series_id: Series GUID.
        :param int stars: Integer 1..5.
        :rtype: dict[str, Any]
        """
        rating = self._stars_to_rating(stars)
        return {
            "ok": True,
            "dry_run": True,
            "series_id": series_id,
            "stars": int(stars),
            "rating": rating,
            "method": "PUT",
            "path": f"/content-reviews/v2/user/{{account_id}}/rating/series/{series_id}",
            "note": "Source stars from sheet computed 5★ column (10→5), not raw 10-scale.",
        }

    def rate_series(self, series_id: str, stars: int, *, allow_save: bool = False) -> dict[str, Any]:
        """Set series rating 1–5 stars when ``allow_save`` is true.

        :param str series_id: Series GUID.
        :param int stars: Integer 1..5 (from sheet 5★ column).
        :param bool allow_save: Required gate for live write.
        :rtype: dict[str, Any]
        """
        if not allow_save:
            raise CrunchyrollClientError("Refusing write without allow_save=true")
        rating = self._stars_to_rating(stars)
        if not series_id:
            raise CrunchyrollClientError("series_id is required")
        store = self.ensure_access_token()
        account_id = store.account_id
        if not account_id:
            raise CrunchyrollAuthError("account_id missing from token store; re-login.")
        response = self._api(
            "PUT",
            f"/content-reviews/v2/user/{account_id}/rating/series/{series_id}",
            store=store,
            json_body={"rating": rating},
        )
        return {
            "ok": True,
            "saved": True,
            "series_id": series_id,
            "stars": int(stars),
            "rating": rating,
            "status_code": response.status_code,
            "body": response.json_data,
        }

    def _transport_or_raise(self) -> HttpTransport:
        if self._transport is None:
            raise CrunchyrollClientError(
                "No HTTP transport: inject MockHttpTransport for tests, or create_http=True."
            )
        return self._transport

    @staticmethod
    def _require_account_id(store: CrunchyrollTokenStore) -> str:
        if not store.account_id:
            raise CrunchyrollAuthError("account_id missing from token store; re-login.")
        return store.account_id

    def _exchange_etp_rt(self, etp_rt: str, *, locale: str | None = None) -> CrunchyrollTokenStore:
        """Exchange browser ``etp_rt`` via cookie grant (with device fields), then refresh fallback.

        Current Crunchyroll auth requires ``device_id`` / ``device_type``; missing them
        yields HTTP 400 ``missing_required_field``.
        """
        transport = self._transport_or_raise()
        existing = self._store.device_id if self._store else ""
        device_id = ensure_device_id(existing)
        device_type = (self._store.device_type if self._store else "") or DEFAULT_DEVICE_TYPE
        cookie_response = transport.request(
            "POST",
            AUTH_TOKEN_URL,
            headers={
                "Authorization": f"Basic {WEB_CLIENT_BASIC}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "etp_rt_cookie",
                "device_id": device_id,
                "device_type": device_type,
            },
            cookies={"etp_rt": etp_rt, "device_id": device_id},
        )
        if cookie_response.status_code < 400 and isinstance(cookie_response.json_data, dict):
            return self._store_from_token_payload(
                cookie_response.json_data,
                etp_rt=etp_rt,
                locale=locale,
                device_id=device_id,
                device_type=device_type,
            )
        if self._looks_like_cloudflare(cookie_response):
            raise CrunchyrollAuthError(
                "Crunchyroll auth blocked by Cloudflare (\"Just a moment...\"). "
                "Retry later, use a non-VPN network, or paste a fresh etp_rt from "
                "crunchyroll.com while logged in."
            )
        refresh_response = transport.request(
            "POST",
            AUTH_TOKEN_URL,
            headers={
                "Authorization": f"Basic {REFRESH_CLIENT_BASIC}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": etp_rt,
                "scope": "offline_access",
                "device_id": device_id,
                "device_type": device_type,
                "device_name": "snitt-crunchyroll",
            },
        )
        if refresh_response.status_code < 400 and isinstance(refresh_response.json_data, dict):
            return self._store_from_token_payload(
                refresh_response.json_data,
                etp_rt=etp_rt,
                locale=locale,
                fallback_refresh=etp_rt,
                device_id=device_id,
                device_type=device_type,
            )
        # Prefer the more specific cookie-grant error body for the user.
        payload = self._require_json_object(cookie_response, context="etp_rt auth")
        return self._store_from_token_payload(
            payload,
            etp_rt=etp_rt,
            locale=locale,
            device_id=device_id,
            device_type=device_type,
        )

    def _refresh_access_token(self, store: CrunchyrollTokenStore) -> CrunchyrollTokenStore:
        transport = self._transport_or_raise()
        device_id = ensure_device_id(store.device_id)
        device_type = store.device_type or DEFAULT_DEVICE_TYPE
        response = transport.request(
            "POST",
            AUTH_TOKEN_URL,
            headers={
                "Authorization": f"Basic {REFRESH_CLIENT_BASIC}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": store.refresh_token,
                "scope": "offline_access",
                "device_id": device_id,
                "device_type": device_type,
                "device_name": "snitt-crunchyroll",
            },
        )
        if self._looks_like_cloudflare(response):
            raise CrunchyrollAuthError(
                "Token refresh blocked by Cloudflare. Re-run snitt-crunchyroll login-etp-rt "
                "with a fresh etp_rt cookie."
            )
        payload = self._require_json_object(response, context="refresh_token auth")
        return self._store_from_token_payload(
            payload,
            etp_rt=store.etp_rt,
            locale=store.locale,
            fallback_refresh=store.refresh_token,
            device_id=device_id,
            device_type=device_type,
        )

    @staticmethod
    def _looks_like_cloudflare(response: HttpResponse) -> bool:
        text = (response.text or "")[:200].lower()
        return response.status_code in {403, 503} and (
            "just a moment" in text or "cf-ray" in text or "cloudflare" in text
        )

    def _store_from_token_payload(
        self,
        payload: dict[str, Any],
        *,
        etp_rt: str = "",
        locale: str | None = None,
        fallback_refresh: str = "",
        device_id: str = "",
        device_type: str = DEFAULT_DEVICE_TYPE,
    ) -> CrunchyrollTokenStore:
        access = str(payload.get("access_token") or "")
        if not access:
            raise CrunchyrollAuthError(f"Auth response missing access_token: keys={sorted(payload)}")
        expires_in = float(payload.get("expires_in") or 0)
        refresh = str(payload.get("refresh_token") or fallback_refresh or "")
        return CrunchyrollTokenStore(
            access_token=access,
            refresh_token=refresh,
            etp_rt=etp_rt,
            account_id=str(payload.get("account_id") or ""),
            country=str(payload.get("country") or ""),
            locale=(locale or DEFAULT_LOCALE),
            expires_at=time.time() + expires_in if expires_in else 0.0,
            token_type=str(payload.get("token_type") or "Bearer"),
            device_id=ensure_device_id(device_id),
            device_type=device_type or DEFAULT_DEVICE_TYPE,
        )

    def _api(
        self,
        method: str,
        path: str,
        *,
        store: CrunchyrollTokenStore,
        params: dict[str, str | int] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> HttpResponse:
        transport = self._transport_or_raise()
        headers = {
            "Authorization": store.authorization_header(),
            "Accept": "application/json",
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        response = transport.request(
            method,
            absolute_url(path),
            headers=headers,
            params=params,
            json_body=json_body,
        )
        if response.status_code >= 400:
            raise CrunchyrollHttpError(
                f"Crunchyroll HTTP {response.status_code} for {method} {path}",
                status_code=response.status_code,
                body=response.text[:500],
            )
        return response

    @staticmethod
    def _require_json_object(response: HttpResponse, *, context: str) -> dict[str, Any]:
        if response.status_code >= 400:
            raise CrunchyrollAuthError(
                f"{context} failed: HTTP {response.status_code}: {response.text[:300]}"
            )
        if not isinstance(response.json_data, dict):
            raise CrunchyrollAuthError(f"{context} returned non-object JSON")
        return response.json_data

    @staticmethod
    def _normalize_level(level: str) -> str:
        level_norm = (level or "series").strip().lower()
        if level_norm not in {"series", "episode"}:
            raise CrunchyrollClientError("level must be 'series' or 'episode'")
        return level_norm

    @staticmethod
    def _require_non_negative_seconds(value: int) -> int:
        try:
            seconds = int(value)
        except (TypeError, ValueError) as exc:
            raise CrunchyrollClientError("playhead_seconds must be an integer") from exc
        if seconds < 0:
            raise CrunchyrollClientError("playhead_seconds must be >= 0")
        return seconds

    @staticmethod
    def _stars_to_rating(stars: int) -> str:
        try:
            value = int(stars)
        except (TypeError, ValueError) as exc:
            raise CrunchyrollClientError("stars must be an integer 1..5") from exc
        rating = f"{value}s"
        if rating not in STAR_RATINGS:
            raise CrunchyrollClientError("stars must be an integer 1..5")
        return rating

    @staticmethod
    def _data_list(payload: dict[str, Any] | list[Any] | None) -> list[Any]:
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list):
                return data
            return []
        if isinstance(payload, list):
            return payload
        return []

    @staticmethod
    def _first_data(payload: dict[str, Any] | list[Any] | None) -> Any:
        items = CrunchyrollClient._data_list(payload)
        if items:
            return items[0]
        if isinstance(payload, dict):
            return payload
        return None

    @staticmethod
    def _extract_search_items(payload: dict[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if not isinstance(payload, dict):
            return items
        for bucket in CrunchyrollClient._data_list(payload):
            if not isinstance(bucket, dict):
                continue
            for entry in bucket.get("items") or []:
                if not isinstance(entry, dict):
                    continue
                items.append(
                    {
                        "id": entry.get("id"),
                        "type": entry.get("type") or bucket.get("type"),
                        "title": entry.get("title") or entry.get("name"),
                        "slug_title": entry.get("slug_title"),
                        "description": entry.get("description"),
                    }
                )
        return items
