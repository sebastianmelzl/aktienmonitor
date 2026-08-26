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
MISSING_NOT_CLASSIFIED = "Keine Einordnung verfuegbar"


def _balance(positive: int, negative: int, total: int) -> float | None:
    """Saldo von -100 (nur negativ) bis +100 (nur positiv)."""
    if total <= 0:
        return None
    return (positive - negative) / total * 100.0


def compute_sentiment_metrics(
    items: list,
    *,
    as_of: datetime | None = None,
    key_available: bool = True,
    unavailable_reason: str | None = None,
) -> MetricSet:
    """Berechnet die Sentiment-Kennzahlen aus einer Liste von ``NewsItem``.

    ``unavailable_reason`` benennt, warum keine Einordnung moeglich war - etwa
    ein fehlender Schluessel oder ein nicht installiertes Paket. Der genaue
    Grund ist hilfreicher als die pauschale Vermutung "kein Schluessel".
    """
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

    classified = [i for i in items if getattr(i, "sentiment", None)]
    if not items:
        reason = MISSING_NO_NEWS
    elif not key_available and not classified:
        reason = unavailable_reason or MISSING_NOT_CLASSIFIED
    else:
        reason = MISSING_TOO_FEW

    metrics["news_count"] = MetricValue(
        key="news_count", label="Gefundene Meldungen", value=float(len(items)),
        unit=UNIT_COUNT, source=quelle, as_of=stamp, is_computed=True,
        inputs=("Schlagzeilen",),
    )
    metrics["sentiment_classified_count"] = MetricValue(
        key="sentiment_classified_count", label="Davon eingeordnet",
        value=float(len(classified)), unit=UNIT_COUNT, source=quelle, as_of=stamp,
        is_computed=True, inputs=("Schlagzeilen",),
    )

    if len(classified) < MIN_CLASSIFIED:
        for key, label in (
            ("sentiment_balance", "Stimmungssaldo"),
            ("sentiment_balance_7d", f"Stimmungssaldo ({RECENT_DAYS} Tage)"),
            ("sentiment_positive_share", "Anteil positiver Meldungen"),
        ):
            add(key, label, None, reason=reason)
        return MetricSet(metrics)

    positive_count = sum(1 for i in classified if i.sentiment == SentimentLabel.POSITIVE)
    negative_count = sum(1 for i in classified if i.sentiment == SentimentLabel.NEGATIVE)

    add(
        "sentiment_balance", "Stimmungssaldo",
        _balance(positive_count, negative_count, len(classified)), reason=reason,
    )
    add(
        "sentiment_positive_share", "Anteil positiver Meldungen",
        positive_count / len(classified) * 100.0, reason=reason,
    )

    cutoff = stamp - timedelta(days=RECENT_DAYS)
    recent = [i for i in classified if _as_aware(i.published_at) >= cutoff]
    add(
        "sentiment_balance_7d", f"Stimmungssaldo ({RECENT_DAYS} Tage)",
        _balance(
            sum(1 for i in recent if i.sentiment == SentimentLabel.POSITIVE),
            sum(1 for i in recent if i.sentiment == SentimentLabel.NEGATIVE),
            len(recent),
        ) if len(recent) >= MIN_CLASSIFIED else None,
        reason=f"Weniger als {MIN_CLASSIFIED} Meldungen in den letzten {RECENT_DAYS} Tagen",
    )
    return MetricSet(metrics)


def _as_aware(moment: datetime) -> datetime:
    """Stellt sicher, dass ein Zeitpunkt eine Zeitzone traegt."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
