"""UDP transport for AniDB (single local port; injectable for tests)."""

from __future__ import annotations

import socket
from typing import Protocol


DEFAULT_HOST = "api.anidb.net"
DEFAULT_PORT = 9000
DEFAULT_RECV_SIZE = 1400


class UdpTransport(Protocol):
    """Minimal send/receive surface used by :class:`AniDBClient`."""

    def send_and_recv(self, payload: bytes, timeout: float) -> bytes:
        """Send one datagram and return one reply datagram.

        :param bytes payload: Encoded command bytes.
        :param float timeout: Socket timeout in seconds.
        :rtype: bytes
        """

    def close(self) -> None:
        """Release the underlying socket / resources."""


class SocketUdpTransport:
    """Real UDP socket bound once and reused (one client/port per IP).

    :param str host: AniDB API host.
    :param int port: AniDB API UDP port.
    :param str | None local_host: Optional bind host.
    :param int local_port: Local bind port (0 = ephemeral, then reused).
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        local_host: str = "0.0.0.0",
        local_port: int = 0,
    ) -> None:
        self.host = host
        self.port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((local_host, local_port))

    def send_and_recv(self, payload: bytes, timeout: float) -> bytes:
        """Send ``payload`` and receive one reply.

        :param bytes payload: Command bytes (UTF-8).
        :param float timeout: Per-call timeout.
        :rtype: bytes
        :raises TimeoutError: On socket timeout.
        :raises OSError: On other socket errors.
        """
        self._sock.settimeout(timeout)
        self._sock.sendto(payload, (self.host, self.port))
        try:
            data, _addr = self._sock.recvfrom(DEFAULT_RECV_SIZE)
        except socket.timeout as exc:
            raise TimeoutError(f"AniDB UDP timeout after {timeout}s") from exc
        return data

    def close(self) -> None:
        """Close the UDP socket."""
        self._sock.close()


class MockUdpTransport:
    """Queue-based transport for offline unit tests (no network).

    :param list[bytes] | None replies: Optional initial reply queue.
    """

    def __init__(self, replies: list[bytes] | None = None) -> None:
        self.sent: list[bytes] = []
        self._replies = list(replies or [])
        self.closed = False

    def queue(self, *replies: str | bytes) -> None:
        """Append reply payloads (str encoded as UTF-8).

        :param str | bytes replies: Reply bodies in send order.
        """
        for reply in replies:
            self._replies.append(reply.encode("utf-8") if isinstance(reply, str) else reply)

    def send_and_recv(self, payload: bytes, timeout: float) -> bytes:
        """Record ``payload`` and pop the next queued reply.

        :param bytes payload: Outgoing command.
        :param float timeout: Ignored (kept for Protocol parity).
        :rtype: bytes
        :raises TimeoutError: If the reply queue is empty.
        """
        del timeout  # unused; signature matches Protocol
        self.sent.append(payload)
        if not self._replies:
            raise TimeoutError("MockUdpTransport: no queued reply (simulates ban/drop)")
        return self._replies.pop(0)

    def close(self) -> None:
        """Mark the mock closed."""
        self.closed = True

    def last_command(self) -> str:
        """Return the last sent command as UTF-8 text.

        :rtype: str
        """
        if not self.sent:
            return ""
        return self.sent[-1].decode("utf-8")
