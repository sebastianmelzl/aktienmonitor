"""Backtest des technischen Teilscores - ohne Netz und ohne Oberflaeche.

**Warum nur der technische Teilscore.** Ein Backtest muss an jedem
vergangenen Stichtag mit genau den Daten rechnen, die an diesem Tag bekannt
waren - alles andere ist Lookahead. Fundamentaldaten, Analystenschaetzungen
und Schlagzeilen-Sentiment liegen aus kostenlosen Quellen nicht als
Zeitreihe vor: yfinance liefert nur den *aktuellen* Bilanzstand, nicht den
Stand, der vor zwei Jahren galt. Ein Test dieser Teilscores wuerde entweder
das heutige Wissen in die Vergangenheit projizieren oder Werte erfinden -
beides verletzt die zentrale Regel des Projekts. Der technische Teilscore
ist die Ausnahme: er stammt vollstaendig aus der Kurshistorie, und jede
Kennzahl darin (SMA, RSI, MACD, Momentum, ...) laesst sich an jedem
Stichtag ausschliesslich aus vorangegangenen Kursen neu berechnen.

**Was trotzdem ungeloest bleibt** - siehe ``LIMITATIONS``:
Survivorship Bias (nur die heutige Watchlist, keine damaligen, seither
ausgeschiedenen Titel), kleine Stichproben je Titel, ueberlappende
Zeitfenster ohne Unabhaengigkeit der Beobachtungen bei kurzem ``step_days``,
keine Transaktionskosten oder Steuern, und keine Garantie, dass ein
Zusammenhang der Vergangenheit fortbesteht.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from ..benchmark.compare import return_between
from ..metrics.technical import compute_technical_metrics
from ..scoring.engine import score_category

LIMITATIONS: tuple[str, ...] = (
    "Nur der technische Teilscore wird getestet - fundamentale, Analysten- und "
    "Sentiment-Kennzahlen liegen nicht als Zeitreihe vor.",
    "Survivorship Bias: getestet wird die heutige Watchlist, nicht die "
    "historische Zusammensetzung eines Index. Titel, die zwischenzeitlich "
    "ausgeschieden sind (Insolvenz, Übernahme, Delisting), fehlen.",
    "Die Stichprobe je Titel ist klein, und bei kurzem Abstand zwischen den "
    "Stichtagen überlappen sich die Bewertungsfenster - das sind keine "
    "unabhängigen Beobachtungen.",
    "Weder Transaktionskosten noch Steuern noch Spread sind eingerechnet.",
    "Ein Zusammenhang in der Vergangenheit ist keine Garantie für die Zukunft "
    "- das Regelwerk wurde nicht auf diese Daten hin optimiert, aber auch "
    "nicht an ihnen widerlegt.",
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


def _sorted_bars(bars: list[dict]) -> list[tuple[date, dict]]:
    """Kerzen aufsteigend sortiert, mit geparstem Datum - ungueltige verworfen."""
    paare: list[tuple[date, dict]] = []
    for bar in bars or []:
        stamp = _to_date(bar.get("date"))
        close = bar.get("close")
        if stamp is None or not isinstance(close, int | float) or isinstance(close, bool):
            continue
        if close <= 0:
            continue
        paare.append((stamp, bar))
    paare.sort(key=lambda paar: paar[0])
    return paare


@dataclass(frozen=True)
class WalkForwardPoint:
    """Ein Stichtag: Teilscore aus der bis dahin bekannten Historie, Folgerendite."""

    date: date
    technical_score: float | None
    weight_coverage: float
    forward_return: float | None
    benchmark_forward_return: float | None

    @property
    def excess_return(self) -> float | None:
        if self.forward_return is None or self.benchmark_forward_return is None:
            return None
        return self.forward_return - self.benchmark_forward_return

    @property
    def usable(self) -> bool:
        return self.technical_score is not None and self.forward_return is not None


def walk_forward(
    bars: list[dict],
    *,
    horizon_days: int,
    step_days: int = 21,
    min_history_days: int = 210,
    benchmark_bars: list[dict] | None = None,
) -> list[WalkForwardPoint]:
    """Rollierender Test ohne Lookahead: Score am Stichtag, Rendite danach.

    An jedem ``step_days``-ten Handelstag ab ``min_history_days`` wird der
    technische Teilscore ausschliesslich aus den Kursen *bis einschliesslich*
    dieses Tages berechnet - kein spaeterer Kurs fliesst ein. Gemessen wird
    anschliessend die tatsaechliche Kursrendite der folgenden
    ``horizon_days`` Handelstage sowie, sofern ``benchmark_bars`` mitgegeben
    ist, die Rendite der Referenz ueber denselben Kalenderzeitraum.
    """
    sortiert = _sorted_bars(bars)
    n = len(sortiert)
    if n < min_history_days + horizon_days + 1:
        return []

    punkte: list[WalkForwardPoint] = []
    i = min_history_days
    while i + horizon_days < n:
        historie = [bar for _, bar in sortiert[: i + 1]]
        stichtag, letzte_kerze = sortiert[i]
        ziel_datum, ziel_kerze = sortiert[i + horizon_days]

        technical = compute_technical_metrics(historie)
        kategorie = score_category("technical", technical)

        einstieg = letzte_kerze.get("close")
        ausstieg = ziel_kerze.get("close")
        rendite = None
        if isinstance(einstieg, int | float) and einstieg > 0 and isinstance(ausstieg, int | float):
            rendite = (float(ausstieg) / float(einstieg) - 1.0) * 100.0

        referenz = (
            return_between(benchmark_bars, stichtag, ziel_datum) if benchmark_bars else None
        )

        punkte.append(
            WalkForwardPoint(
                date=stichtag,
                technical_score=kategorie.score,
                weight_coverage=kategorie.weight_coverage,
                forward_return=rendite,
                benchmark_forward_return=referenz,
            )
        )
        i += step_days

    return punkte


@dataclass(frozen=True)
class ScoreBucket:
    """Zusammenfassung aller Beobachtungen in einem Score-Terzil."""

    label: str
    lower: float
    upper: float
    points: list[WalkForwardPoint] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.points)

    @property
    def mean_forward_return(self) -> float | None:
        werte = [p.forward_return for p in self.points if p.forward_return is not None]
        return sum(werte) / len(werte) if werte else None

    @property
    def mean_benchmark_return(self) -> float | None:
        werte = [p.benchmark_forward_return for p in self.points if p.benchmark_forward_return is not None]
        return sum(werte) / len(werte) if werte else None

    @property
    def win_rate(self) -> float | None:
        """Anteil der Beobachtungen mit positivem Vorsprung gegenueber der Referenz."""
        vergleichbar = [p for p in self.points if p.excess_return is not None]
        if not vergleichbar:
            return None
        gewonnen = sum(1 for p in vergleichbar if p.excess_return > 0)
        return gewonnen / len(vergleichbar) * 100.0


def bucket_by_score(points: list[WalkForwardPoint], *, buckets: int = 3) -> list[ScoreBucket]:
    """Teilt die Beobachtungen nach technischem Score in gleich grosse Terzile.

    Terzile statt fixer Score-Schwellen, weil die Verteilung des Scores je
    nach Titelmix stark schwanken kann - gleich grosse Gruppen machen den
    Vergleich zwischen ihnen aussagekraeftiger als beliebig gewaehlte
    Schwellenwerte.
    """
    verwendbar = sorted(
        (p for p in points if p.technical_score is not None), key=lambda p: p.technical_score
    )
    if not verwendbar:
        return []

    n = len(verwendbar)
    groesse = max(1, -(-n // buckets))  # aufrunden
    labels = ["Unteres Drittel", "Mittleres Drittel", "Oberes Drittel"] if buckets == 3 else None

    ergebnis: list[ScoreBucket] = []
    for index in range(buckets):
        start = index * groesse
        ende = min(n, start + groesse)
        if start >= n:
            break
        gruppe = verwendbar[start:ende]
        label = labels[index] if labels else f"Gruppe {index + 1}"
        ergebnis.append(
            ScoreBucket(
                label=label,
                lower=gruppe[0].technical_score,
                upper=gruppe[-1].technical_score,
                points=gruppe,
            )
        )
    return ergebnis


def pearson_correlation(points: list[WalkForwardPoint]) -> float | None:
    """Korrelation zwischen technischem Score und Folgerendite.

    Ohne externe Abhaengigkeiten berechnet - unter 5 Beobachtungen wird kein
    Wert ausgewiesen, weil eine Korrelation aus so wenigen Punkten kaum mehr
    als Zufall abbildet.
    """
    paare = [(p.technical_score, p.forward_return) for p in points if p.usable]
    if len(paare) < 5:
        return None

    xs = [x for x, _ in paare]
    ys = [y for _, y in paare]
    n = len(paare)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    cov = sum((x - mean_x) * (y - mean_y) for x, y in paare)
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    nenner = (var_x * var_y) ** 0.5
    return cov / nenner if nenner > 0 else None


__all__ = [
    "LIMITATIONS",
    "ScoreBucket",
    "WalkForwardPoint",
    "bucket_by_score",
    "pearson_correlation",
    "walk_forward",
]
