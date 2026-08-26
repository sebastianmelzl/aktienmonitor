"""Bausteine des Bewertungsregelwerks.

Eine ``ScoreRule`` beschreibt, wie genau eine Kennzahl in Punkte von 0 bis 100
uebersetzt wird. Die Regeln stehen bewusst als Daten und nicht als Code: so
laesst sich jede Bewertung in der Oberflaeche aufklappen und bis zur Rohzahl
zurueckverfolgen.

Es gibt drei Bewertungsarten:

* **absolut** - die Kennzahl hat einen ueber Branchen hinweg sinnvollen
  Massstab (Eigenkapitalquote, RSI, Verschuldungsgrad).
* **Sektor-Perzentil** - die Kennzahl ist nur im Branchenvergleich aussagekraeftig
  (KGV, KUV, Margen). Bewertet wird der Rang innerhalb der Vergleichsgruppe.
* **kategorial** - die Kennzahl ist Text (etwa das SMA-Kreuzungssignal).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

MIN_POINTS = 0.0
MAX_POINTS = 100.0


class ScoreMode(StrEnum):
    ABSOLUTE = "absolut"
    SECTOR_RELATIVE = "Sektor-Perzentil"
    CATEGORICAL = "kategorial"


def piecewise_score(value: float, breakpoints: tuple[tuple[float, float], ...]) -> float:
    """Uebersetzt einen Wert anhand von Stuetzstellen linear in Punkte.

    ``breakpoints`` ist eine nach dem Kennzahlenwert aufsteigend sortierte Folge
    von ``(wert, punkte)``. Zwischen zwei Stuetzstellen wird linear
    interpoliert, ausserhalb wird auf die Randpunkte begrenzt. Die Punktefolge
    muss nicht monoton sein - so lassen sich auch Kennzahlen mit einem guenstigen
    Mittelbereich abbilden (etwa die Ausschuettungsquote).
    """
    if not breakpoints:
        raise ValueError("breakpoints darf nicht leer sein")

    values = [point[0] for point in breakpoints]
    if values != sorted(values):
        raise ValueError("breakpoints muessen aufsteigend nach Kennzahlenwert sortiert sein")

    if value <= breakpoints[0][0]:
        return _clamp(breakpoints[0][1])
    if value >= breakpoints[-1][0]:
        return _clamp(breakpoints[-1][1])

    for (x_low, y_low), (x_high, y_high) in zip(breakpoints, breakpoints[1:], strict=False):
        if x_low <= value <= x_high:
            if x_high == x_low:
                return _clamp(y_high)
            share = (value - x_low) / (x_high - x_low)
            return _clamp(y_low + share * (y_high - y_low))

    # Unerreichbar, solange die Stuetzstellen sortiert sind.
    return _clamp(breakpoints[-1][1])


def _clamp(points: float) -> float:
    return max(MIN_POINTS, min(MAX_POINTS, float(points)))


@dataclass(frozen=True)
class ScoreRule:
    """Bewertungsvorschrift fuer genau eine Kennzahl."""

    metric_key: str
    weight: float
    mode: ScoreMode
    # Nur bei ScoreMode.ABSOLUTE: Stuetzstellen (Wert -> Punkte).
    breakpoints: tuple[tuple[float, float], ...] = ()
    # Nur bei ScoreMode.SECTOR_RELATIVE: Richtung der Bewertung.
    higher_is_better: bool = True
    # Nur bei ScoreMode.CATEGORICAL: Zuordnung Text -> Punkte.
    categories: tuple[tuple[str, float], ...] = ()
    # Begruendung der Regel - wird in der Oberflaeche angezeigt.
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ValueError(f"{self.metric_key}: Gewicht muss groesser als 0 sein")
        if self.mode is ScoreMode.ABSOLUTE and not self.breakpoints:
            raise ValueError(f"{self.metric_key}: absolute Bewertung braucht Stuetzstellen")
        if self.mode is ScoreMode.CATEGORICAL and not self.categories:
            raise ValueError(f"{self.metric_key}: kategoriale Bewertung braucht Zuordnungen")

    def score_absolute(self, value: float) -> float:
        return piecewise_score(value, self.breakpoints)

    def score_categorical(self, text: str) -> float | None:
        """Punkte fuer einen Textwert; ``None`` bei unbekannter Auspraegung.

        Eine unbekannte Auspraegung wird nicht geraten, sondern faellt aus der
        Bewertung heraus und senkt die ausgewiesene Datenabdeckung.
        """
        for category, points in self.categories:
            if category == text:
                return _clamp(points)
        return None
