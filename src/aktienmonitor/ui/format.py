"""Formatierung fuer die deutschsprachige Oberflaeche.

Fehlende Werte erscheinen ausnahmslos als "n/a". Es gibt keinen Pfad, auf dem
ein fehlender Wert als Zahl dargestellt wird.
"""

from __future__ import annotations

from ..models import (
    UNIT_COUNT,
    UNIT_CURRENCY,
    UNIT_DATE,
    UNIT_PERCENT,
    UNIT_TEXT,
    MetricValue,
)

NOT_AVAILABLE = "n/a"


def german_number(value: float, decimals: int = 2) -> str:
    """Zahl mit Komma als Dezimaltrennzeichen und Punkt als Tausendertrennung."""
    formatted = f"{value:,.{decimals}f}"
    return formatted.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def compact_currency(value: float, currency: str | None = None) -> str:
    """Grosse Betraege lesbar kuerzen (Mrd./Mio./Tsd.)."""
    suffix = f" {currency}" if currency else ""
    absolute = abs(value)
    if absolute >= 1e12:
        return f"{german_number(value / 1e12, 2)} Bio.{suffix}"
    if absolute >= 1e9:
        return f"{german_number(value / 1e9, 2)} Mrd.{suffix}"
    if absolute >= 1e6:
        return f"{german_number(value / 1e6, 2)} Mio.{suffix}"
    if absolute >= 1e3:
        return f"{german_number(value / 1e3, 2)} Tsd.{suffix}"
    return f"{german_number(value, 2)}{suffix}"


def format_metric(metric: MetricValue, currency: str | None = None) -> str:
    """Stellt eine Kennzahl dar - oder "n/a", wenn sie fehlt."""
    if not metric.is_available:
        return NOT_AVAILABLE
    if metric.unit in (UNIT_TEXT, UNIT_DATE):
        return metric.text or NOT_AVAILABLE
    value = metric.value
    if value is None:
        return NOT_AVAILABLE
    if metric.unit == UNIT_PERCENT:
        return f"{german_number(value, 2)} %"
    if metric.unit == UNIT_CURRENCY:
        return compact_currency(value, currency)
    if metric.unit == UNIT_COUNT:
        return german_number(value, 0)
    return german_number(value, 2)


def format_change(value: float | None) -> str:
    """Veraenderung mit Vorzeichen."""
    if value is None:
        return NOT_AVAILABLE
    return f"{'+' if value >= 0 else ''}{german_number(value, 2)} %"
