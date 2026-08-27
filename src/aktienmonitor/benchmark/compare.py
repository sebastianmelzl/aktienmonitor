"""Renditevergleich zwischen einem Titel und einer Referenz.

Reine Rechenlogik auf Kursreihen - ohne Netz und ohne Oberflaeche.

Wichtige Einschraenkung, die ueberall mitgefuehrt wird: verglichen werden
**Kursrenditen**. Dividenden sind nicht enthalten, solange die Kursreihe nicht
um sie bereinigt ist. Bei ausschuettenden Titeln und Indizes wird der Vergleich
dadurch verzerrt - zulasten des Titels mit der hoeheren Ausschuettung.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

# Uebliche Vergleichszeitraeume in Handelstagen.
PERIODS: tuple[tuple[str, int], ...] = (
    ("1 Monat", 21),
    ("3 Monate", 63),
    ("6 Monate", 126),
    ("1 Jahr", 252),
    ("3 Jahre", 756),
)


def _to_date(value: object) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def closes_by_date(bars: list[dict]) -> list[tuple[date, float]]:
    """Wandelt Rohkerzen in eine aufsteigende Liste aus (Datum, Schlusskurs)."""
    reihe: list[tuple[date, float]] = []
    for bar in bars or []:
        stamp = _to_date(bar.get("date"))
        close = bar.get("close")
        if stamp is None or not isinstance(close, int | float) or isinstance(close, bool):
            continue
        if close <= 0:
            continue
        reihe.append((stamp, float(close)))
    reihe.sort(key=lambda pair: pair[0])
    return reihe


def total_return(bars: list[dict], *, trading_days: int) -> float | None:
    """Kursrendite ueber die letzten ``trading_days`` Handelstage, in Prozent."""
    reihe = closes_by_date(bars)
    if len(reihe) < trading_days + 1:
        return None
    start = reihe[-(trading_days + 1)][1]
    ende = reihe[-1][1]
    if start <= 0:
        return None
    return (ende / start - 1.0) * 100.0


def return_between(bars: list[dict], start: date, end: date | None = None) -> float | None:
    """Kursrendite zwischen zwei Datumsangaben, in Prozent.

    Es wird der jeweils letzte Kurs *bis einschliesslich* des Stichtags genutzt -
    an Wochenenden und Feiertagen gibt es keinen.
    """
    reihe = closes_by_date(bars)
    if not reihe:
        return None
    ziel_ende = end or reihe[-1][0]

    def kurs_am(stichtag: date) -> float | None:
        passend = [wert for stamp, wert in reihe if stamp <= stichtag]
        return passend[-1] if passend else None

    anfangskurs = kurs_am(start)
    endkurs = kurs_am(ziel_ende)
    if anfangskurs is None or endkurs is None or anfangskurs <= 0:
        return None
    return (endkurs / anfangskurs - 1.0) * 100.0


@dataclass(frozen=True)
class PeriodComparison:
    """Ein Zeitraum im Vergleich."""

    label: str
    trading_days: int
    subject: float | None
    benchmark: float | None

    @property
    def excess(self) -> float | None:
        """Vorsprung in Prozentpunkten - None, wenn eine Seite fehlt."""
        if self.subject is None or self.benchmark is None:
            return None
        return self.subject - self.benchmark

    @property
    def beats_benchmark(self) -> bool | None:
        vorsprung = self.excess
        return None if vorsprung is None else vorsprung > 0


@dataclass(frozen=True)
class BenchmarkComparison:
    """Vergleich eines Titels mit der Referenz ueber mehrere Zeitraeume."""

    ticker: str
    benchmark_ticker: str
    periods: list[PeriodComparison]

    @property
    def available(self) -> list[PeriodComparison]:
        return [p for p in self.periods if p.excess is not None]

    @property
    def wins(self) -> int:
        return sum(1 for p in self.available if p.beats_benchmark)

    @property
    def summary(self) -> str:
        verfuegbar = self.available
        if not verfuegbar:
            return "Kein Vergleich moeglich - zu wenig gemeinsame Kurshistorie."
        return (
            f"In {self.wins} von {len(verfuegbar)} Zeitraeumen besser als "
            f"{self.benchmark_ticker}"
        )


def compare(
    ticker: str,
    bars: list[dict],
    benchmark_ticker: str,
    benchmark_bars: list[dict],
    *,
    periods: tuple[tuple[str, int], ...] = PERIODS,
) -> BenchmarkComparison:
    """Stellt Titel und Referenz ueber mehrere Zeitraeume gegenueber."""
    vergleiche = [
        PeriodComparison(
            label=label,
            trading_days=tage,
            subject=total_return(bars, trading_days=tage),
            benchmark=total_return(benchmark_bars, trading_days=tage),
        )
        for label, tage in periods
    ]
    return BenchmarkComparison(
        ticker=ticker, benchmark_ticker=benchmark_ticker, periods=vergleiche
    )


def annualised(total_percent: float, days: int) -> float | None:
    """Rechnet eine Gesamtrendite auf ein Jahr um."""
    if days <= 0:
        return None
    jahre = days / 365.25
    if jahre <= 0:
        return None
    faktor = 1.0 + total_percent / 100.0
    if faktor <= 0:
        return None
    return ((faktor ** (1.0 / jahre)) - 1.0) * 100.0


def since_date_comparison(
    bars: list[dict], benchmark_bars: list[dict], start: date
) -> tuple[float | None, float | None, float | None]:
    """Rendite von Titel und Referenz seit einem Stichtag plus Vorsprung."""
    titel = return_between(bars, start)
    referenz = return_between(benchmark_bars, start)
    vorsprung = None if titel is None or referenz is None else titel - referenz
    return titel, referenz, vorsprung


def trading_days_between(start: date, end: date) -> int:
    """Naeherung: Handelstage zwischen zwei Daten."""
    tage = max(0, (end - start).days)
    return int(tage * 252 / 365.25)


def period_start(trading_days: int, *, today: date | None = None) -> date:
    """Kalenderdatum, das etwa ``trading_days`` Handelstage zurueckliegt."""
    basis = today or date.today()
    return basis - timedelta(days=int(trading_days * 365.25 / 252))
