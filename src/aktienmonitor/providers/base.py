"""Gemeinsames Gerüst aller Datenquellen-Adapter.

``ProviderRuntime`` buendelt die vier Dinge, die jeder Abruf braucht: Cache,
Rate-Limit, Wiederholversuche und Protokollierung. Die konkreten Adapter
kuemmern sich nur noch um das Umwandeln der Anbieter-Antwort.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..models import Provenance, ProviderResult
from ..storage.cache import Cache, build_key
from ..storage.call_log import (
    STATUS_ERROR,
    STATUS_FORBIDDEN,
    STATUS_NOT_FOUND,
    STATUS_OK,
    STATUS_RATE_LIMITED,
    CallLog,
)
from .throttle import AccessForbidden, RateLimitExceeded, ThrottleRegistry, call_with_retry

logger = logging.getLogger("aktienmonitor.providers")


class SourceUnavailable(RuntimeError):
    """Die Quelle ist nicht nutzbar (z.B. fehlender API-Key)."""


def jsonable(value: Any) -> Any:
    """Wandelt Anbieter-Objekte in JSON-taugliche Strukturen.

    NaN und Inf werden zu ``None`` - ein fehlender Wert bleibt so auch nach dem
    Cachen ein fehlender Wert und wird nicht stillschweigend zu 0.
    """
    if value is None:
        return None
    if isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [jsonable(v) for v in value]
    # numpy-Skalare und aehnliches
    if hasattr(value, "item"):
        try:
            return jsonable(value.item())
        except (ValueError, AttributeError):
            pass
    return str(value)


def frame_to_payload(frame: Any) -> dict[str, Any] | None:
    """Serialisiert einen pandas-DataFrame verlustarm.

    Ergebnis: ``{"columns": [...], "index": [...], "rows": {index: [werte]}}``.
    """
    if frame is None:
        return None
    try:
        if frame.empty:
            return None
    except AttributeError:
        return None
    columns = [jsonable(c) for c in frame.columns]
    index = [jsonable(i) for i in frame.index]
    rows: dict[str, list[Any]] = {}
    for label, series in frame.iterrows():
        rows[str(jsonable(label))] = [jsonable(v) for v in series.tolist()]
    return {"columns": columns, "index": index, "rows": rows}


def series_to_payload(series: Any) -> dict[str, Any] | None:
    """Serialisiert eine pandas-Series als ``{index: wert}``."""
    if series is None:
        return None
    try:
        if series.empty:
            return None
    except AttributeError:
        return None
    return {str(jsonable(i)): jsonable(v) for i, v in series.items()}


@dataclass
class ProviderRuntime:
    """Fuehrt Abrufe cache-, limit- und protokollbewusst aus."""

    cache: Cache
    call_log: CallLog
    throttle: ThrottleRegistry
    ttl_seconds: dict[str, int]
    retry_max_attempts: int = 4

    def fetch(
        self,
        *,
        source: Provenance,
        source_key: str,
        endpoint: str,
        ticker: str | None,
        data_kind: str,
        loader: Callable[[], Any],
        cache_parts: tuple[str, ...] = (),
        force_refresh: bool = False,
        ttl_override: int | None = None,
        cache_only: bool = False,
    ) -> ProviderResult:
        """Holt Daten - erst aus dem Cache, sonst von der Quelle.

        Schlaegt der Live-Abruf fehl, wird ein abgelaufener Cache-Eintrag als
        Rueckfallebene genutzt und ueber ``age_seconds`` als alt ausgewiesen.

        Mit ``cache_only`` unterbleibt jeder Netzzugriff. Das wird gebraucht, wo
        viele Titel auf einmal betrachtet werden (Sektorvergleich), ohne dass
        ungewollt Dutzende Abrufe gegen das Rate-Limit laufen.
        """
        cache_key = build_key(source_key, endpoint, ticker, *cache_parts)
        ttl = ttl_override if ttl_override is not None else self.ttl_seconds.get(data_kind, 3600)

        if not force_refresh:
            entry = self.cache.get(cache_key)
            if entry is not None:
                self.call_log.record(
                    source=source_key,
                    endpoint=endpoint,
                    ticker=ticker,
                    cache_hit=True,
                    status=STATUS_OK,
                )
                return ProviderResult(
                    data=entry.payload,
                    source=source,
                    fetched_at=entry.fetched_at,
                    from_cache=True,
                    age_seconds=entry.age_seconds,
                )

        if cache_only:
            # Auch ein abgelaufener Stand ist hier brauchbar - er wird ueber
            # ``age_seconds`` als alt ausgewiesen.
            stale = self.cache.get(cache_key, allow_stale=True)
            if stale is not None:
                return ProviderResult(
                    data=stale.payload,
                    source=source,
                    fetched_at=stale.fetched_at,
                    from_cache=True,
                    age_seconds=stale.age_seconds,
                )
            return ProviderResult(
                data=None,
                source=source,
                fetched_at=datetime.now(UTC),
                from_cache=False,
                error="Nicht im Cache und kein Abruf angefordert",
            )

        self.throttle.acquire(source_key)
        started = time.monotonic()
        try:
            payload = call_with_retry(
                loader,
                max_attempts=self.retry_max_attempts,
                label=f"{source_key}/{endpoint}/{ticker or '-'}",
            )
        except Exception as exc:  # noqa: BLE001 - Fehler wird als Ergebnis weitergereicht
            duration = int((time.monotonic() - started) * 1000)
            status = _status_for(exc)
            self.call_log.record(
                source=source_key,
                endpoint=endpoint,
                ticker=ticker,
                cache_hit=False,
                status=status,
                duration_ms=duration,
                error=f"{type(exc).__name__}: {exc}",
            )
            stale = self.cache.get(cache_key, allow_stale=True)
            if stale is not None:
                logger.warning(
                    "%s/%s fuer %s fehlgeschlagen - nutze veralteten Cache-Stand (%.0f s alt)",
                    source_key,
                    endpoint,
                    ticker or "-",
                    stale.age_seconds,
                )
                return ProviderResult(
                    data=stale.payload,
                    source=source,
                    fetched_at=stale.fetched_at,
                    from_cache=True,
                    age_seconds=stale.age_seconds,
                    error=None,
                )
            return ProviderResult(
                data=None,
                source=source,
                fetched_at=datetime.now(UTC),
                from_cache=False,
                error=f"{type(exc).__name__}: {exc}",
            )

        duration = int((time.monotonic() - started) * 1000)
        self.call_log.record(
            source=source_key,
            endpoint=endpoint,
            ticker=ticker,
            cache_hit=False,
            status=STATUS_OK if payload is not None else STATUS_NOT_FOUND,
            duration_ms=duration,
        )

        fetched_at = datetime.now(UTC)
        if payload is not None:
            entry = self.cache.set(
                cache_key,
                payload,
                source=source_key,
                data_kind=data_kind,
                ttl_seconds=ttl,
                ticker=ticker,
            )
            fetched_at = entry.fetched_at

        return ProviderResult(
            data=payload,
            source=source,
            fetched_at=fetched_at,
            from_cache=False,
            age_seconds=0.0,
            error=None if payload is not None else "Keine Daten geliefert",
        )


def _status_for(exc: Exception) -> str:
    if isinstance(exc, AccessForbidden):
        return STATUS_FORBIDDEN
    if isinstance(exc, RateLimitExceeded):
        return STATUS_RATE_LIMITED
    return STATUS_ERROR
