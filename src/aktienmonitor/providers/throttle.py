"""Rate-Limiting und Wiederholversuche.

Der Token-Bucket begrenzt die Aufrufe je Quelle und Minute; ``call_with_retry``
wiederholt fehlgeschlagene Aufrufe mit exponentiell wachsender Wartezeit. Beides
zusammen haelt die App innerhalb der Free-Tier-Grenzen der Anbieter.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger("aktienmonitor.throttle")

T = TypeVar("T")


class RateLimitExceeded(RuntimeError):
    """Die Gegenstelle hat mit 429 geantwortet."""


class AccessForbidden(RuntimeError):
    """Endpunkt ist fuer diesen Key gesperrt (typisch: Free-Tier, HTTP 403)."""


class TokenBucket:
    """Klassischer Token-Bucket: ``rate_per_minute`` Tokens pro Minute."""

    def __init__(self, rate_per_minute: int, *, capacity: int | None = None) -> None:
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute muss groesser als 0 sein")
        self.rate_per_second = rate_per_minute / 60.0
        self.capacity = float(capacity if capacity is not None else rate_per_minute)
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self, now: float) -> None:
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate_per_second)
            self._updated = now

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Entnimmt Tokens, wenn verfuegbar - ohne zu warten."""
        with self._lock:
            self._refill(time.monotonic())
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def acquire(self, tokens: float = 1.0, *, timeout: float | None = None) -> float:
        """Wartet, bis Tokens frei sind. Gibt die Wartezeit in Sekunden zurueck."""
        deadline = None if timeout is None else time.monotonic() + timeout
        waited = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                self._refill(now)
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return waited
                needed = (tokens - self._tokens) / self.rate_per_second
            if deadline is not None and time.monotonic() + needed > deadline:
                raise TimeoutError("Rate-Limit-Fenster nicht rechtzeitig frei geworden")
            sleep_for = min(needed, 1.0)
            time.sleep(sleep_for)
            waited += sleep_for


class ThrottleRegistry:
    """Ein Token-Bucket je Datenquelle."""

    def __init__(self, limits: dict[str, int]) -> None:
        self._buckets = {name: TokenBucket(rate) for name, rate in limits.items() if rate > 0}

    def acquire(self, source: str, tokens: float = 1.0) -> float:
        bucket = self._buckets.get(source)
        if bucket is None:
            return 0.0
        waited = bucket.acquire(tokens)
        if waited > 0.5:
            logger.info("Throttling %s: %.1f s gewartet", source, waited)
        return waited


def call_with_retry(
    func: Callable[[], T],
    *,
    max_attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: tuple[type[Exception], ...] = (RateLimitExceeded, ConnectionError, TimeoutError),
    label: str = "",
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Fuehrt ``func`` aus und wiederholt bei bestimmten Fehlern mit Backoff.

    Die Wartezeit waechst exponentiell (1s, 2s, 4s, ...) und erhaelt einen
    zufaelligen Aufschlag, damit parallele Abrufe nicht im Gleichtakt erneut
    anklopfen. ``AccessForbidden`` wird bewusst *nicht* wiederholt - ein
    gesperrter Endpunkt wird durch Warten nicht frei.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts muss mindestens 1 sein")

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except AccessForbidden:
            raise
        except retry_on as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay += random.uniform(0, delay * 0.25)
            logger.warning(
                "Versuch %d/%d fuer %s fehlgeschlagen (%s) - neuer Versuch in %.1f s",
                attempt,
                max_attempts,
                label or "Abruf",
                exc,
                delay,
            )
            sleep(delay)

    assert last_error is not None
    raise last_error
