"""Kennzahlen aus den eingeordneten Schlagzeilen.

Wie ueberall gilt: zu wenige Daten ergeben keine Kennzahl. Ein Stimmungssaldo
aus zwei Meldungen waere Rauschen, kein Signal - er wird deshalb gar nicht erst
gebildet.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..models import (
    UNIT_COUNT,
    UNIT_PERCENT,
    MetricSet,
    MetricValue,
    Provenance,
)
from .classifier import SentimentLabel

# Ab so vielen eingeordneten Meldungen wird ein Saldo gebildet.
MIN_CLASSIFIED = 3

# Zeitfenster fuer die "aktuelle" Stimmung.
RECENT_DAYS = 7

MISSING_TOO_FEW = f"Weniger als {MIN_CLASSIFIED} eingeordnete Meldungen"
MISSING_NO_NEWS = "Keine Meldungen gefunden"
MISSING_NOT_CLASSIFIED = "Keine Einordnung verfuegbar (kein Anthropic-Schluessel)"


def _balance(positive: int, negative: int, total: int) -> float | None:
    """Saldo von -100 (nur negativ) bis +100 (nur positiv)."""
    if total <= 0:
        return None
    return (positive - negative) / total * 100.0


def compute_sentiment_metrics(
    items: list, *, as_of: datetime | None = None, key_available: bool = True
) -> MetricSet:
    """Berechnet die Sentiment-Kennzahlen aus einer Liste von ``NewsItem``."""
    stamp = as_of or datetime.now(UTC)
    quelle = Provenance.COMPUTED
    metrics: dict[str, MetricValue] = {}

    def add(
        key: str, label: str, value: float | None, *, unit: str = UNIT_PERCENT,
        reason: str, inputs: tuple[str, ...] = ("Eingeordnete Schlagzeilen",),
    ) -> None:
        if value is None:
            metrics[key] = MetricValue.missing(
                key, label, unit=unit, reason=reason, source=quelle,
                is_computed=True, inputs=inputs,
            )
        else:
            metrics[key] = MetricValue(
                key=key, label=label, value=float(value), unit=unit, source=quelle,
                as_of=stamp, is_computed=True, inputs=inputs,
            )

    eingeordnet = [i for i in items if getattr(i, "sentiment", None)]
    grund = (
        MISSING_NO_NEWS if not items
        else MISSING_NOT_CLASSIFIED if not key_available and not eingeordnet
        else MISSING_TOO_FEW
    )

    metrics["news_count"] = MetricValue(
        key="news_count", label="Gefundene Meldungen", value=float(len(items)),
        unit=UNIT_COUNT, source=quelle, as_of=stamp, is_computed=True,
        inputs=("Schlagzeilen",),
    )
    metrics["sentiment_classified_count"] = MetricValue(
        key="sentiment_classified_count", label="Davon eingeordnet",
        value=float(len(eingeordnet)), unit=UNIT_COUNT, source=quelle, as_of=stamp,
        is_computed=True, inputs=("Schlagzeilen",),
    )

    if len(eingeordnet) < MIN_CLASSIFIED:
        for key, label in (
            ("sentiment_balance", "Stimmungssaldo"),
            ("sentiment_balance_7d", f"Stimmungssaldo ({RECENT_DAYS} Tage)"),
            ("sentiment_positive_share", "Anteil positiver Meldungen"),
        ):
            add(key, label, None, reason=grund)
        return MetricSet(metrics)

    positiv = sum(1 for i in eingeordnet if i.sentiment == SentimentLabel.POSITIVE)
    negativ = sum(1 for i in eingeordnet if i.sentiment == SentimentLabel.NEGATIVE)

    add(
        "sentiment_balance", "Stimmungssaldo",
        _balance(positiv, negativ, len(eingeordnet)), reason=grund,
    )
    add(
        "sentiment_positive_share", "Anteil positiver Meldungen",
        positiv / len(eingeordnet) * 100.0, reason=grund,
    )

    grenze = stamp - timedelta(days=RECENT_DAYS)
    aktuell = [i for i in eingeordnet if _as_aware(i.published_at) >= grenze]
    add(
        "sentiment_balance_7d", f"Stimmungssaldo ({RECENT_DAYS} Tage)",
        _balance(
            sum(1 for i in aktuell if i.sentiment == SentimentLabel.POSITIVE),
            sum(1 for i in aktuell if i.sentiment == SentimentLabel.NEGATIVE),
            len(aktuell),
        ) if len(aktuell) >= MIN_CLASSIFIED else None,
        reason=f"Weniger als {MIN_CLASSIFIED} Meldungen in den letzten {RECENT_DAYS} Tagen",
    )
    return MetricSet(metrics)


def _as_aware(moment: datetime) -> datetime:
    """Stellt sicher, dass ein Zeitpunkt eine Zeitzone traegt."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
