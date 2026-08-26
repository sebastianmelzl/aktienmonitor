"""Adapter fuer die Finnhub-REST-API.

Ergaenzende Quelle: Realtime-Quote, Firmenprofil, Basis-Kennzahlen und
Unternehmens-News - im Free-Tier im Wesentlichen fuer US-Titel. Historische
Kurse, Analystendaten und News-Sentiment sind im Free-Tier gesperrt und
antworten mit HTTP 403; das wird als ``AccessForbidden`` sauber weitergereicht
und fuehrt zu einem ausgewiesenen "n/a", nicht zu einem Ersatzwert.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from ..config import (
    DATA_KIND_ANALYST,
    DATA_KIND_FUNDAMENTALS,
    DATA_KIND_NEWS,
    DATA_KIND_PROFILE,
    DATA_KIND_QUOTE,
)
from ..models import Provenance, ProviderResult
from .base import ProviderRuntime, SourceUnavailable, jsonable
from .throttle import AccessForbidden, RateLimitExceeded

logger = logging.getLogger("aktienmonitor.providers.finnhub")

SOURCE_KEY = "finnhub"
BASE_URL = "https://finnhub.io/api/v1"
REQUEST_TIMEOUT = 15


class InvalidApiKey(RuntimeError):
    """Der hinterlegte Finnhub-Key wurde abgelehnt (HTTP 401)."""


class FinnhubSource:
    """Kapselt alle Finnhub-Zugriffe."""

    source = Provenance.FINNHUB
    source_key = SOURCE_KEY

    def __init__(self, runtime: ProviderRuntime, api_key: str | None) -> None:
        self.runtime = runtime
        self.api_key = api_key
        self._session: requests.Session | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": "aktienmonitor/0.1"})
        return self._session

    def request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Fuehrt einen rohen API-Aufruf aus und uebersetzt HTTP-Fehler in Exceptions."""
        if not self.api_key:
            raise SourceUnavailable("Kein Finnhub-API-Key hinterlegt (FINNHUB_API_KEY in .env)")

        query = dict(params or {})
        query["token"] = self.api_key
        try:
            response = self._get_session().get(
                f"{BASE_URL}{path}", params=query, timeout=REQUEST_TIMEOUT
            )
        except requests.Timeout as exc:
            raise TimeoutError(f"Finnhub-Zeitueberschreitung bei {path}") from exc
        except requests.RequestException as exc:
            raise ConnectionError(f"Finnhub nicht erreichbar: {exc}") from exc

        if response.status_code == 401:
            raise InvalidApiKey("Finnhub hat den API-Key abgelehnt (HTTP 401)")
        if response.status_code == 403:
            raise AccessForbidden(f"{path} ist fuer diesen Key gesperrt (HTTP 403, Free-Tier)")
        if response.status_code == 429:
            raise RateLimitExceeded("Finnhub-Rate-Limit erreicht (HTTP 429)")
        if response.status_code >= 500:
            raise ConnectionError(f"Finnhub-Serverfehler {response.status_code} bei {path}")
        if response.status_code != 200:
            raise RuntimeError(f"Finnhub antwortete mit HTTP {response.status_code} bei {path}")

        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"Finnhub lieferte kein gueltiges JSON bei {path}") from exc

    # --- Endpunkte -----------------------------------------------------------

    def quote(self, ticker: str, *, force_refresh: bool = False) -> ProviderResult:
        def load() -> dict[str, Any] | None:
            data = self.request("/quote", {"symbol": ticker})
            # Finnhub liefert fuer unbekannte Symbole ein Objekt aus lauter Nullen.
            if not isinstance(data, dict) or not data.get("c"):
                return None
            return {
                "current": jsonable(data.get("c")),
                "change": jsonable(data.get("d")),
                "change_percent": jsonable(data.get("dp")),
                "high": jsonable(data.get("h")),
                "low": jsonable(data.get("l")),
                "open": jsonable(data.get("o")),
                "previous_close": jsonable(data.get("pc")),
                "timestamp": jsonable(data.get("t")),
            }

        return self.runtime.fetch(
            source=self.source, source_key=self.source_key, endpoint="/quote", ticker=ticker,
            data_kind=DATA_KIND_QUOTE, loader=load, force_refresh=force_refresh,
        )

    def profile(self, ticker: str, *, force_refresh: bool = False) -> ProviderResult:
        def load() -> dict[str, Any] | None:
            data = self.request("/stock/profile2", {"symbol": ticker})
            return jsonable(data) if isinstance(data, dict) and data else None

        return self.runtime.fetch(
            source=self.source, source_key=self.source_key, endpoint="/stock/profile2",
            ticker=ticker, data_kind=DATA_KIND_PROFILE, loader=load, force_refresh=force_refresh,
        )

    def basic_financials(self, ticker: str, *, force_refresh: bool = False) -> ProviderResult:
        """``/stock/metric`` - Sammelendpunkt mit vielen Kennzahlen in einem Aufruf."""

        def load() -> dict[str, Any] | None:
            data = self.request("/stock/metric", {"symbol": ticker, "metric": "all"})
            if not isinstance(data, dict) or not data.get("metric"):
                return None
            return {"metric": jsonable(data.get("metric")), "series": jsonable(data.get("series"))}

        return self.runtime.fetch(
            source=self.source, source_key=self.source_key, endpoint="/stock/metric",
            ticker=ticker, data_kind=DATA_KIND_FUNDAMENTALS, loader=load,
            force_refresh=force_refresh,
        )

    def recommendations(self, ticker: str, *, force_refresh: bool = False) -> ProviderResult:
        def load() -> list[dict[str, Any]] | None:
            data = self.request("/stock/recommendation", {"symbol": ticker})
            return jsonable(data) if isinstance(data, list) and data else None

        return self.runtime.fetch(
            source=self.source, source_key=self.source_key, endpoint="/stock/recommendation",
            ticker=ticker, data_kind=DATA_KIND_ANALYST, loader=load, force_refresh=force_refresh,
        )

    def price_target(self, ticker: str, *, force_refresh: bool = False) -> ProviderResult:
        def load() -> dict[str, Any] | None:
            data = self.request("/stock/price-target", {"symbol": ticker})
            if not isinstance(data, dict) or not data.get("targetMean"):
                return None
            return jsonable(data)

        return self.runtime.fetch(
            source=self.source, source_key=self.source_key, endpoint="/stock/price-target",
            ticker=ticker, data_kind=DATA_KIND_ANALYST, loader=load, force_refresh=force_refresh,
        )

    def earnings_surprises(self, ticker: str, *, force_refresh: bool = False) -> ProviderResult:
        def load() -> list[dict[str, Any]] | None:
            data = self.request("/stock/earnings", {"symbol": ticker})
            return jsonable(data) if isinstance(data, list) and data else None

        return self.runtime.fetch(
            source=self.source, source_key=self.source_key, endpoint="/stock/earnings",
            ticker=ticker, data_kind=DATA_KIND_ANALYST, loader=load, force_refresh=force_refresh,
        )

    def company_news(
        self, ticker: str, *, days: int = 14, force_refresh: bool = False
    ) -> ProviderResult:
        def load() -> list[dict[str, Any]] | None:
            today = datetime.now(UTC).date()
            data = self.request(
                "/company-news",
                {
                    "symbol": ticker,
                    "from": (today - timedelta(days=days)).isoformat(),
                    "to": today.isoformat(),
                },
            )
            return jsonable(data) if isinstance(data, list) and data else None

        return self.runtime.fetch(
            source=self.source, source_key=self.source_key, endpoint="/company-news",
            ticker=ticker, data_kind=DATA_KIND_NEWS, loader=load, cache_parts=(str(days),),
            force_refresh=force_refresh,
        )
