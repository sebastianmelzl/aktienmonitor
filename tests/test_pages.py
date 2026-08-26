"""Durchlauftest aller Seiten mit Streamlits eigenem Testlaeufer.

Diese Tests fangen Fehler, die Unit-Tests nicht sehen: eine umbenannte Funktion,
eine fehlerhafte Spaltenkonfiguration oder ein Tippfehler in einer Seite faellt
sonst erst beim Aufruf im Browser auf.

Die Testdaten sind synthetisch und liegen in einer temporaeren Datenbank. Die
Ticker heissen bewusst TEST*, damit sie nicht mit echten Werten zu verwechseln
sind - in die Oberflaeche des Nutzers gelangen sie nie.
"""

from __future__ import annotations

import math
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from aktienmonitor.config import (
    DATA_KIND_ANALYST,
    DATA_KIND_FUNDAMENTALS,
    DATA_KIND_PRICE_HISTORY,
    DATA_KIND_PROFILE,
    DATA_KIND_QUOTE,
)
from aktienmonitor.storage.cache import Cache, build_key
from aktienmonitor.storage.db import Database
from aktienmonitor.storage.watchlist import Watchlist

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
    return db_path


def run_page(name: str, timeout: int = 120):
    """Fuehrt eine Seite aus und gibt das Testergebnis zurueck."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(VIEWS / name), default_timeout=timeout)
    return app.run()


@pytest.mark.usefixtures("seeded_app")
class TestSeitenLaufen:
    """Jede Seite muss ohne Ausnahme durchlaufen."""

    @pytest.mark.parametrize(
        "seite",
        ["uebersicht.py", "watchlist.py", "detail.py", "vergleich.py",
         "datenquellen.py", "einstellungen.py"],
    )
    def test_seite_wirft_keine_ausnahme(self, seite):
        ergebnis = run_page(seite)
        assert not ergebnis.exception, [str(e.message) for e in ergebnis.exception]


@pytest.mark.usefixtures("seeded_app")
class TestUebersicht:
    def test_tabelle_enthaelt_alle_titel(self):
        ergebnis = run_page("uebersicht.py")
        tabelle = ergebnis.dataframe[0].value
        assert len(tabelle) == len(TEST_SECURITIES)
        assert set(tabelle["Ticker"]) == {t[0] for t in TEST_SECURITIES}

    def test_nach_gesamtscore_absteigend_sortiert(self):
        scores = [
            wert for wert in run_page("uebersicht.py").dataframe[0].value["Gesamtscore"]
            if wert == wert  # NaN aussortieren
        ]
        assert scores == sorted(scores, reverse=True)

    def test_export_knoepfe_vorhanden(self):
        ergebnis = run_page("uebersicht.py")
        beschriftungen = [k.label for k in ergebnis.button] + [
            k.label for k in getattr(ergebnis, "download_button", [])
        ]
        assert any("CSV" in text for text in beschriftungen)


@pytest.mark.usefixtures("seeded_app")
class TestVergleich:
    def test_zwei_titel_nebeneinander(self):
        ergebnis = run_page("vergleich.py")
        ergebnis.multiselect[0].select("TESTA").select("TESTF").run()
        assert not ergebnis.exception, [str(e.message) for e in ergebnis.exception]

        teilscores = ergebnis.dataframe[0].value
        assert "TESTA" in teilscores.columns
        assert "TESTF" in teilscores.columns
        assert list(teilscores["Teilscore"]) == [
            "Fundamental", "Technik", "Analysten", "Sentiment"
        ]

    def test_titel_ohne_vergleichsgruppe_hat_geringere_abdeckung(self):
        """TESTF ist der einzige Finanzwert - seine sektorrelativen Kennzahlen
        koennen mangels Vergleichsgruppe nicht bewertet werden."""
        ergebnis = run_page("vergleich.py")
        ergebnis.multiselect[0].select("TESTA").select("TESTF").run()
        zeile = ergebnis.dataframe[0].value.iloc[0]
        assert zeile["Teilscore"] == "Fundamental"
        # Format "20-20 / 11-20": TESTA nutzt alle, TESTF deutlich weniger.
        links, rechts = zeile["Abdeckung"].split(" / ")
        assert int(links.split("-")[0]) > int(rechts.split("-")[0])

    def test_ohne_auswahl_kein_fehler(self):
        ergebnis = run_page("vergleich.py")
        assert not ergebnis.exception
