"""Zugriff auf Jahresabschluesse.

Yahoo benennt Bilanzpositionen nicht ueber alle Titel hinweg gleich. Deshalb
arbeitet dieser Leser mit Aliaslisten und gibt ``None`` zurueck, wenn keine der
bekannten Bezeichnungen vorkommt - er raet nicht und setzt nichts auf null.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

Series = list[tuple[datetime, float]]


def _parse_stamp(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class Statement:
    """Eine Aufstellung (GuV, Bilanz oder Cashflow) aus dem Cache-Payload."""

    def __init__(self, payload: dict[str, Any] | None) -> None:
        self.periods: list[datetime] = []
        self.rows: dict[str, list[float | None]] = {}
        if not payload or "rows" not in payload:
            return
        stamps = [_parse_stamp(c) for c in payload.get("columns", [])]
        keep = [i for i, s in enumerate(stamps) if s is not None]
        self.periods = [stamps[i] for i in keep]  # type: ignore[misc]
        for label, values in (payload.get("rows") or {}).items():
            picked: list[float | None] = []
            for i in keep:
                value = values[i] if i < len(values) else None
                picked.append(float(value) if isinstance(value, int | float) else None)
            self.rows[str(label)] = picked
        # Aufsteigend nach Datum sortieren: aeltestes Geschaeftsjahr zuerst.
        order = sorted(range(len(self.periods)), key=lambda i: self.periods[i])
        self.periods = [self.periods[i] for i in order]
        self.rows = {label: [values[i] for i in order] for label, values in self.rows.items()}

    @property
    def is_empty(self) -> bool:
        return not self.periods or not self.rows

    def _find_row(self, aliases: tuple[str, ...]) -> list[float | None] | None:
        """Sucht eine Zeile - erst exakt, dann normalisiert, dann als Teilstring."""
        for alias in aliases:
            if alias in self.rows:
                return self.rows[alias]
        normalised = {label.lower().replace(" ", ""): values for label, values in self.rows.items()}
        for alias in aliases:
            key = alias.lower().replace(" ", "")
            if key in normalised:
                return normalised[key]
        for alias in aliases:
            key = alias.lower().replace(" ", "")
            for label, values in normalised.items():
                if key in label:
                    return values
        return None

    def series(self, *aliases: str) -> Series:
        """Zeitreihe einer Position, aufsteigend, ohne Luecken."""
        row = self._find_row(aliases)
        if row is None:
            return []
        return [
            (stamp, float(value))
            for stamp, value in zip(self.periods, row, strict=False)
            if value is not None
        ]

    def latest(self, *aliases: str) -> float | None:
        """Juengster verfuegbarer Wert einer Position."""
        series = self.series(*aliases)
        return series[-1][1] if series else None

    def value_at(self, index_from_end: int, *aliases: str) -> float | None:
        """Wert ``index_from_end`` Geschaeftsjahre vor dem juengsten."""
        series = self.series(*aliases)
        position = len(series) - 1 - index_from_end
        return series[position][1] if 0 <= position < len(series) else None

    @property
    def period_count(self) -> int:
        return len(self.periods)


class Statements:
    """Buendel aus GuV, Bilanz und Cashflow eines Titels."""

    def __init__(self, payload: dict[str, Any] | None) -> None:
        payload = payload or {}
        self.income = Statement(payload.get("income_annual"))
        self.income_quarterly = Statement(payload.get("income_quarterly"))
        self.balance = Statement(payload.get("balance_annual"))
        self.cashflow = Statement(payload.get("cashflow_annual"))
        self.dividends: dict[str, float] = {
            str(k): float(v)
            for k, v in (payload.get("dividends") or {}).items()
            if isinstance(v, int | float)
        }

    @property
    def is_empty(self) -> bool:
        return self.income.is_empty and self.balance.is_empty and self.cashflow.is_empty


# --- Aliaslisten der benoetigten Positionen ---------------------------------

REVENUE = ("Total Revenue", "OperatingRevenue", "Operating Revenue")
GROSS_PROFIT = ("Gross Profit",)
OPERATING_INCOME = ("Operating Income", "EBIT", "Total Operating Income As Reported")
NET_INCOME = ("Net Income", "Net Income Common Stockholders", "NetIncomeContinuousOperations")
EBITDA = ("EBITDA", "Normalized EBITDA")
EBIT = ("EBIT", "Operating Income")
PRETAX_INCOME = ("Pretax Income",)
TAX_PROVISION = ("Tax Provision",)
TAX_RATE = ("Tax Rate For Calcs",)
DILUTED_SHARES = ("Diluted Average Shares", "Basic Average Shares")

TOTAL_ASSETS = ("Total Assets",)
TOTAL_EQUITY = (
    "Stockholders Equity",
    "Total Equity Gross Minority Interest",
    "Common Stock Equity",
)
TOTAL_DEBT = ("Total Debt",)
CASH = (
    "Cash And Cash Equivalents",
    "Cash Cash Equivalents And Short Term Investments",
    "Cash Financial",
)
CURRENT_ASSETS = ("Current Assets", "Total Current Assets")
CURRENT_LIABILITIES = ("Current Liabilities", "Total Current Liabilities")
INVESTED_CAPITAL = ("Invested Capital",)
SHARES_ISSUED = ("Share Issued", "Ordinary Shares Number", "Common Stock")

FREE_CASH_FLOW = ("Free Cash Flow",)
OPERATING_CASH_FLOW = ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
CAPEX = ("Capital Expenditure",)
