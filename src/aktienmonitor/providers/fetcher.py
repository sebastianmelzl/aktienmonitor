"""Orchestrierung des Datenabrufs.

Buendelt die Adapter zu einem ``StockSnapshot`` je Titel. Fuer jeden Teilbereich
wird festgehalten, aus welcher Quelle er stammt, wann er abgerufen wurde und ob
er aus dem Cache kam - diese Angaben zeigt die Oberflaeche an.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..config import Config
from ..metrics.analyst import compute_analyst_metrics
from ..metrics.fundamental import compute_fundamental_metrics
from ..metrics.technical import compute_technical_metrics
from ..models import (
    MetricSet,
    NewsItem,
    Provenance,
    ProviderResult,
    SecurityProfile,
)
from ..narrative.generator import NarrativeGenerator
from ..sentiment.classifier import SentimentClassifier
from ..sentiment.metrics import compute_sentiment_metrics
from ..storage.cache import Cache
from ..storage.call_log import CallLog
from ..storage.db import Database
from ..storage.history import ScoreHistory
from .base import ProviderRuntime
from .finnhub_source import FinnhubSource
from .screener import MarketScreener
from .throttle import ThrottleRegistry
from .yfinance_source import YFinanceSource

logger = logging.getLogger("aktienmonitor.fetcher")


@dataclass(frozen=True)
class DataFreshness:
    """Herkunft und Alter eines Teilbereichs."""

    label: str
    source: Provenance
    fetched_at: datetime | None
    from_cache: bool
    error: str | None = None

    @property
    def age_text(self) -> str:
        if self.fetched_at is None:
            return "nicht abgerufen"
        seconds = (datetime.now(UTC) - self.fetched_at).total_seconds()
        if seconds < 90:
            return "gerade eben"
        if seconds < 3600:
            return f"vor {int(seconds // 60)} Min."
        if seconds < 86_400:
            return f"vor {int(seconds // 3600)} Std."
        return f"vor {int(seconds // 86_400)} Tg."


@dataclass
class StockSnapshot:
    """Vollstaendiger Datenstand eines Titels zu einem Zeitpunkt."""

    ticker: str
    profile: SecurityProfile
    price: float | None = None
    previous_close: float | None = None
    currency: str | None = None
    bars: list[dict] = field(default_factory=list)
    fundamental: MetricSet = field(default_factory=lambda: MetricSet({}))
    technical: MetricSet = field(default_factory=lambda: MetricSet({}))
    analyst: MetricSet = field(default_factory=lambda: MetricSet({}))
    sentiment: MetricSet = field(default_factory=lambda: MetricSet({}))
    news: list[NewsItem] = field(default_factory=list)
    freshness: list[DataFreshness] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def change_percent(self) -> float | None:
        if self.price is None or not self.previous_close:
            return None
        return (self.price / self.previous_close - 1.0) * 100.0

    @property
    def oldest_fetch(self) -> datetime | None:
        stamps = [f.fetched_at for f in self.freshness if f.fetched_at is not None]
        return min(stamps) if stamps else None

    @property
    def has_any_data(self) -> bool:
        return bool(self.bars) or len(self.fundamental.available) > 0 or self.price is not None


class StockDataService:
    """Zentrale Anlaufstelle fuer Titel-Daten."""

    def __init__(self, config: Config, db: Database | None = None) -> None:
        self.config = config
        self.db = db or Database(config.db_path)
        self.cache = Cache(self.db)
        self.call_log = CallLog(self.db)
        self.history = ScoreHistory(self.db)
        self.runtime = ProviderRuntime(
            cache=self.cache,
            call_log=self.call_log,
            throttle=ThrottleRegistry(config.rate_limit_per_min),
            ttl_seconds=config.ttl_seconds,
            retry_max_attempts=config.retry_max_attempts,
        )
        self.yfinance = YFinanceSource(self.runtime)
        self.screener = MarketScreener(self.runtime)
        self.finnhub = FinnhubSource(self.runtime, config.finnhub_api_key)
        self.classifier = SentimentClassifier(
            config.anthropic_api_key, self.cache, model=config.anthropic_model
        )
        self.narrator = NarrativeGenerator(
            config.anthropic_api_key, self.cache, model=config.anthropic_model
        )

    # --- oeffentliche Schnittstelle -----------------------------------------

    def get_snapshot(
        self,
        ticker: str,
        *,
        force_refresh: bool = False,
        history_period: str = "5y",
        cache_only: bool = False,
        with_news: bool = True,
    ) -> StockSnapshot:
        """Holt alle Daten eines Titels und berechnet die Kennzahlen.

        Mit ``cache_only`` werden ausschliesslich bereits gespeicherte Daten
        verwendet. Das ist die Betriebsart fuer den Sektorvergleich, der viele
        Titel auf einmal braucht und dabei keine Abrufwelle ausloesen darf.
        """
        ticker = ticker.upper()
        if force_refresh:
            self.cache.invalidate_ticker(ticker)

        freshness: list[DataFreshness] = []
        errors: list[str] = []

        def track(label: str, result: ProviderResult) -> Any:
            freshness.append(
                DataFreshness(
                    label=label,
                    source=result.source,
                    fetched_at=result.fetched_at if result.ok else None,
                    from_cache=result.from_cache,
                    error=result.error,
                )
            )
            if result.error:
                errors.append(f"{label}: {result.error}")
            return result.data if result.ok else None

        info = track(
            "Stammdaten",
            self.yfinance.profile(ticker, force_refresh=force_refresh, cache_only=cache_only),
        ) or {}
        quote = track(
            "Kurs",
            self.yfinance.quote(ticker, force_refresh=force_refresh, cache_only=cache_only),
        ) or {}
        history = track(
            "Kurshistorie",
            self.yfinance.price_history(
                ticker, period=history_period, force_refresh=force_refresh, cache_only=cache_only
            ),
        ) or {}
        statements = track(
            "Abschluesse",
            self.yfinance.fundamentals(ticker, force_refresh=force_refresh, cache_only=cache_only),
        )
        analyst_payload = track(
            "Analysten",
            self.yfinance.analyst(ticker, force_refresh=force_refresh, cache_only=cache_only),
        )

        profile = self._build_profile(ticker, info, quote)

        # Finnhub nur ergaenzend - und nur, wenn ein Key hinterlegt ist.
        finnhub_metric: dict[str, Any] = {}
        if self.finnhub.available:
            finnhub_data = track(
                "Finnhub-Kennzahlen",
                self.finnhub.basic_financials(
                    ticker, force_refresh=force_refresh, cache_only=cache_only
                ),
            )
            if isinstance(finnhub_data, dict):
                finnhub_metric = finnhub_data.get("metric") or {}

        bars = history.get("bars", []) if isinstance(history, dict) else []
        price = _as_float(quote.get("last_price"))
        previous_close = _as_float(quote.get("previous_close"))
        if price is None and bars:
            price = _as_float(bars[-1].get("close"))

        technical = compute_technical_metrics(bars)
        fundamental = compute_fundamental_metrics(
            info=info,
            statements_payload=statements,
            profile=profile,
            finnhub_metric=finnhub_metric,
        )
        analyst = compute_analyst_metrics(
            analyst_payload=analyst_payload, current_price=price, info=info
        )

        # Schlagzeilen und deren Einordnung. Im Cache-Only-Betrieb entsteht dabei
        # weder ein Datenabruf noch ein API-Aufruf beim Sprachmodell.
        news: list[NewsItem] = []
        sentiment = compute_sentiment_metrics(
            [],
            key_available=self.classifier.available,
            unavailable_reason=self.classifier.unavailable_reason,
        )
        if with_news:
            news = self.get_news(
                ticker, force_refresh=force_refresh, cache_only=cache_only
            )
            if news:
                news = self.classifier.classify(news, cache_only=cache_only)
            sentiment = compute_sentiment_metrics(
                news,
                key_available=self.classifier.available,
                unavailable_reason=self.classifier.unavailable_reason,
            )

        return StockSnapshot(
            ticker=ticker,
            profile=profile,
            price=price,
            previous_close=previous_close,
            currency=profile.currency,
            bars=bars,
            fundamental=fundamental,
            technical=technical,
            analyst=analyst,
            sentiment=sentiment,
            news=news,
            freshness=freshness,
            errors=errors,
        )

    def get_snapshots(
        self,
        tickers: list[str],
        *,
        force_refresh: bool = False,
        cache_only: bool = False,
        history_period: str = "5y",
        with_news: bool = True,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, StockSnapshot]:
        """Holt die Daten mehrerer Titel nacheinander.

        Ohne ``force_refresh`` wird die Cache-Lebensdauer beachtet: bereits
        aktuelle Daten werden nicht erneut abgerufen. Das macht ein wiederholtes
        Aktualisieren des Universums billig, weil nur wirklich veraltete Bereiche
        neu geholt werden.

        Die Abrufe laufen bewusst nacheinander - der Token-Bucket je Quelle
        greift nur, wenn nicht parallel daran vorbei gearbeitet wird. Ein Fehler
        bei einem Titel bricht den Lauf nicht ab; der betroffene Titel erhaelt
        einen Snapshot ohne Daten und wird in der Oberflaeche als solcher
        ausgewiesen.

        ``progress`` wird vor jedem Titel mit (Index, Gesamtzahl, Ticker)
        aufgerufen.
        """
        eindeutig = list(dict.fromkeys(t.upper() for t in tickers))
        result: dict[str, StockSnapshot] = {}

        for index, ticker in enumerate(eindeutig):
            if progress is not None:
                progress(index, len(eindeutig), ticker)
            try:
                result[ticker] = self.get_snapshot(
                    ticker,
                    force_refresh=force_refresh,
                    cache_only=cache_only,
                    history_period=history_period,
                    with_news=with_news,
                )
            except Exception as exc:  # noqa: BLE001 - ein Titel darf den Lauf nicht kippen
                logger.exception("Abruf fuer %s fehlgeschlagen", ticker)
                result[ticker] = StockSnapshot(
                    ticker=ticker,
                    profile=SecurityProfile(ticker=ticker),
                    errors=[f"Abruf fehlgeschlagen: {type(exc).__name__}: {exc}"],
                )

        if progress is not None:
            progress(len(eindeutig), len(eindeutig), "")
        return result

    def get_news(
        self, ticker: str, *, force_refresh: bool = False, cache_only: bool = False
    ) -> list[NewsItem]:
        """Schlagzeilen eines Titels - immer mit Quelle und Link."""
        ticker = ticker.upper()
        items: list[NewsItem] = []

        if self.finnhub.available:
            result = self.finnhub.company_news(
                ticker, force_refresh=force_refresh, cache_only=cache_only
            )
            if result.ok and isinstance(result.data, list):
                items.extend(_parse_finnhub_news(result.data))

        if not items:
            result = self.yfinance.news(
                ticker, force_refresh=force_refresh, cache_only=cache_only
            )
            if result.ok and isinstance(result.data, list):
                items.extend(_parse_yfinance_news(result.data))

        items.sort(key=lambda item: item.published_at, reverse=True)
        return items

    def _build_profile(
        self, ticker: str, info: dict[str, Any], quote: dict[str, Any]
    ) -> SecurityProfile:
        return SecurityProfile(
            ticker=ticker,
            name=info.get("longName") or info.get("shortName"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            country=info.get("country"),
            currency=info.get("currency") or quote.get("currency"),
            exchange=info.get("exchange") or quote.get("exchange"),
            quote_type=info.get("quoteType") or quote.get("quote_type"),
            source=Provenance.YFINANCE,
        )


def _as_float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _parse_finnhub_news(raw: list[dict[str, Any]]) -> list[NewsItem]:
    items = []
    for entry in raw:
        headline = (entry.get("headline") or "").strip()
        url = (entry.get("url") or "").strip()
        if not headline or not url:
            continue
        stamp = entry.get("datetime")
        try:
            published = datetime.fromtimestamp(float(stamp), tz=UTC)
        except (TypeError, ValueError):
            continue
        items.append(
            NewsItem(
                headline=headline,
                url=url,
                source_name=(entry.get("source") or "Finnhub").strip(),
                published_at=published,
                summary=(entry.get("summary") or "").strip() or None,
            )
        )
    return items


def _parse_yfinance_news(raw: list[dict[str, Any]]) -> list[NewsItem]:
    """yfinance kapselt Meldungen je nach Version flach oder unter ``content``."""
    items = []
    for entry in raw:
        content = entry.get("content") if isinstance(entry.get("content"), dict) else entry
        headline = (content.get("title") or "").strip()
        url = _extract_news_url(content) or (entry.get("link") or "").strip()
        if not headline or not url:
            continue

        published = None
        for field_name in ("pubDate", "displayTime"):
            value = content.get(field_name)
            if value:
                try:
                    published = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    break
                except ValueError:
                    continue
        if published is None and entry.get("providerPublishTime"):
            try:
                published = datetime.fromtimestamp(float(entry["providerPublishTime"]), tz=UTC)
            except (TypeError, ValueError):
                published = None
        if published is None:
            continue

        provider = content.get("provider")
        source_name = (
            provider.get("displayName")
            if isinstance(provider, dict)
            else entry.get("publisher") or "Yahoo Finance"
        )
        items.append(
            NewsItem(
                headline=headline,
                url=url,
                source_name=str(source_name or "Yahoo Finance"),
                published_at=published,
                summary=(content.get("summary") or "").strip() or None,
            )
        )
    return items


def _extract_news_url(content: dict[str, Any]) -> str | None:
    for key in ("canonicalUrl", "clickThroughUrl"):
        value = content.get(key)
        if isinstance(value, dict) and value.get("url"):
            return str(value["url"])
        if isinstance(value, str) and value:
            return value
    return None
