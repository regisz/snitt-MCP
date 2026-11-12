"""AniDB UDP flood protection (~1 pkt/2s after burst start, ~1/4s sustained)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class FloodRateLimiter:
    """Serialize and pace UDP packets per AniDB flood rules.

    Short term: at most one packet every ``short_interval`` seconds; enforcement
    begins after the first ``burst_allowance`` packets. Sustained: one packet
    every ``long_interval`` seconds. Idle for ``idle_reset_seconds`` resets the
    sustained counter. Thread-safe for a single shared client/session.

    :param float short_interval: Minimum spacing after the initial burst window (wiki: 2s).
    :param float long_interval: Sustained spacing (wiki: 4s).
    :param int burst_allowance: Packets before sustained (long) spacing applies (wiki: 5).
    :param float idle_reset_seconds: Idle time that resets the packet counter (default 30 min).
    :param Callable[[float], None] sleeper: Injected sleep (tests).
    :param Callable[[], float] clock: Injected monotonic clock (tests).
    """

    def __init__(
        self,
        *,
        short_interval: float = 2.0,
        long_interval: float = 4.0,
        burst_allowance: int = 5,
        idle_reset_seconds: float = 1800.0,
        sleeper: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.short_interval = short_interval
        self.long_interval = long_interval
        self.burst_allowance = burst_allowance
        self.idle_reset_seconds = idle_reset_seconds
        self._sleep = sleeper or time.sleep
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._packets_since_reset = 0
        self._last_send_at: float | None = None

    def status(self) -> dict[str, float | int | None]:
        """Return limiter counters for session status tools.

        :rtype: dict[str, float | int | None]
        """
        with self._lock:
            return {
                "packets_since_reset": self._packets_since_reset,
                "last_send_at": self._last_send_at,
                "short_interval": self.short_interval,
                "long_interval": self.long_interval,
                "burst_allowance": self.burst_allowance,
                "next_interval": self._required_interval_unlocked(),
            }

    def _required_interval_unlocked(self) -> float:
        if self._packets_since_reset >= self.burst_allowance:
            return self.long_interval
        # wiki: limit enforced after first 5; still space early packets by short_interval
        if self._packets_since_reset > 0:
            return self.short_interval
        return 0.0

    def wait(self) -> None:
        """Block until the next packet may be sent, then record the send."""
        with self._lock:
            now = self._clock()
            if self._last_send_at is not None and (now - self._last_send_at) >= self.idle_reset_seconds:
                self._packets_since_reset = 0
            interval = self._required_interval_unlocked()
            if self._last_send_at is not None and interval > 0:
                remaining = interval - (now - self._last_send_at)
                if remaining > 0:
                    self._sleep(remaining)
                    now = self._clock()
            self._last_send_at = now
            self._packets_since_reset += 1
