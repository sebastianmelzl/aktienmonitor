"""Gemeinsame Testdaten.

Alle Tests arbeiten mit fixen, im Code stehenden Werten. Es gibt bewusst keinen
Netzwerkzugriff: die Kennzahlen- und Scoring-Logik muss ohne Datenquelle
vollstaendig pruefbar sein.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest


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
