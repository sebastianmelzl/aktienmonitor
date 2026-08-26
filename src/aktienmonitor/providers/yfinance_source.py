"""Adapter fuer yfinance.

yfinance ist in diesem Projekt die Hauptquelle: nur hier gibt es fuer nicht-US-
Titel und ETFs ueberhaupt Kurshistorie, Fundamentaldaten und Analystendaten.
Die Daten stammen von Yahoo Finance, sind kostenlos und ohne Key nutzbar -
dafuer ohne Zusage zu Verfuegbarkeit oder Richtigkeit. Deshalb wird jede
Kennzahl mit Quelle und Abrufzeitpunkt weitergereicht.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import (
    DATA_KIND_ANALYST,
    DATA_KIND_FUNDAMENTALS,
    DATA_KIND_NEWS,
    DATA_KIND_PRICE_HISTORY,
    DATA_KIND_PROFILE,
    DATA_KIND_QUOTE,
)
from ..models import Provenance, ProviderResult
from .base import ProviderRuntime, frame_to_payload, jsonable, series_to_payload

logger = logging.getLogger("aktienmonitor.providers.yfinance")

SOURCE_KEY = "yfinance"

# Felder aus ``Ticker.info``, die wir uebernehmen. Bewusst als Positivliste:
# der Rest ist entweder redundant oder in seiner Bedeutung unklar.
INFO_FIELDS = (
    "longName", "shortName", "sector", "industry", "country", "currency", "exchange",
    "quoteType", "marketCap", "enterpriseValue", "sharesOutstanding", "floatShares",
    "trailingPE", "forwardPE", "priceToBook", "priceToSalesTrailing12Months",
    "trailingPegRatio", "enterpriseToEbitda", "enterpriseToRevenue",
    "returnOnEquity", "returnOnAssets", "grossMargins", "operatingMargins",
    "profitMargins", "ebitdaMargins", "revenueGrowth", "earningsGrowth",
    "earningsQuarterlyGrowth", "revenuePerShare", "totalRevenue", "ebitda",
    "freeCashflow", "operatingCashflow", "totalCash", "totalDebt", "debtToEquity",
    "currentRatio", "quickRatio", "bookValue", "beta",
    "dividendYield", "trailingAnnualDividendYield", "payoutRatio", "fiveYearAvgDividendYield",
    "lastDividendValue", "lastDividendDate", "exDividendDate",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyDayAverage", "twoHundredDayAverage",
    "targetMeanPrice", "targetHighPrice", "targetLowPrice", "targetMedianPrice",
    "recommendationMean", "recommendationKey", "numberOfAnalystOpinions",
    "trailingEps", "forwardEps", "netIncomeToCommon",
)


class YFinanceSource:
    """Kapselt alle yfinance-Zugriffe."""

    source = Provenance.YFINANCE
    source_key = SOURCE_KEY

    def __init__(self, runtime: ProviderRuntime) -> None:
        self.runtime = runtime

    # --- interne Helfer ------------------------------------------------------

    @staticmethod
    def _ticker(marker: str):
        import yfinance as yf

        return yf.Ticker(marker)

    @staticmethod
    def _safe(getter, default: Any = None) -> Any:
        """Fuehrt einen yfinance-Zugriff aus; liefert bei Fehlern ``default``.

        yfinance wirft je nach Titel und Endpunkt sehr unterschiedliche Fehler.
        Ein fehlender Teilbereich darf nicht den gesamten Abruf zerstoeren - er
        wird spaeter als "n/a" gefuehrt.
        """
        try:
            return getter()
        except Exception as exc:  # noqa: BLE001
            logger.debug("yfinance-Teilabruf fehlgeschlagen: %s", exc)
            return default

    # --- Endpunkte -----------------------------------------------------------

    def profile(
        self, ticker: str, *, force_refresh: bool = False, cache_only: bool = False
    ) -> ProviderResult:
        def load() -> dict[str, Any] | None:
            info = self._safe(lambda: self._ticker(ticker).info, {}) or {}
            if not info:
                return None
            return {field: jsonable(info.get(field)) for field in INFO_FIELDS if field in info}

        return self.runtime.fetch(
            source=self.source, source_key=self.source_key, endpoint="info", ticker=ticker,
            data_kind=DATA_KIND_PROFILE,
            loader=load, force_refresh=force_refresh, cache_only=cache_only,
        )

    def quote(
        self, ticker: str, *, force_refresh: bool = False, cache_only: bool = False
    ) -> ProviderResult:
        def load() -> dict[str, Any] | None:
            fast = self._safe(lambda: self._ticker(ticker).fast_info)
            if fast is None:
                return None
            fields = (
                "last_price", "previous_close", "open", "day_high", "day_low",
                "last_volume", "currency", "exchange", "quote_type", "market_cap",
                "shares", "year_high", "year_low", "fifty_day_average",
                "two_hundred_day_average", "ten_day_average_volume",
                "three_month_average_volume",
            )
            payload = {f: jsonable(self._safe(lambda f=f: fast[f])) for f in fields}
            return payload if payload.get("last_price") is not None else None

        return self.runtime.fetch(
            source=self.source, source_key=self.source_key, endpoint="fast_info", ticker=ticker,
            data_kind=DATA_KIND_QUOTE,
            loader=load, force_refresh=force_refresh, cache_only=cache_only,
        )

    def price_history(
        self, ticker: str, *, period: str = "5y", interval: str = "1d",
        force_refresh: bool = False, cache_only: bool = False,
    ) -> ProviderResult:
        def load() -> dict[str, Any] | None:
            frame = self._safe(
                lambda: self._ticker(ticker).history(
                    period=period, interval=interval, auto_adjust=True
                )
            )
            if frame is None or frame.empty:
                return None
            bars = []
            for stamp, row in frame.iterrows():
                bars.append(
                    {
                        "date": jsonable(stamp.date() if hasattr(stamp, "date") else stamp),
                        "open": jsonable(row.get("Open")),
                        "high": jsonable(row.get("High")),
                        "low": jsonable(row.get("Low")),
                        "close": jsonable(row.get("Close")),
                        "volume": jsonable(row.get("Volume")),
                    }
                )
            return {"period": period, "interval": interval, "bars": bars}

        return self.runtime.fetch(
            source=self.source, source_key=self.source_key, endpoint="history", ticker=ticker,
            data_kind=DATA_KIND_PRICE_HISTORY, loader=load, cache_parts=(period, interval),
            force_refresh=force_refresh, cache_only=cache_only,
        )

    def fundamentals(
        self, ticker: str, *, force_refresh: bool = False, cache_only: bool = False
    ) -> ProviderResult:
        """Jahres- und Quartalsabschluesse plus Dividenden- und Aktienzahl-Historie."""

        def load() -> dict[str, Any] | None:
            handle = self._ticker(ticker)
            payload = {
                "income_annual": frame_to_payload(self._safe(lambda: handle.income_stmt)),
                "income_quarterly": frame_to_payload(self._safe(lambda: handle.quarterly_income_stmt)),
                "balance_annual": frame_to_payload(self._safe(lambda: handle.balance_sheet)),
                "cashflow_annual": frame_to_payload(self._safe(lambda: handle.cash_flow)),
                "dividends": series_to_payload(self._safe(lambda: handle.dividends)),
            }
            return payload if any(v for v in payload.values()) else None

        return self.runtime.fetch(
            source=self.source, source_key=self.source_key, endpoint="financials", ticker=ticker,
            data_kind=DATA_KIND_FUNDAMENTALS,
            loader=load, force_refresh=force_refresh, cache_only=cache_only,
        )

    def analyst(
        self, ticker: str, *, force_refresh: bool = False, cache_only: bool = False
    ) -> ProviderResult:
        """Konsens, Kursziele, Schaetzungsrevisionen und Earnings-Termine."""

        def load() -> dict[str, Any] | None:
            handle = self._ticker(ticker)
            payload = {
                "recommendations": frame_to_payload(self._safe(lambda: handle.recommendations)),
                "price_targets": jsonable(self._safe(lambda: handle.analyst_price_targets)),
                "earnings_dates": frame_to_payload(self._safe(lambda: handle.earnings_dates)),
                "eps_revisions": frame_to_payload(self._safe(lambda: handle.eps_revisions)),
                "eps_trend": frame_to_payload(self._safe(lambda: handle.eps_trend)),
                "earnings_estimate": frame_to_payload(self._safe(lambda: handle.earnings_estimate)),
                "calendar": jsonable(self._safe(lambda: handle.calendar)),
            }
            return payload if any(v for v in payload.values()) else None

        return self.runtime.fetch(
            source=self.source, source_key=self.source_key, endpoint="analyst", ticker=ticker,
            data_kind=DATA_KIND_ANALYST,
            loader=load, force_refresh=force_refresh, cache_only=cache_only,
        )

    def news(
        self, ticker: str, *, force_refresh: bool = False, cache_only: bool = False
    ) -> ProviderResult:
        def load() -> list[dict[str, Any]] | None:
            items = self._safe(lambda: self._ticker(ticker).news, []) or []
            return [jsonable(item) for item in items] or None

        return self.runtime.fetch(
            source=self.source, source_key=self.source_key, endpoint="news", ticker=ticker,
            data_kind=DATA_KIND_NEWS,
            loader=load, force_refresh=force_refresh, cache_only=cache_only,
        )
