"""Datenmodell der Anwendung.

Zentrale Regel dieses Projekts: es gibt keine erfundenen Werte. Deshalb ist
``MetricValue`` der einzige Traeger fuer Kennzahlen, und ein fehlender Wert ist
dort ein *expliziter Zustand* mit Begruendung - nicht 0.0, nicht NaN und kein
Schaetzwert. Wer eine Kennzahl anzeigt oder bewertet, muss sich mit
``is_available`` auseinandersetzen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

# --- Einheiten ---------------------------------------------------------------

UNIT_RATIO = "ratio"  # dimensionslos, z.B. KGV 18.4
UNIT_PERCENT = "percent"  # bereits in Prozentpunkten, z.B. 12.5 = 12,5 %
UNIT_CURRENCY = "currency"  # Geldbetrag in der Waehrung des Titels
UNIT_COUNT = "count"  # Stueckzahl, z.B. Anzahl Analysten
UNIT_DATE = "date"  # Datum, im Feld ``text`` hinterlegt
UNIT_TEXT = "text"  # Freitext, im Feld ``text`` hinterlegt


class Provenance(StrEnum):
    """Woher ein Wert stammt - wird in der Oberflaeche an jeder Kennzahl angezeigt."""

    YFINANCE = "yfinance"
    FINNHUB = "Finnhub"
    COMPUTED = "berechnet"
    UNKNOWN = "unbekannt"


# Standardisierte Begruendungen fuer fehlende Werte.
MISSING_NOT_PROVIDED = "Von der Datenquelle nicht geliefert"
MISSING_NOT_APPLICABLE = "Fuer diesen Titel nicht anwendbar"
MISSING_INSUFFICIENT_HISTORY = "Historie zu kurz"
MISSING_PREMIUM = "Endpunkt im Free-Tier gesperrt"
MISSING_DIVISION_UNDEFINED = "Nicht berechenbar (Nenner null oder negativ)"
MISSING_INPUT = "Eingangsgroesse fehlt"


@dataclass(frozen=True)
class MetricValue:
    """Eine einzelne Kennzahl samt Herkunft.

    Ein Objekt mit ``value is None`` und ``text is None`` bedeutet "n/a" und wird
    in der Oberflaeche als fehlend gekennzeichnet. ``missing_reason`` sagt warum.
    """

    key: str
    label: str
    value: float | None = None
    text: str | None = None
    unit: str = UNIT_RATIO
    source: Provenance = Provenance.UNKNOWN
    as_of: datetime | None = None
    is_computed: bool = False
    # Bei berechneten Kennzahlen: welche Rohgroessen eingeflossen sind.
    inputs: tuple[str, ...] = ()
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        # NaN und Inf sind keine Werte - sie werden zu einem sauberen "n/a".
        if self.value is not None and not math.isfinite(self.value):
            object.__setattr__(self, "value", None)
            if self.missing_reason is None:
                object.__setattr__(self, "missing_reason", MISSING_DIVISION_UNDEFINED)
        if not self.is_available and self.missing_reason is None:
            object.__setattr__(self, "missing_reason", MISSING_NOT_PROVIDED)

    @property
    def is_available(self) -> bool:
        return self.value is not None or self.text is not None

    @property
    def source_label(self) -> str:
        """Quellenangabe fuer die Oberflaeche, inkl. Kennzeichnung "berechnet"."""
        if not self.is_available:
            return "-"
        if self.is_computed:
            origin = self.source.value if self.source is not Provenance.COMPUTED else None
            return f"berechnet (aus {origin})" if origin else "berechnet"
        return self.source.value

    @classmethod
    def missing(
        cls,
        key: str,
        label: str,
        *,
        unit: str = UNIT_RATIO,
        reason: str = MISSING_NOT_PROVIDED,
        source: Provenance = Provenance.UNKNOWN,
        is_computed: bool = False,
        inputs: tuple[str, ...] = (),
    ) -> MetricValue:
        """Erzeugt eine ausdruecklich fehlende Kennzahl."""
        return cls(
            key=key,
            label=label,
            unit=unit,
            source=source,
            is_computed=is_computed,
            inputs=inputs,
            missing_reason=reason,
        )


@dataclass(frozen=True)
class MetricSet:
    """Sammlung von Kennzahlen eines Bereichs (fundamental, technisch, ...)."""

    metrics: dict[str, MetricValue] = field(default_factory=dict)

    def __getitem__(self, key: str) -> MetricValue:
        return self.metrics[key]

    def __contains__(self, key: str) -> bool:
        return key in self.metrics

    def __iter__(self):
        return iter(self.metrics.values())

    def __len__(self) -> int:
        return len(self.metrics)

    def get(self, key: str) -> MetricValue | None:
        return self.metrics.get(key)

    def value_of(self, key: str) -> float | None:
        """Numerischer Wert oder None - nie ein Ersatzwert."""
        metric = self.metrics.get(key)
        return metric.value if metric is not None else None

    @property
    def available(self) -> list[MetricValue]:
        return [m for m in self.metrics.values() if m.is_available]

    @property
    def missing(self) -> list[MetricValue]:
        return [m for m in self.metrics.values() if not m.is_available]

    @property
    def coverage(self) -> float:
        """Anteil vorhandener Kennzahlen (0.0-1.0)."""
        if not self.metrics:
            return 0.0
        return len(self.available) / len(self.metrics)


@dataclass(frozen=True)
class ProviderResult:
    """Rohantwort einer Datenquelle inklusive Herkunftsnachweis."""

    data: object
    source: Provenance
    fetched_at: datetime
    from_cache: bool = False
    # Alter der Daten in Sekunden zum Zeitpunkt der Auslieferung.
    age_seconds: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.data is not None


@dataclass(frozen=True)
class PriceBar:
    """Eine Tageskerze."""

    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class NewsItem:
    """Eine Schlagzeile - immer mit Quelle und Link, damit sie nachlesbar bleibt."""

    headline: str
    url: str
    source_name: str
    published_at: datetime
    summary: str | None = None
    # Wird erst in Phase 4 gefuellt; None bedeutet "nicht eingeordnet".
    sentiment: str | None = None
    sentiment_rationale: str | None = None


@dataclass(frozen=True)
class SecurityProfile:
    """Stammdaten eines Titels."""

    ticker: str
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    currency: str | None = None
    exchange: str | None = None
    quote_type: str | None = None  # EQUITY, ETF, MUTUALFUND, ...
    source: Provenance = Provenance.UNKNOWN

    @property
    def is_fund(self) -> bool:
        """ETFs und Fonds haben keine Unternehmenskennzahlen (ROE, Margen, ...)."""
        return (self.quote_type or "").upper() in {"ETF", "MUTUALFUND", "INDEX"}
