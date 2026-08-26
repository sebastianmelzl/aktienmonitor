"""Analysten-Kennzahlen.

Quellen sind die Analysten-Endpunkte von yfinance (Konsens, Kursziele,
Schaetzungsrevisionen, Earnings-Termine) und - sofern der Free-Tier es zulaesst -
Finnhub. Jede Kennzahl behaelt ihre Herkunft; nicht gelieferte Werte bleiben n/a.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..models import (
    MISSING_NOT_PROVIDED,
    UNIT_COUNT,
    UNIT_CURRENCY,
    UNIT_DATE,
    UNIT_PERCENT,
    UNIT_RATIO,
    UNIT_TEXT,
    MetricSet,
    MetricValue,
    Provenance,
)

# Uebersetzung der englischen Konsensbegriffe - neutral gehalten, keine
# Handlungsempfehlung.
RATING_LABELS = {
    "strongbuy": "sehr positiv",
    "buy": "positiv",
    "hold": "neutral",
    "sell": "negativ",
    "strongsell": "sehr negativ",
    "underperform": "negativ",
    "outperform": "positiv",
    "none": None,
}


def frame_records(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Wandelt ein serialisiertes DataFrame in eine Liste von Datensaetzen.

    ``frame_to_payload`` speichert Zeilen unter ihrem Index-Label; hier wird
    daraus wieder ``[{spalte: wert}, ...]`` samt Index unter dem Schluessel
    ``_index``.
    """
    if not payload or not payload.get("rows"):
        return []
    columns = [str(c) for c in payload.get("columns", [])]
    records = []
    for label, values in payload["rows"].items():
        record: dict[str, Any] = {"_index": label}
        for column, value in zip(columns, values, strict=False):
            record[column] = value
        records.append(record)
    return records


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _consensus_from_counts(record: dict[str, Any]) -> tuple[str | None, float | None, float | None]:
    """Ermittelt Konsens-Label, Analystenzahl und mittlere Note aus den Zaehlern.

    Die mittlere Note folgt der ueblichen Skala 1 (sehr positiv) bis 5 (sehr
    negativ).
    """
    weights = {"strongBuy": 1.0, "buy": 2.0, "hold": 3.0, "sell": 4.0, "strongSell": 5.0}
    total = 0.0
    weighted = 0.0
    for field, weight in weights.items():
        count = _number(record.get(field)) or 0.0
        total += count
        weighted += count * weight
    if total <= 0:
        return None, None, None
    mean = weighted / total
    if mean < 1.5:
        label = "sehr positiv"
    elif mean < 2.5:
        label = "positiv"
    elif mean < 3.5:
        label = "neutral"
    elif mean < 4.5:
        label = "negativ"
    else:
        label = "sehr negativ"
    return label, total, mean


def compute_analyst_metrics(
    *,
    analyst_payload: dict[str, Any] | None,
    current_price: float | None = None,
    info: dict[str, Any] | None = None,
    finnhub_recommendations: list[dict[str, Any]] | None = None,
    finnhub_price_target: dict[str, Any] | None = None,
    as_of: datetime | None = None,
) -> MetricSet:
    """Berechnet alle Analysten-Kennzahlen."""
    analyst_payload = analyst_payload or {}
    info = info or {}
    stamp = as_of or datetime.now(UTC)
    yf = Provenance.YFINANCE
    fh = Provenance.FINNHUB
    metrics: dict[str, MetricValue] = {}

    def add(
        key: str, label: str, value: float | None, *, unit: str = UNIT_RATIO,
        source: Provenance = yf, computed: bool = False, inputs: tuple[str, ...] = (),
        reason: str = MISSING_NOT_PROVIDED,
    ) -> None:
        if value is None:
            metrics[key] = MetricValue.missing(
                key, label, unit=unit, reason=reason, source=source, is_computed=computed,
                inputs=inputs,
            )
        else:
            metrics[key] = MetricValue(
                key=key, label=label, value=float(value), unit=unit, source=source,
                as_of=stamp, is_computed=computed, inputs=inputs,
            )

    def add_text(
        key: str, label: str, text: str | None, *, unit: str = UNIT_TEXT,
        source: Provenance = yf, reason: str = MISSING_NOT_PROVIDED,
    ) -> None:
        if not text:
            metrics[key] = MetricValue.missing(key, label, unit=unit, reason=reason, source=source)
        else:
            metrics[key] = MetricValue(
                key=key, label=label, text=text, unit=unit, source=source, as_of=stamp
            )

    # --- Konsens ------------------------------------------------------------
    rating_label: str | None = None
    analyst_count: float | None = None
    rating_mean: float | None = None
    rating_source = yf

    records = frame_records(analyst_payload.get("recommendations"))
    if records:
        # Der juengste Datensatz ist bei yfinance die Periode "0m".
        latest = next((r for r in records if str(r.get("period", "")) == "0m"), records[0])
        rating_label, analyst_count, rating_mean = _consensus_from_counts(latest)

    if rating_label is None and finnhub_recommendations:
        latest_fh = finnhub_recommendations[0]
        rating_label, analyst_count, rating_mean = _consensus_from_counts(latest_fh)
        rating_source = fh

    if rating_label is None:
        key_label = str(info.get("recommendationKey", "")).lower().replace(" ", "")
        rating_label = RATING_LABELS.get(key_label)
        rating_mean = _number(info.get("recommendationMean"))
        analyst_count = _number(info.get("numberOfAnalystOpinions"))

    add_text("consensus_rating", "Konsens-Einordnung", rating_label, source=rating_source)
    add("analyst_count", "Anzahl Analysten", analyst_count, unit=UNIT_COUNT, source=rating_source)
    add(
        "consensus_score", "Konsens-Note (1 = sehr positiv, 5 = sehr negativ)", rating_mean,
        source=rating_source, computed=True, inputs=("Analysten-Zaehlungen",),
    )

    # --- Kursziel -----------------------------------------------------------
    targets = analyst_payload.get("price_targets")
    target_mean = _number((targets or {}).get("mean")) if isinstance(targets, dict) else None
    target_source = yf
    if target_mean is None:
        target_mean = _number(info.get("targetMeanPrice"))
    if target_mean is None and finnhub_price_target:
        target_mean = _number(finnhub_price_target.get("targetMean"))
        target_source = fh

    add("target_mean", "Durchschnittliches Kursziel", target_mean, unit=UNIT_CURRENCY, source=target_source)

    upside = None
    if target_mean is not None and current_price is not None and current_price > 0:
        upside = (target_mean / current_price - 1.0) * 100.0
    add(
        "target_upside", "Abstand zum Kursziel", upside, unit=UNIT_PERCENT, source=target_source,
        computed=True, inputs=("Kursziel", "aktueller Kurs"),
    )

    # --- Revisionen der Schaetzungen ----------------------------------------
    revisions = frame_records(analyst_payload.get("eps_revisions"))
    up_30 = down_30 = None
    if revisions:
        # "0y" ist das laufende Geschaeftsjahr - die aussagekraeftigste Periode.
        current = next((r for r in revisions if str(r.get("_index", "")) == "0y"), revisions[0])
        up_30 = _number(current.get("upLast30days"))
        down_30 = _number(current.get("downLast30days"))

    add("revisions_up_30d", "Aufwaertsrevisionen (30 Tage)", up_30, unit=UNIT_COUNT)
    add("revisions_down_30d", "Abwaertsrevisionen (30 Tage)", down_30, unit=UNIT_COUNT)

    revision_balance = None
    if up_30 is not None and down_30 is not None and (up_30 + down_30) > 0:
        # -100 = ausschliesslich Abwaerts-, +100 = ausschliesslich Aufwaertsrevisionen.
        revision_balance = (up_30 - down_30) / (up_30 + down_30) * 100.0
    add(
        "revision_balance", "Revisionssaldo (30 Tage)", revision_balance, unit=UNIT_PERCENT,
        computed=True, inputs=("Auf- und Abwaertsrevisionen",),
    )

    # --- Earnings-Surprises -------------------------------------------------
    surprises = _extract_surprises(analyst_payload.get("earnings_dates"))
    add(
        "earnings_surprise_last", "Letzte Earnings-Ueberraschung",
        surprises[0] if surprises else None, unit=UNIT_PERCENT,
    )
    average = None
    if surprises:
        recent = surprises[:4]
        average = sum(recent) / len(recent)
    add(
        "earnings_surprise_avg_4q", "Earnings-Ueberraschung (Schnitt 4 Quartale)", average,
        unit=UNIT_PERCENT, computed=True, inputs=("Earnings-Historie",),
    )

    # --- Naechster Termin ---------------------------------------------------
    add_text(
        "next_earnings_date", "Naechster Termin Zahlen",
        _next_earnings(analyst_payload.get("calendar"), analyst_payload.get("earnings_dates")),
        unit=UNIT_DATE,
    )

    return MetricSet(metrics)


def _extract_surprises(payload: dict[str, Any] | None) -> list[float]:
    """Ueberraschungen in Prozent, absteigend nach Datum (juengste zuerst)."""
    records = frame_records(payload)
    if not records:
        return []
    dated: list[tuple[datetime, float]] = []
    for record in records:
        value = None
        for field in ("Surprise(%)", "Surprise (%)", "surprisePercent"):
            if field in record:
                value = _number(record[field])
                if value is not None:
                    break
        if value is None:
            continue
        try:
            stamp = datetime.fromisoformat(str(record["_index"]).replace("Z", "+00:00"))
        except (ValueError, KeyError):
            continue
        dated.append((stamp.replace(tzinfo=None), value))
    dated.sort(key=lambda pair: pair[0], reverse=True)
    now = datetime.now(UTC).replace(tzinfo=None)
    # yfinance liefert auch kuenftige Termine ohne Ergebnis - die zaehlen nicht.
    return [value * 100.0 if abs(value) < 1.0 else value for stamp, value in dated if stamp <= now]


def _next_earnings(calendar: Any, earnings_dates: dict[str, Any] | None) -> str | None:
    """Naechsten Zahlentermin bestimmen - erst aus dem Kalender, dann aus der Historie."""
    today = datetime.now(UTC).replace(tzinfo=None)

    if isinstance(calendar, dict):
        raw = calendar.get("Earnings Date") or calendar.get("earningsDate")
        candidates = raw if isinstance(raw, list) else [raw]
        for entry in candidates:
            stamp = _parse_date(entry)
            if stamp is not None and stamp >= today:
                return stamp.date().isoformat()

    future: list[datetime] = []
    for record in frame_records(earnings_dates):
        stamp = _parse_date(record.get("_index"))
        if stamp is not None and stamp >= today:
            future.append(stamp)
    return min(future).date().isoformat() if future else None


def _parse_date(raw: Any) -> datetime | None:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
