"""AniDB UDP client: single session, flood pacing, ban latch, gated mylist writes."""

from __future__ import annotations

import getpass
import threading
from typing import Any
from urllib.parse import unquote

from snitt_anidb.protocol import (
    ANIME_CLASSIC_FIELDS,
    MYLIST_FIELDS,
    AniDBReply,
    encode_command,
    map_fields,
    parse_reply,
)
from snitt_anidb.rate_limit import FloodRateLimiter
from snitt_anidb.session import (
    PASSWORD_REQUIRED_MSG,
    AniDBAuthError,
    AniDBCredentials,
    load_credentials,
)
from snitt_anidb.transport import SocketUdpTransport, UdpTransport

# Ban / critical codes that latch the client until explicit reset.
BAN_CODES = frozenset({504, 555})
CRITICAL_CODES = frozenset({502})  # ACCESS DENIED — treat as latch-worthy
AUTH_OK = frozenset({200, 201})


class AniDBClientError(RuntimeError):
    """Raised for client validation or AniDB protocol failures."""


class AniDBBannedError(AniDBClientError):
    """Raised when the ban latch is set or a ban reply is received."""


class AniDBClient:
    """Paced AniDB UDP client with one shared session and a ban latch.

    Non-secret identity (user / client / clientver) comes from ENV/local config.
    Website password prefers process memory (``set_password`` / ``prompt_password``);
    ``ANIDB_PASS`` remains an optional temporary fallback. Live sockets are only
    created when a transport is not injected — tests should inject
    :class:`~snitt_anidb.transport.MockUdpTransport`.

    :param AniDBCredentials | None credentials: Optional explicit credentials.
    :param UdpTransport | None transport: Optional transport (tests / custom).
    :param FloodRateLimiter | None rate_limiter: Optional limiter (tests).
    :param float timeout: Per-packet recv timeout seconds.
    :param bool create_socket: When True and transport is None, open a real UDP socket.
    :param bool interactive: When True, missing password prompts via ``getpass`` once.
    """

    def __init__(
        self,
        credentials: AniDBCredentials | None = None,
        *,
        transport: UdpTransport | None = None,
        rate_limiter: FloodRateLimiter | None = None,
        timeout: float = 20.0,
        create_socket: bool = True,
        interactive: bool = False,
    ) -> None:
        self._credentials = credentials
        self._transport = transport
        self._owns_transport = transport is None and create_socket
        self._rate_limiter = rate_limiter or FloodRateLimiter()
        self._timeout = timeout
        self._create_socket = create_socket
        self._interactive = interactive
        self._lock = threading.RLock()
        self._session_key: str | None = None
        self._memory_password: str | None = None
        self._banned = False
        self._ban_reason: str | None = None
        self._last_reply: AniDBReply | None = None
        self._authed_user: str | None = None

    def close(self) -> None:
        """LOGOUT when possible and close the transport we own."""
        with self._lock:
            if self._session_key and self._transport is not None and not self._banned:
                try:
                    self._command("LOGOUT", require_auth=True, allow_when_banned=False)
                except Exception:  # noqa: BLE001 — best-effort logout
                    pass
            self._session_key = None
            if self._owns_transport and self._transport is not None:
                self._transport.close()
                self._transport = None

    def __enter__(self) -> AniDBClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- status / latch -------------------------------------------------

    @property
    def banned(self) -> bool:
        """Return whether the ban latch is engaged.

        :rtype: bool
        """
        return self._banned

    @property
    def password_in_memory(self) -> bool:
        """Return whether a website password is held in process memory.

        :rtype: bool
        """
        return bool(self._memory_password)

    def reset_ban_latch(self) -> dict[str, Any]:
        """Clear the ban latch so further calls may proceed (explicit only).

        Does not contact AniDB. Call only after the ban window has passed.

        :rtype: dict[str, Any]
        """
        with self._lock:
            self._banned = False
            self._ban_reason = None
            return {"ok": True, "banned": False, "message": "Ban latch cleared (local only)"}

    def set_password(self, password: str) -> dict[str, Any]:
        """Store the website password in process memory only (never disk/logs).

        Does not echo the password. Does not contact AniDB.

        :param str password: AniDB website password.
        :rtype: dict[str, Any]
        :raises AniDBAuthError: If password is empty.
        """
        if not isinstance(password, str) or not password:
            raise AniDBAuthError("Password must be a non-empty string")
        with self._lock:
            self._memory_password = password
            return {"ok": True, "ready": True}

    def prompt_password(self, prompt: str = "AniDB website password: ") -> dict[str, Any]:
        """Prompt once via ``getpass`` and store the result in process memory.

        Intended for interactive CLI use. Never logs or returns the password.

        :param str prompt: getpass prompt text.
        :rtype: dict[str, Any]
        """
        return self.set_password(getpass.getpass(prompt))

    def clear_credentials(self) -> dict[str, Any]:
        """Clear in-memory password and session (local logout; best-effort UDP LOGOUT).

        Does not write to disk. Does not echo secrets.

        :rtype: dict[str, Any]
        """
        with self._lock:
            if self._session_key and self._transport is not None and not self._banned:
                try:
                    self._command("LOGOUT", require_auth=True, allow_when_banned=False)
                except Exception:  # noqa: BLE001 — best-effort logout
                    pass
            self._memory_password = None
            self._session_key = None
            self._authed_user = None
            if self._credentials is not None and self._credentials.password:
                self._credentials = self._credentials.with_password("")
            return {
                "ok": True,
                "cleared": True,
                "authenticated": False,
                "password_in_memory": False,
            }

    def session_status(self, *, load_creds: bool = True) -> dict[str, Any]:
        """Return local session/rate-limit/ban state without sending packets.

        :param bool load_creds: Try loading credentials for a redacted summary.
        :rtype: dict[str, Any]
        """
        creds_info: dict[str, Any] | None = None
        creds_error: str | None = None
        if load_creds:
            try:
                # status must not require password; show redacted identity + flags
                base = self._load_identity()
                with self._lock:
                    effective = self._effective_password(base)
                creds_info = base.with_password(effective or "").redacted()
            except AniDBAuthError as exc:
                creds_error = str(exc)
        with self._lock:
            return {
                "ok": True,
                "authenticated": self._session_key is not None,
                "session_key_present": self._session_key is not None,
                "authed_user": self._authed_user,
                "banned": self._banned,
                "ban_reason": self._ban_reason,
                "password_in_memory": bool(self._memory_password),
                "credentials": creds_info,
                "credentials_error": creds_error,
                "rate_limit": self._rate_limiter.status(),
                "transport_ready": self._transport is not None,
                "last_reply": self._last_reply.to_dict() if self._last_reply else None,
            }

    # --- public API -----------------------------------------------------

    def ensure_auth(self) -> AniDBReply:
        """AUTH if needed; return the last AUTH reply or a synthetic logged-in reply.

        :rtype: AniDBReply
        :raises AniDBBannedError: If the ban latch is set.
        :raises AniDBClientError: On login failure.
        """
        with self._lock:
            self._ensure_not_banned()
            if self._session_key:
                return AniDBReply(code=200, message="LOGIN ACCEPTED (cached session)")
            return self._auth()

    def lookup_anime(self, *, aid: int | None = None, aname: str | None = None) -> dict[str, Any]:
        """Look up one anime by aid or exact name (ANIME; one paced packet).

        Fuzzy title search is intentionally not implemented (would flood or need
        an offline titles dump).

        :param int | None aid: AniDB anime id.
        :param str | None aname: Exact romaji/kanji/english/synonym/short name.
        :rtype: dict[str, Any]
        """
        if (aid is None) == (aname is None):
            raise AniDBClientError("Provide exactly one of aid or aname")
        params: dict[str, Any] = {"aid": aid} if aid is not None else {"aname": aname}
        reply = self._command("ANIME", params, require_auth=True)
        if reply.code == 330:
            return {"ok": False, "error": "NO SUCH ANIME", "reply": reply.to_dict()}
        if reply.code != 230:
            return {"ok": False, "error": reply.message, "reply": reply.to_dict()}
        anime = map_fields(ANIME_CLASSIC_FIELDS, reply.fields)
        return {"ok": True, "anime": anime, "reply": reply.to_dict()}

    def mylist_get(
        self,
        *,
        lid: int | None = None,
        fid: int | None = None,
        aid: int | None = None,
        aname: str | None = None,
        epno: int | None = None,
    ) -> dict[str, Any]:
        """Fetch a bounded MYLIST entry (by lid/fid/aid[/epno]; not a full dump).

        :param int | None lid: MyList id.
        :param int | None fid: File id.
        :param int | None aid: Anime id.
        :param str | None aname: Exact anime name.
        :param int | None epno: Optional episode number when querying by anime.
        :rtype: dict[str, Any]
        """
        params: dict[str, Any] = {}
        if lid is not None:
            params["lid"] = lid
        elif fid is not None:
            params["fid"] = fid
        elif aid is not None:
            params["aid"] = aid
            if epno is not None:
                params["epno"] = epno
        elif aname is not None:
            params["aname"] = aname
            if epno is not None:
                params["epno"] = epno
        else:
            raise AniDBClientError("Provide lid, fid, aid, or aname for mylist_get")
        reply = self._command("MYLIST", params, require_auth=True)
        if reply.code == 321:
            return {"ok": False, "error": "NO SUCH ENTRY", "reply": reply.to_dict()}
        if reply.code == 221:
            return {"ok": True, "entry": map_fields(MYLIST_FIELDS, reply.fields), "reply": reply.to_dict()}
        if reply.code in {312, 322}:
            return {
                "ok": True,
                "multiple": True,
                "code": reply.code,
                "data": reply.data,
                "fields": reply.fields,
                "reply": reply.to_dict(),
            }
        return {"ok": False, "error": reply.message, "reply": reply.to_dict()}

    def mylist_stats(self) -> dict[str, Any]:
        """Return MYLISTSTATS (single paced packet; summary only).

        :rtype: dict[str, Any]
        """
        reply = self._command("MYLISTSTATS", require_auth=True)
        if reply.code != 222:
            return {"ok": False, "error": reply.message, "reply": reply.to_dict()}
        names = (
            "animes",
            "eps",
            "files",
            "size_of_files",
            "added_animes",
            "added_eps",
            "added_files",
            "added_groups",
            "leech_pct",
            "glory_pct",
            "viewed_pct_of_db",
            "mylist_pct_of_db",
            "viewed_pct_of_mylist",
            "viewed_eps",
            "votes",
            "reviews",
            "viewed_length_minutes",
        )
        return {"ok": True, "stats": map_fields(names, reply.fields), "reply": reply.to_dict()}

    def plan_mark_watched(
        self,
        *,
        aid: int,
        epno: int,
        viewed: bool = True,
        state: int = 1,
        edit: bool = False,
        lid: int | None = None,
    ) -> dict[str, Any]:
        """Build a MYLISTADD preview without sending UDP.

        :param int aid: Anime id.
        :param int epno: Episode number (generic entry).
        :param bool viewed: Mark viewed (default True).
        :param int state: MyList state (default 1 = internal/HDD).
        :param bool edit: Use edit=1 instead of add.
        :param int | None lid: Optional mylist id for lid-based edit.
        :rtype: dict[str, Any]
        """
        params = self._mylistadd_params(
            aid=aid, epno=epno, viewed=viewed, state=state, edit=edit, lid=lid
        )
        command = encode_command("MYLISTADD", {**params, "s": "<session>"})
        return {
            "ok": True,
            "dry_run": True,
            "command": "MYLISTADD",
            "params": params,
            "preview": command,
            "note": "No UDP sent. Call mark_watched with allow_save=True after explicit approval.",
        }

    def mark_watched(
        self,
        *,
        aid: int,
        epno: int,
        allow_save: bool = False,
        viewed: bool = True,
        state: int = 1,
        edit: bool = False,
        lid: int | None = None,
        edit_if_exists: bool = True,
    ) -> dict[str, Any]:
        """MYLISTADD mark watched/unwatched; refuses unless ``allow_save`` is True.

        :param int aid: Anime id.
        :param int epno: Episode number.
        :param bool allow_save: Write gate (default False).
        :param bool viewed: Viewed flag.
        :param int state: MyList state.
        :param bool edit: Force edit mode.
        :param int | None lid: Optional lid for edit.
        :param bool edit_if_exists: On 310 FILE ALREADY IN MYLIST, retry with edit=1.
        :rtype: dict[str, Any]
        """
        plan = self.plan_mark_watched(
            aid=aid, epno=epno, viewed=viewed, state=state, edit=edit, lid=lid
        )
        if not allow_save:
            return {
                "ok": False,
                "error": "Refusing write without allow_save=True",
                "dry_run_hint": "Use plan_mark_watched / anidb_plan_mark_watched first",
                "plan": plan,
            }
        params = self._mylistadd_params(
            aid=aid, epno=epno, viewed=viewed, state=state, edit=edit, lid=lid
        )
        reply = self._command("MYLISTADD", params, require_auth=True)
        if reply.code == 310 and edit_if_exists and not edit:
            # already present — edit viewed flag using lid when available
            existing = map_fields(MYLIST_FIELDS, reply.fields)
            edit_lid = int(existing["lid"]) if existing.get("lid", "").isdigit() else None
            edit_params = self._mylistadd_params(
                aid=aid,
                epno=epno,
                viewed=viewed,
                state=state,
                edit=True,
                lid=edit_lid,
            )
            reply = self._command("MYLISTADD", edit_params, require_auth=True)
            return {
                "ok": reply.code in {210, 311},
                "edited_existing": True,
                "reply": reply.to_dict(),
                "plan": plan,
            }
        return {
            "ok": reply.code in {210, 311},
            "reply": reply.to_dict(),
            "plan": plan,
            "entry": map_fields(MYLIST_FIELDS, reply.fields) if reply.fields else None,
        }

    # --- internals ------------------------------------------------------

    @staticmethod
    def _mylistadd_params(
        *,
        aid: int,
        epno: int,
        viewed: bool,
        state: int,
        edit: bool,
        lid: int | None,
    ) -> dict[str, Any]:
        if lid is not None and edit:
            return {
                "lid": lid,
                "edit": 1,
                "viewed": 1 if viewed else 0,
                "state": state,
            }
        params: dict[str, Any] = {
            "aid": aid,
            "generic": 1,
            "epno": epno,
            "viewed": 1 if viewed else 0,
            "state": state,
        }
        if edit:
            params["edit"] = 1
        return params

    def _load_identity(self) -> AniDBCredentials:
        if self._credentials is not None:
            return self._credentials
        return load_credentials(require_password=False)

    def _effective_password(self, base: AniDBCredentials) -> str:
        if self._memory_password:
            return self._memory_password
        return base.password or ""

    def _get_credentials(self) -> AniDBCredentials:
        base = self._load_identity()
        password = self._effective_password(base)
        if not password and self._interactive:
            self.prompt_password()
            password = self._memory_password or ""
        if not password:
            raise AniDBAuthError(PASSWORD_REQUIRED_MSG)
        return base.with_password(password)

    def _ensure_transport(self) -> UdpTransport:
        if self._transport is not None:
            return self._transport
        if not self._create_socket:
            raise AniDBClientError(
                "No UDP transport: inject MockUdpTransport for tests, "
                "or construct with create_socket=True for live use."
            )
        self._transport = SocketUdpTransport()
        self._owns_transport = True
        return self._transport

    def _ensure_not_banned(self) -> None:
        if self._banned:
            raise AniDBBannedError(
                f"AniDB ban latch is set ({self._ban_reason or 'unknown'}). "
                "Call reset_ban_latch() only after the ban window; do not retry blindly."
            )

    def _engage_ban(self, reason: str) -> None:
        self._banned = True
        self._ban_reason = reason
        self._session_key = None

    def _auth(self) -> AniDBReply:
        creds = self._get_credentials()
        params = {
            "user": creds.user,
            "pass": creds.password,
            "protover": creds.protover,
            "client": creds.client,
            "clientver": creds.clientver,
            "enc": "UTF-8",
        }
        reply = self._command("AUTH", params, require_auth=False)
        if reply.code in AUTH_OK:
            # "200 {session} LOGIN ACCEPTED" — session is first token of message
            token = reply.message.split()[0] if reply.message else ""
            if not token or token.upper().startswith("LOGIN"):
                raise AniDBClientError(f"AUTH ok but no session key in: {reply.message!r}")
            self._session_key = token
            self._authed_user = creds.user
            return reply
        if reply.code in BAN_CODES:
            self._engage_ban(f"{reply.code} {reply.message}")
            raise AniDBBannedError(self._ban_reason or "banned")
        raise AniDBClientError(f"AUTH failed: {reply.code} {reply.message}")

    def _command(
        self,
        command: str,
        params: dict[str, Any] | None = None,
        *,
        require_auth: bool = True,
        allow_when_banned: bool = False,
    ) -> AniDBReply:
        with self._lock:
            if not allow_when_banned:
                self._ensure_not_banned()
            if require_auth and command != "AUTH":
                if not self._session_key:
                    self._auth()
            send_params = dict(params or {})
            if require_auth and self._session_key and command != "AUTH":
                send_params["s"] = self._session_key
            body = encode_command(command, send_params)
            transport = self._ensure_transport()
            self._rate_limiter.wait()
            try:
                raw = transport.send_and_recv(body.encode("utf-8"), self._timeout)
            except TimeoutError as exc:
                self._engage_ban(f"UDP timeout / possible ban: {exc}")
                raise AniDBBannedError(self._ban_reason or str(exc)) from exc
            try:
                reply = parse_reply(raw.decode("utf-8", errors="replace"))
            except ValueError as exc:
                self._engage_ban(f"Unparseable reply (possible ban/drop): {exc}")
                raise AniDBBannedError(self._ban_reason or str(exc)) from exc
            self._last_reply = reply
            if reply.code in BAN_CODES or reply.code in CRITICAL_CODES:
                self._engage_ban(f"{reply.code} {reply.message}")
                raise AniDBBannedError(self._ban_reason or reply.message)
            if reply.code == 501 and command != "AUTH":
                # LOGIN FIRST — re-auth once
                self._session_key = None
                self._auth()
                send_params["s"] = self._session_key
                body = encode_command(command, send_params)
                self._rate_limiter.wait()
                raw = transport.send_and_recv(body.encode("utf-8"), self._timeout)
                reply = parse_reply(raw.decode("utf-8", errors="replace"))
                self._last_reply = reply
                if reply.code in BAN_CODES:
                    self._engage_ban(f"{reply.code} {reply.message}")
                    raise AniDBBannedError(self._ban_reason or reply.message)
            if reply.code == 506 and command != "AUTH":
                self._session_key = None
                self._auth()
                send_params["s"] = self._session_key
                body = encode_command(command, send_params)
                self._rate_limiter.wait()
                raw = transport.send_and_recv(body.encode("utf-8"), self._timeout)
                reply = parse_reply(raw.decode("utf-8", errors="replace"))
                self._last_reply = reply
            return reply


def decode_sent_command(payload: bytes) -> str:
    """Helper for tests: UTF-8 decode a sent datagram.

    :param bytes payload: Sent bytes.
    :rtype: str
    """
    return unquote(payload.decode("utf-8"))
