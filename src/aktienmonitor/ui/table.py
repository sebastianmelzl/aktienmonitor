"""Aufbau und Filterung der Uebersichtstabelle.

Bewusst ohne Streamlit-Import: Zeilenaufbau, Filter und CSV-Export sind reine
Datenverarbeitung und damit ohne Oberflaeche testbar.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..scoring.engine import TotalScore

# Spaltenbezeichner der Uebersicht. Die Reihenfolge bestimmt die Anzeige.
COLUMNS: tuple[tuple[str, str], ...] = (
    ("ticker", "Ticker"),
    ("name", "Name"),
    ("sector", "Sektor"),
    ("price", "Kurs"),
    ("change_percent", "Veraenderung"),
    ("score_total", "Gesamtscore"),
    ("score_fundamental", "Fundamental"),
    ("score_technical", "Technik"),
    ("score_analyst", "Analysten"),
    ("score_sentiment", "Sentiment"),
    ("coverage_fundamental", "Abdeckung fundamental"),
    ("market_cap", "Marktkapitalisierung"),
    ("dividend_yield", "Dividendenrendite"),
    ("pe_trailing", "KGV"),
    ("data_age_text", "Datenstand"),
    ("note", "Hinweis"),
)


def _age_hours(moment: datetime | None) -> float | None:
    if moment is None:
        return None
    return max(0.0, (datetime.now(UTC) - moment).total_seconds() / 3600.0)


def _age_text(hours: float | None) -> str:
    if hours is None:
        return "nicht abgerufen"
    if hours < 1.5:
        return f"vor {int(hours * 60)} Min."
    if hours < 48:
        return f"vor {int(hours)} Std."
    return f"vor {int(hours / 24)} Tg."


def build_row(snapshot, score: TotalScore) -> dict[str, Any]:
    """Baut eine Tabellenzeile aus Snapshot und Bewertung.

    Zahlen bleiben Zahlen - so sortiert die Tabelle korrekt und die Filter
    arbeiten auf den Rohwerten. Fehlende Werte bleiben ``None`` und werden von
    der Oberflaeche als n/a dargestellt.
    """
    alter = _age_hours(snapshot.oldest_fetch)
    kategorien = score.categories
    return {
        "ticker": snapshot.ticker,
        "name": snapshot.profile.name or "",
        "sector": snapshot.profile.sector or "",
        "price": snapshot.price,
        "change_percent": snapshot.change_percent,
        "score_total": score.total,
        "score_fundamental": kategorien["fundamental"].score,
        "score_technical": kategorien["technical"].score,
        "score_analyst": kategorien["analyst"].score,
        "score_sentiment": kategorien["sentiment"].score,
        "coverage_fundamental": kategorien["fundamental"].weight_coverage * 100.0,
        "market_cap": snapshot.fundamental.value_of("market_cap"),
        "dividend_yield": snapshot.fundamental.value_of("dividend_yield"),
        "pe_trailing": snapshot.fundamental.value_of("pe_trailing"),
        "data_age_hours": alter,
        "data_age_text": _age_text(alter),
        "note": "Keine Daten abrufbar" if not snapshot.has_any_data else (
            f"{len(snapshot.errors)} Bereich(e) unvollstaendig" if snapshot.errors else ""
        ),
        "is_fund": snapshot.profile.is_fund,
    }


def build_rows(snapshots: dict, scores: dict[str, TotalScore]) -> list[dict[str, Any]]:
    """Baut alle Zeilen, sortiert nach Gesamtscore absteigend.

    Titel ohne Score stehen am Ende - sie sind nicht "schlecht", sondern
    unbewertbar, und werden deshalb nicht unter die bewerteten gemischt.
    """
    zeilen = [build_row(snap, scores[ticker]) for ticker, snap in snapshots.items()]
    return sorted(
        zeilen,
        key=lambda z: (z["score_total"] is None, -(z["score_total"] or 0.0), z["ticker"]),
    )


@dataclass
class OverviewFilter:
    """Filterkriterien der Uebersicht. ``None`` bedeutet: nicht filtern."""

    min_score: float | None = None
    sectors: list[str] = field(default_factory=list)
    min_market_cap: float | None = None
    max_market_cap: float | None = None
    min_dividend_yield: float | None = None
    max_pe: float | None = None
    include_funds: bool = True

    @property
    def is_active(self) -> bool:
        return any(
            (
                self.min_score is not None,
                bool(self.sectors),
                self.min_market_cap is not None,
                self.max_market_cap is not None,
                self.min_dividend_yield is not None,
                self.max_pe is not None,
                not self.include_funds,
            )
        )


@dataclass
class FilterResult:
    """Ergebnis der Filterung samt Begruendung der Ausschluesse."""

    rows: list[dict[str, Any]]
    excluded_by_value: int = 0
    # Ausgeschlossen, weil die gefilterte Kennzahl fehlt - nicht, weil sie die
    # Schwelle verfehlt. Diese Unterscheidung ist wichtig: sonst verschwinden
    # Titel stillschweigend aus der Ansicht.
    excluded_by_missing: int = 0
    missing_tickers: list[str] = field(default_factory=list)

    @property
    def total_excluded(self) -> int:
        return self.excluded_by_value + self.excluded_by_missing


def apply_filters(rows: list[dict[str, Any]], criteria: OverviewFilter) -> FilterResult:
    """Filtert die Zeilen und unterscheidet dabei zwei Ausschlussgruende.

    Ein Titel, dessen gefilterte Kennzahl gar nicht vorliegt, verfehlt die
    Schwelle nicht - er ist nicht pruefbar. Beides wird getrennt gezaehlt, damit
    in der Oberflaeche nicht der Eindruck entsteht, ein Titel sei aussortiert
    worden, obwohl schlicht die Daten fehlen.
    """
    behalten: list[dict[str, Any]] = []
    nach_wert = 0
    nach_fehlend = 0
    fehlende: list[str] = []

    numerische_pruefungen = (
        ("score_total", criteria.min_score, "min"),
        ("market_cap", criteria.min_market_cap, "min"),
        ("market_cap", criteria.max_market_cap, "max"),
        ("dividend_yield", criteria.min_dividend_yield, "min"),
        ("pe_trailing", criteria.max_pe, "max"),
    )

    for zeile in rows:
        if criteria.sectors and zeile["sector"] not in criteria.sectors:
            nach_wert += 1
            continue
        if not criteria.include_funds and zeile.get("is_fund"):
            nach_wert += 1
            continue

        fehlt = False
        verfehlt = False
        for feld, schwelle, richtung in numerische_pruefungen:
            if schwelle is None:
                continue
            wert = zeile.get(feld)
            if wert is None:
                fehlt = True
                break
            if richtung == "min" and wert < schwelle:
                verfehlt = True
                break
            if richtung == "max" and wert > schwelle:
                verfehlt = True
                break

        if fehlt:
            nach_fehlend += 1
            fehlende.append(zeile["ticker"])
            continue
        if verfehlt:
            nach_wert += 1
            continue
        behalten.append(zeile)

    return FilterResult(
        rows=behalten,
        excluded_by_value=nach_wert,
        excluded_by_missing=nach_fehlend,
        missing_tickers=fehlende,
    )


def rows_to_csv(rows: list[dict[str, Any]], *, german: bool = True) -> str:
    """Exportiert die Zeilen als CSV.

    In der deutschen Variante mit Semikolon als Trennzeichen und Komma als
    Dezimaltrennzeichen - so oeffnet Excel die Datei ohne Nachfrage korrekt.
    Fehlende Werte erscheinen als leeres Feld, nicht als 0.
    """
    puffer = io.StringIO()
    schreiber = csv.writer(puffer, delimiter=";" if german else ",", lineterminator="\n")
    schreiber.writerow([label for _, label in COLUMNS])

    for zeile in rows:
        ausgabe = []
        for schluessel, _ in COLUMNS:
            wert = zeile.get(schluessel)
            if wert is None:
                ausgabe.append("")
            elif isinstance(wert, float):
                text = f"{wert:.4f}".rstrip("0").rstrip(".")
                ausgabe.append(text.replace(".", ",") if german else text)
            else:
                ausgabe.append(str(wert))
        schreiber.writerow(ausgabe)
    return puffer.getvalue()


def build_comparison_matrix(
    snapshots: dict, category: str
) -> tuple[list[str], list[dict[str, Any]]]:
    """Stellt eine Kennzahlengruppe mehrerer Titel nebeneinander.

    Rueckgabe: (Ticker-Reihenfolge, Zeilen). Jede Zeile enthaelt die Kennzahl,
    ihre Quelle und je Titel den ``MetricValue`` - die Formatierung uebernimmt
    die Oberflaeche.
    """
    ticker = list(snapshots)
    if not ticker:
        return [], []

    # Reihenfolge der Kennzahlen vom ersten Titel uebernehmen, damit die Matrix
    # stabil bleibt; fehlende Kennzahlen anderer Titel werden ergaenzt.
    schluessel: list[str] = []
    for kuerzel in ticker:
        metrics = getattr(snapshots[kuerzel], category)
        for metric in metrics:
            if metric.key not in schluessel:
                schluessel.append(metric.key)

    zeilen = []
    for key in schluessel:
        eintrag: dict[str, Any] = {"key": key, "label": key}
        for kuerzel in ticker:
            metric = getattr(snapshots[kuerzel], category).get(key)
            if metric is not None:
                eintrag["label"] = metric.label
            eintrag[kuerzel] = metric
        zeilen.append(eintrag)
    return ticker, zeilen
