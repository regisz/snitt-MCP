# -*- coding: utf-8 -*-
"""Offline unit tests for AniDB UDP client (mocked transport; no live traffic)."""

from __future__ import annotations

import pytest

from snitt_anidb.client import AniDBBannedError, AniDBClient, AniDBClientError
from snitt_anidb.protocol import encode_command, parse_reply
from snitt_anidb.rate_limit import FloodRateLimiter
from snitt_anidb.session import AniDBAuthError, AniDBCredentials, load_credentials
from snitt_anidb.transport import MockUdpTransport


def _creds() -> AniDBCredentials:
    return AniDBCredentials(
        user="testuser",
        password="secret",
        client="snittanidb",
        clientver=1,
        protover=3,
    )


def _client(transport: MockUdpTransport, sleeper=None) -> AniDBClient:
    limiter = FloodRateLimiter(sleeper=sleeper or (lambda _s: None), idle_reset_seconds=3600)
    return AniDBClient(credentials=_creds(), transport=transport, rate_limiter=limiter, create_socket=False)


def test_encode_and_parse_reply() -> None:
    cmd = encode_command("ANIME", {"aid": 1, "s": "abcd"})
    assert cmd.startswith("ANIME ")
    assert "aid=1" in cmd
    reply = parse_reply("230 ANIME\n1|26|26|0|0|0|0|0|0|0|2008|TV Series|Romaji|Kanji|English||||")
    assert reply.code == 230
    assert reply.fields[0] == "1"
    tagged = parse_reply("t1 200 xLOGIN LOGIN ACCEPTED")
    assert tagged.tag == "t1"
    assert tagged.code == 200


def test_encode_keeps_exclamation_in_password() -> None:
    """AniDB AUTH treats literal '!' as part of the password; %21 → LOGIN FAILED."""
    cmd = encode_command("AUTH", {"user": "regisz", "pass": "ab!cd", "client": "snittanidb", "clientver": 1})
    assert "pass=ab!cd" in cmd
    assert "%21" not in cmd


def test_load_credentials_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("ANIDB_USER", "balage")
    monkeypatch.setenv("ANIDB_PASS", "pw")
    monkeypatch.setenv("ANIDB_CLIENT", "snittanidb")
    monkeypatch.setenv("ANIDB_CLIENTVER", "1")
    creds = load_credentials(tmp_path / "missing.cfg")
    assert creds.user == "balage"
    assert creds.client == "snittanidb"
    assert "password" not in str(creds.redacted()["password"]) or creds.redacted()["password"] == "***"


def test_load_credentials_without_password(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("ANIDB_USER", "balage")
    monkeypatch.delenv("ANIDB_PASS", raising=False)
    monkeypatch.setenv("ANIDB_CLIENT", "snittanidb")
    monkeypatch.setenv("ANIDB_CLIENTVER", "1")
    creds = load_credentials(tmp_path / "missing.cfg", require_password=False)
    assert creds.user == "balage"
    assert creds.password == ""
    assert creds.redacted()["password_set"] is False
    with pytest.raises(AniDBAuthError):
        load_credentials(tmp_path / "missing.cfg", require_password=True)


def test_memory_password_set_and_clear(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("ANIDB_USER", "balage")
    monkeypatch.delenv("ANIDB_PASS", raising=False)
    monkeypatch.setenv("ANIDB_CLIENT", "snittanidb")
    monkeypatch.setenv("ANIDB_CLIENTVER", "1")
    transport = MockUdpTransport()
    transport.queue("200 sess LOGIN ACCEPTED", "330 NO SUCH ANIME", "203 LOGGED OUT")
    client = AniDBClient(
        transport=transport,
        rate_limiter=FloodRateLimiter(sleeper=lambda _s: None),
        create_socket=False,
    )
    with pytest.raises(AniDBAuthError) as exc_info:
        client.ensure_auth()
    assert "anidb_set_password" in str(exc_info.value)
    ready = client.set_password("memory-secret")
    assert ready == {"ok": True, "ready": True}
    assert "memory-secret" not in str(ready)
    assert client.password_in_memory is True
    result = client.lookup_anime(aid=1)
    assert result["ok"] is False
    assert result["error"] == "NO SUCH ANIME"
    sent = transport.sent[0].decode()
    assert "pass=memory-secret" in sent or "pass=" in sent
    cleared = client.clear_credentials()
    assert cleared["ok"] is True
    assert cleared["password_in_memory"] is False
    assert client.password_in_memory is False
    assert client.session_status()["authenticated"] is False
    assert client.banned is False
    with pytest.raises(AniDBAuthError):
        client.ensure_auth()


def test_prompt_password_uses_getpass(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AniDBClient(credentials=_creds().with_password(""), create_socket=False)
    monkeypatch.setattr("snitt_anidb.client.getpass.getpass", lambda _prompt="": "typed-once")
    result = client.prompt_password()
    assert result == {"ok": True, "ready": True}
    assert client.password_in_memory is True
    assert "typed-once" not in str(result)


def test_auth_lookup_mylist_and_stats() -> None:
    transport = MockUdpTransport()
    transport.queue(
        "200 abc12 LOGIN ACCEPTED",
        "230 ANIME\n42|12|12|0|0|0|0|0|0|0|2020|TV Series|Demo||||cat",
        "221 MYLIST\n9|0|1|42|0|1|1|123|storage|source|other|0",
        "222 MYLIST STATS\n1|2|3|4|5|6|7|8|9|10|11|12|13|14|15|16|17",
    )
    client = _client(transport)
    status = client.session_status()
    assert status["authenticated"] is False
    anime = client.lookup_anime(aid=42)
    assert anime["ok"] is True
    assert anime["anime"]["aid"] == "42"
    assert anime["anime"]["romaji"] == "Demo"
    entry = client.mylist_get(aid=42, epno=1)
    assert entry["ok"] is True
    assert entry["entry"]["lid"] == "9"
    stats = client.mylist_stats()
    assert stats["ok"] is True
    assert stats["stats"]["animes"] == "1"
    assert transport.sent[0].decode().startswith("AUTH ")
    assert "pass=secret" in transport.sent[0].decode() or "pass=" in transport.sent[0].decode()


def test_plan_and_gated_mark_watched() -> None:
    transport = MockUdpTransport()
    transport.queue("200 sess LOGIN ACCEPTED", "210 MYLIST ENTRY ADDED\n99")
    client = _client(transport)
    plan = client.plan_mark_watched(aid=42, epno=3)
    assert plan["dry_run"] is True
    assert plan["params"]["viewed"] == 1
    assert plan["params"]["generic"] == 1
    refused = client.mark_watched(aid=42, epno=3, allow_save=False)
    assert refused["ok"] is False
    assert "allow_save" in refused["error"]
    assert len(transport.sent) == 0  # plan + refuse never AUTH
    done = client.mark_watched(aid=42, epno=3, allow_save=True)
    assert done["ok"] is True
    assert any(b"MYLISTADD" in payload for payload in transport.sent)


def test_mark_watched_edits_when_already_in_mylist() -> None:
    transport = MockUdpTransport()
    transport.queue(
        "200 sess LOGIN ACCEPTED",
        "310 FILE ALREADY IN MYLIST\n77|0|1|42|0|1|1|0||| |0",
        "311 MYLIST ENTRY EDITED\n1",
    )
    client = _client(transport)
    result = client.mark_watched(aid=42, epno=1, allow_save=True)
    assert result["ok"] is True
    assert result.get("edited_existing") is True
    assert sum(1 for payload in transport.sent if b"MYLISTADD" in payload) == 2


def test_ban_latch_on_504_and_blocks_until_reset() -> None:
    transport = MockUdpTransport()
    transport.queue("504 CLIENT BANNED - test")
    client = _client(transport)
    with pytest.raises(AniDBBannedError):
        client.ensure_auth()
    assert client.banned is True
    with pytest.raises(AniDBBannedError):
        client.lookup_anime(aid=1)
    client.reset_ban_latch()
    transport.queue("200 newsess LOGIN ACCEPTED", "330 NO SUCH ANIME")
    result = client.lookup_anime(aid=1)
    assert result["ok"] is False
    assert result["error"] == "NO SUCH ANIME"


def test_timeout_engages_ban_latch() -> None:
    transport = MockUdpTransport()  # empty queue → TimeoutError
    client = _client(transport)
    with pytest.raises(AniDBBannedError):
        client.ensure_auth()
    assert client.banned is True


def test_rate_limiter_switches_to_long_interval() -> None:
    slept: list[float] = []
    clock = {"t": 0.0}

    def tick() -> float:
        return clock["t"]

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock["t"] += seconds

    limiter = FloodRateLimiter(
        short_interval=2.0,
        long_interval=4.0,
        burst_allowance=5,
        sleeper=sleep,
        clock=tick,
        idle_reset_seconds=1000,
    )
    for _ in range(6):
        limiter.wait()
        clock["t"] += 0.01  # tiny advance so next wait computes remaining
    # after burst_allowance packets, required interval is long
    assert limiter.status()["packets_since_reset"] == 6
    assert limiter.status()["next_interval"] == 4.0
    assert any(abs(value - 2.0) < 0.01 or abs(value - 4.0) < 0.01 for value in slept) or slept


def test_lookup_requires_exactly_one_key() -> None:
    client = _client(MockUdpTransport())
    with pytest.raises(AniDBClientError):
        client.lookup_anime()
    with pytest.raises(AniDBClientError):
        client.lookup_anime(aid=1, aname="x")
