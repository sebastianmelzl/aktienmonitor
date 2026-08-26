"""Gemeinsame Testdaten.

Alle Tests arbeiten mit fixen, im Code stehenden Werten. Es gibt bewusst keinen
Netzwerkzugriff: die Kennzahlen- und Scoring-Logik muss ohne Datenquelle
vollstaendig pruefbar sein.
"""

from __future__ import annotations

import math
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from aktienmonitor.config import (
    DATA_KIND_ANALYST,
    DATA_KIND_FUNDAMENTALS,
    DATA_KIND_NEWS,
    DATA_KIND_PRICE_HISTORY,
    DATA_KIND_PROFILE,
    DATA_KIND_QUOTE,
)
from aktienmonitor.models import NewsItem
from aktienmonitor.sentiment.classifier import SentimentClassifier
from aktienmonitor.storage.cache import Cache, build_key
from aktienmonitor.storage.db import Database
from aktienmonitor.storage.watchlist import Watchlist


def make_bars(closes: list[float], *, start: date = date(2023, 1, 2), volume: float = 1_000_000.0):
    """Baut Tageskerzen aus einer Liste von Schlusskursen.

    Hoch und Tief werden mit festem Abstand zum Schlusskurs gesetzt, damit die
    ATR-Berechnung deterministisch pruefbar bleibt.
    """
    bars = []
    for index, close in enumerate(closes):
        bars.append(
            {
                "date": (start + timedelta(days=index)).isoformat(),
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": volume,
            }
        )
    return bars


# Wilders Originalreihe zur Pruefung des RSI.
WILDER_CLOSES = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
    45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28,
]


@pytest.fixture
def income_statement() -> dict:
    """GuV ueber sechs Geschaeftsjahre - absichtlich unsortiert geliefert."""
    return {
        "columns": [
            "2024-12-31T00:00:00", "2021-12-31T00:00:00", "2023-12-31T00:00:00",
            "2019-12-31T00:00:00", "2022-12-31T00:00:00", "2020-12-31T00:00:00",
        ],
        "index": [],
        "rows": {
            # Umsatz: 2019 = 1000, danach exakt +10 % pro Jahr.
            "Total Revenue": [1610.51, 1210.0, 1464.1, 1000.0, 1331.0, 1100.0],
            "Gross Profit": [644.204, 484.0, 585.64, 400.0, 532.4, 440.0],
            "Operating Income": [322.102, 242.0, 292.82, 200.0, 266.2, 220.0],
            "Net Income": [241.58, 181.5, 219.62, 150.0, 199.65, 165.0],
            "EBITDA": [402.6, 302.5, 366.0, 250.0, 332.75, 275.0],
            "Pretax Income": [300.0, 225.0, 273.0, 187.5, 248.0, 205.0],
            "Tax Provision": [75.0, 56.25, 68.25, 46.875, 62.0, 51.25],
            "Diluted Average Shares": [95.0, 101.0, 97.0, 105.0, 99.0, 103.0],
        },
    }


@pytest.fixture
def balance_sheet() -> dict:
    return {
        "columns": ["2023-12-31T00:00:00", "2024-12-31T00:00:00"],
        "index": [],
        "rows": {
            "Total Assets": [4000.0, 5000.0],
            "Stockholders Equity": [1600.0, 2000.0],
            "Total Debt": [1200.0, 1500.0],
            "Cash And Cash Equivalents": [400.0, 500.0],
            "Current Assets": [1500.0, 1800.0],
            "Current Liabilities": [750.0, 1200.0],
            "Invested Capital": [2800.0, 3500.0],
        },
    }


@pytest.fixture
def cash_flow() -> dict:
    return {
        "columns": ["2023-12-31T00:00:00", "2024-12-31T00:00:00"],
        "index": [],
        "rows": {
            "Operating Cash Flow": [300.0, 400.0],
            # Investitionen stehen in der Kapitalflussrechnung negativ.
            "Capital Expenditure": [-100.0, -150.0],
        },
    }


@pytest.fixture
def statements_payload(income_statement, balance_sheet, cash_flow) -> dict:
    return {
        "income_annual": income_statement,
        "balance_annual": balance_sheet,
        "cashflow_annual": cash_flow,
        "dividends": {
            "2020-03-01T00:00:00": 1.00,
            "2021-03-01T00:00:00": 1.10,
            "2022-03-01T00:00:00": 1.20,
            "2023-03-01T00:00:00": 1.15,
            "2024-03-01T00:00:00": 1.30,
        },
    }


# --- Gemeinsame Fixture fuer die Seiten- und Zugangstests -------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VIEWS = PROJECT_ROOT / "views"

# (Ticker, Sektor, KGV, Marge) - drei Technologiewerte ergeben eine
# Vergleichsgruppe, der Finanzwert steht bewusst allein.
TEST_SECURITIES = (
    ("TESTA", "Technology", 14.0, 18.0),
    ("TESTB", "Technology", 22.0, 12.0),
    ("TESTC", "Technology", 31.0, 24.0),
    ("TESTF", "Financial Services", 9.0, 26.0),
)

CACHE_TTL = 30 * 24 * 3600


def _bars(seed: float, count: int = 300) -> list[dict]:
    start = date.today() - timedelta(days=count)
    kurs = 100.0 + seed * 5
    reihe = []
    for i in range(count):
        kurs = max(5.0, kurs + 0.1 + math.sin(i / 8.0 + seed) * 1.2)
        reihe.append(
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "open": kurs - 0.3, "high": kurs + 1.0, "low": kurs - 1.0,
                "close": kurs, "volume": 800_000 + (i % 17) * 15_000,
            }
        )
    return reihe


def _statements(umsatz: float, marge: float) -> dict:
    jahre = [f"{y}-12-31T00:00:00" for y in (2020, 2021, 2022, 2023, 2024)]
    reihe = [umsatz * (1.08**i) for i in range(5)]
    return {
        "income_annual": {
            "columns": jahre, "index": [],
            "rows": {
                "Total Revenue": reihe,
                "Gross Profit": [v * 0.4 for v in reihe],
                "Operating Income": [v * marge / 100 * 1.2 for v in reihe],
                "Net Income": [v * marge / 100 for v in reihe],
                "EBITDA": [v * marge / 100 * 1.6 for v in reihe],
                "Pretax Income": [v * marge / 100 * 1.3 for v in reihe],
                "Tax Provision": [v * marge / 100 * 0.3 for v in reihe],
                "Diluted Average Shares": [1000.0 - i * 10 for i in range(5)],
            },
        },
        "balance_annual": {
            "columns": jahre[-2:], "index": [],
            "rows": {
                "Total Assets": [umsatz * 2.4, umsatz * 2.5],
                "Stockholders Equity": [umsatz * 1.0, umsatz * 1.1],
                "Total Debt": [umsatz * 0.7, umsatz * 0.7],
                "Cash And Cash Equivalents": [umsatz * 0.3, umsatz * 0.3],
                "Current Assets": [umsatz * 0.9, umsatz * 0.9],
                "Current Liabilities": [umsatz * 0.55, umsatz * 0.55],
                "Invested Capital": [umsatz * 1.7, umsatz * 1.8],
            },
        },
        "cashflow_annual": {
            "columns": jahre[-2:], "index": [],
            "rows": {
                "Operating Cash Flow": [umsatz * 0.19, umsatz * 0.20],
                "Capital Expenditure": [-umsatz * 0.06, -umsatz * 0.06],
            },
        },
        "dividends": {
            f"{y}-04-01T00:00:00": 1.0 + 0.05 * i
            for i, y in enumerate((2020, 2021, 2022, 2023))
        },
    }


class _FakeBlock:
    """Textblock einer Modellantwort."""

    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponse:
    stop_reason = "end_turn"

    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    """Ordnet jede Schlagzeile abwechselnd ein - deterministisch und ohne Netz."""

    def create(self, **kwargs):
        import json as _json
        import re as _re

        zeilen = _re.findall(r"^(\d+)\. ", kwargs["messages"][0]["content"], _re.MULTILINE)
        labels = ("positive", "neutral", "negative")
        return _FakeResponse(
            _json.dumps(
                {
                    "verdicts": [
                        {
                            "index": int(i),
                            "label": labels[int(i) % 3],
                            "rationale": "Testbegruendung",
                        }
                        for i in zeilen
                    ]
                }
            )
        )


class _FakeAnthropic:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


def _news_payload(ticker: str, count: int = 6) -> list[dict]:
    """Meldungen im aktuellen yfinance-Format."""
    from datetime import UTC, datetime

    return [
        {
            "content": {
                "title": f"{ticker}: Meldung {i}",
                "pubDate": (datetime.now(UTC) - timedelta(days=i)).isoformat(),
                "provider": {"displayName": "Testquelle"},
                "canonicalUrl": {"url": f"https://example.com/{ticker}/{i}"},
                "summary": "Kurzfassung der Meldung.",
            }
        }
        for i in range(count)
    ]


@pytest.fixture(scope="session")
def seeded_app(tmp_path_factory):
    """Legt eine temporaere Datenbank mit Testtiteln an und richtet die App darauf aus."""
    db_path = tmp_path_factory.mktemp("app") / "test.db"
    os.environ["AKTIENMONITOR_DB_PATH"] = str(db_path)
    # Ohne Schluessel bleibt Finnhub aussen vor - der Durchlauf braucht kein Netz.
    os.environ["FINNHUB_API_KEY"] = ""
    os.environ["ANTHROPIC_API_KEY"] = ""

    db = Database(db_path)
    cache = Cache(db)
    watchlist = Watchlist(db)

    for index, (ticker, sektor, kgv, marge) in enumerate(TEST_SECURITIES):
        watchlist.add(ticker, display_name=f"Testwert {ticker}")
        watchlist.assign(ticker, "Testdaten")
        reihe = _bars(index)
        kurs = reihe[-1]["close"]

        eintraege = {
            "info": (DATA_KIND_PROFILE, {
                "longName": f"Testwert {ticker}", "sector": sektor, "industry": "Software",
                "currency": "EUR", "quoteType": "EQUITY", "exchange": "XETRA",
                "marketCap": kurs * 1e9, "sharesOutstanding": 1e9,
                "trailingPE": kgv, "forwardPE": kgv * 0.9,
                "priceToSalesTrailing12Months": kgv / 6, "priceToBook": kgv / 5,
                "enterpriseToEbitda": kgv * 0.6, "returnOnEquity": 0.18,
                "grossMargins": 0.4, "operatingMargins": marge / 100 * 1.2,
                "profitMargins": marge / 100, "earningsGrowth": 0.1,
                "currentRatio": 1.6, "dividendYield": 2.0 + index * 0.4, "payoutRatio": 0.35,
                "targetMeanPrice": kurs * 1.1, "numberOfAnalystOpinions": 10,
                "ebitda": 800e6, "totalDebt": 700e6, "totalCash": 300e6,
            }),
            "fast_info": (DATA_KIND_QUOTE, {
                "last_price": kurs, "previous_close": kurs * 0.99, "currency": "EUR",
                "quote_type": "EQUITY", "market_cap": kurs * 1e9, "shares": 1e9,
            }),
            "financials": (DATA_KIND_FUNDAMENTALS, _statements(4000.0 + index * 500, marge)),
            "analyst": (DATA_KIND_ANALYST, {
                "recommendations": {
                    "columns": ["period", "strongBuy", "buy", "hold", "sell", "strongSell"],
                    "index": [], "rows": {"0": ["0m", 5, 6, 3, 1, 0]},
                },
                "price_targets": {"mean": kurs * 1.1},
                "eps_revisions": {
                    "columns": ["upLast7days", "upLast30days", "downLast7days", "downLast30days"],
                    "index": [], "rows": {"0y": [1, 5, 0, 1]},
                },
                "earnings_dates": {
                    "columns": ["EPS Estimate", "Reported EPS", "Surprise(%)"], "index": [],
                    "rows": {(date.today() - timedelta(days=45)).isoformat(): [1.0, 1.04, 4.0]},
                },
                "calendar": {"Earnings Date": [(date.today() + timedelta(days=45)).isoformat()]},
            }),
        }
        for endpoint, (kind, payload) in eintraege.items():
            cache.set(build_key("yfinance", endpoint, ticker), payload, source="yfinance",
                      data_kind=kind, ttl_seconds=CACHE_TTL, ticker=ticker)
        for periode in ("5y", "1y"):
            cache.set(build_key("yfinance", "history", ticker, periode, "1d"),
                      {"period": periode, "interval": "1d", "bars": reihe},
                      source="yfinance", data_kind=DATA_KIND_PRICE_HISTORY,
                      ttl_seconds=CACHE_TTL, ticker=ticker)

        # Schlagzeilen ablegen und vorab einordnen, damit der Sentiment-Pfad
        # im Seitentest ohne Netz und ohne API-Schluessel abgedeckt ist.
        meldungen = _news_payload(ticker)
        cache.set(build_key("yfinance", "news", ticker), meldungen, source="yfinance",
                  data_kind=DATA_KIND_NEWS, ttl_seconds=CACHE_TTL, ticker=ticker)

        klassifikator = SentimentClassifier(None, cache, client=_FakeAnthropic())
        klassifikator.classify(
            [
                NewsItem(
                    headline=eintrag["content"]["title"],
                    url=eintrag["content"]["canonicalUrl"]["url"],
                    source_name="Testquelle",
                    published_at=datetime.fromisoformat(eintrag["content"]["pubDate"]),
                )
                for eintrag in meldungen
            ]
        )
    return db_path


