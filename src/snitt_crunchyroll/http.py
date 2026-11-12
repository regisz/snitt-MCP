"""HTTP transport for unofficial Crunchyroll API (injectable for tests)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from snitt_crunchyroll.session import API_BASE, DEFAULT_USER_AGENT


class CrunchyrollHttpError(RuntimeError):
    """Raised when an HTTP call fails or returns a non-success status."""

    def __init__(self, message: str, *, status_code: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass(frozen=True)
class HttpResponse:
    """Minimal HTTP response used by the client.

    :param int status_code: HTTP status.
    :param str text: Raw body text.
    :param dict[str, Any] json_data: Parsed JSON when available.
    """

    status_code: int
    text: str
    json_data: dict[str, Any] | list[Any] | None


class HttpTransport(Protocol):
    """Request interface used by :class:`CrunchyrollClient`."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str | int] | None = None,
        cookies: dict[str, str] | None = None,
    ) -> HttpResponse:
        """Perform one HTTP request."""


class HttpxTransport:
    """Real ``httpx`` transport against Crunchyroll hosts."""

    def __init__(self, *, timeout: float = 30.0, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self._timeout = timeout
        self._user_agent = user_agent

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str | int] | None = None,
        cookies: dict[str, str] | None = None,
    ) -> HttpResponse:
        merged = {"User-Agent": self._user_agent, "Accept": "application/json, text/plain, */*"}
        if headers:
            merged.update(headers)
        with httpx.Client(timeout=self._timeout, follow_redirects=True, headers={"User-Agent": self._user_agent}) as client:
            response = client.request(
                method,
                url,
                headers=merged,
                data=data,
                json=json_body,
                params=params,
                cookies=cookies,
            )
        json_data: dict[str, Any] | list[Any] | None
        try:
            json_data = response.json()
        except ValueError:
            json_data = None
        return HttpResponse(status_code=response.status_code, text=response.text, json_data=json_data)


@dataclass
class MockCall:
    """Recorded mock HTTP call."""

    method: str
    url: str
    headers: dict[str, str]
    data: dict[str, str] | None
    json_body: dict[str, Any] | None
    params: dict[str, str | int] | None
    cookies: dict[str, str] | None


class MockHttpTransport:
    """Queue-based HTTP mock for unit tests."""

    def __init__(self) -> None:
        self.calls: list[MockCall] = []
        self._queue: list[HttpResponse | Exception] = []

    def queue(self, *items: HttpResponse | Exception) -> None:
        """Append canned responses or exceptions.

        :param HttpResponse | Exception items: Responses to return in order.
        """
        self._queue.extend(items)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str | int] | None = None,
        cookies: dict[str, str] | None = None,
    ) -> HttpResponse:
        self.calls.append(
            MockCall(
                method=method.upper(),
                url=url,
                headers=dict(headers or {}),
                data=dict(data) if data else None,
                json_body=dict(json_body) if json_body else None,
                params=dict(params) if params else None,
                cookies=dict(cookies) if cookies else None,
            )
        )
        if not self._queue:
            raise AssertionError(f"MockHttpTransport exhausted for {method} {url}")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def absolute_url(path_or_url: str) -> str:
    """Join ``API_BASE`` when ``path_or_url`` is a path.

    :param str path_or_url: Absolute URL or ``/…`` path.
    :rtype: str
    """
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url
    if not path_or_url.startswith("/"):
        path_or_url = "/" + path_or_url
    return API_BASE.rstrip("/") + path_or_url
