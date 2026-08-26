"""Berechnung der Teilscores und des Gesamtscores.

Zwei Grundsaetze bestimmen den Aufbau:

1. **Nachvollziehbarkeit.** Jeder Teilscore fuehrt saemtliche Beitraege mit -
   welche Kennzahl mit welchem Wert wie viele Punkte beigesteuert hat und
   warum eine Kennzahl gegebenenfalls nicht eingegangen ist.
2. **Fehlende Daten verfaelschen nichts.** Nicht verfuegbare Kennzahlen gehen
   nicht mit null Punkten ein - sie fallen heraus, der Teilscore wird auf die
   verbleibenden Gewichte normiert und die Abdeckung wird ausgewiesen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import MetricSet, MetricValue
from .definitions import CATEGORY_LABELS, DEFAULT_WEIGHTS, RULES_BY_CATEGORY
from .rules import ScoreMode, ScoreRule
from .sector import PeerComparison, SectorStatistics

# Begruendungen, warum eine Kennzahl nicht in den Score eingeht.
EXCLUDED_MISSING = "Kennzahl nicht verfuegbar"
EXCLUDED_NO_PEERS = "Zu wenige Vergleichstitel derselben Branche"
EXCLUDED_UNKNOWN_CATEGORY = "Auspraegung im Regelwerk nicht hinterlegt"


@dataclass(frozen=True)
class Contribution:
    """Beitrag einer einzelnen Kennzahl zu einem Teilscore."""

    metric: MetricValue
    rule: ScoreRule
    points: float | None = None
    comparison: PeerComparison | None = None
    excluded_reason: str | None = None

    @property
    def included(self) -> bool:
        return self.points is not None and self.excluded_reason is None

    @property
    def weighted_points(self) -> float:
        """Punkte mal Gewicht - der tatsaechliche Beitrag zum Teilscore."""
        return 0.0 if self.points is None else self.points * self.rule.weight

    @property
    def mode_label(self) -> str:
        return str(self.rule.mode)


@dataclass(frozen=True)
class CategoryScore:
    """Ein Teilscore samt vollstaendiger Herleitung."""

    category: str
    score: float | None
    contributions: list[Contribution] = field(default_factory=list)

    @property
    def label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)

    @property
    def included(self) -> list[Contribution]:
        return [c for c in self.contributions if c.included]

    @property
    def excluded(self) -> list[Contribution]:
        return [c for c in self.contributions if not c.included]

    @property
    def used_count(self) -> int:
        return len(self.included)

    @property
    def total_count(self) -> int:
        return len(self.contributions)

    @property
    def weight_coverage(self) -> float:
        """Anteil der tatsaechlich genutzten Gewichtung (0.0-1.0)."""
        total = sum(c.rule.weight for c in self.contributions)
        if total <= 0:
            return 0.0
        return sum(c.rule.weight for c in self.included) / total

    @property
    def is_available(self) -> bool:
        return self.score is not None

    @property
    def coverage_text(self) -> str:
        """Abdeckungshinweis, wie er in der Oberflaeche erscheint."""
        if not self.is_available:
            return f"{self.label}-Score: n/a - keine der {self.total_count} Kennzahlen verfuegbar"
        return (
            f"{self.label}-Score: {self.score:.0f} - basiert auf {self.used_count} von "
            f"{self.total_count} Kennzahlen ({self.weight_coverage * 100:.0f} % der Gewichtung)"
        )


@dataclass(frozen=True)
class TotalScore:
    """Gesamtscore und alle Teilscores eines Titels."""

    ticker: str
    total: float | None
    categories: dict[str, CategoryScore] = field(default_factory=dict)
    # Tatsaechlich verwendete Gewichte nach Umverteilung nicht verfuegbarer Teilscores.
    effective_weights: dict[str, float] = field(default_factory=dict)
    requested_weights: dict[str, float] = field(default_factory=dict)

    @property
    def is_available(self) -> bool:
        return self.total is not None

    @property
    def redistributed(self) -> list[str]:
        """Teilscores, deren Gewicht mangels Daten umverteilt wurde."""
        return [
            CATEGORY_LABELS.get(name, name)
            for name, weight in self.requested_weights.items()
            if weight > 0 and self.effective_weights.get(name, 0.0) == 0.0
        ]


def score_category(
    category: str,
    metrics: MetricSet,
    *,
    sector: str | None = None,
    statistics: SectorStatistics | None = None,
) -> CategoryScore:
    """Berechnet einen Teilscore aus den Regeln der Kategorie."""
    rules = RULES_BY_CATEGORY.get(category, ())
    contributions: list[Contribution] = []

    for rule in rules:
        metric = metrics.get(rule.metric_key)
        if metric is None or not metric.is_available:
            placeholder = metric or MetricValue.missing(rule.metric_key, rule.metric_key)
            contributions.append(
                Contribution(metric=placeholder, rule=rule, excluded_reason=EXCLUDED_MISSING)
            )
            continue

        if rule.mode is ScoreMode.CATEGORICAL:
            points = rule.score_categorical(metric.text or "")
            contributions.append(
                Contribution(
                    metric=metric, rule=rule, points=points,
                    excluded_reason=None if points is not None else EXCLUDED_UNKNOWN_CATEGORY,
                )
            )
            continue

        if metric.value is None:
            contributions.append(
                Contribution(metric=metric, rule=rule, excluded_reason=EXCLUDED_MISSING)
            )
            continue

        if rule.mode is ScoreMode.ABSOLUTE:
            contributions.append(
                Contribution(metric=metric, rule=rule, points=rule.score_absolute(metric.value))
            )
            continue

        # Sektorrelativ: ohne ausreichende Vergleichsgruppe wird nicht bewertet.
        comparison = (
            statistics.compare(
                sector, rule.metric_key, metric.value, higher_is_better=rule.higher_is_better
            )
            if statistics is not None
            else None
        )
        if comparison is None:
            contributions.append(
                Contribution(metric=metric, rule=rule, excluded_reason=EXCLUDED_NO_PEERS)
            )
            continue

        contributions.append(
            Contribution(
                metric=metric, rule=rule, points=comparison.percentile, comparison=comparison
            )
        )

    included = [c for c in contributions if c.included]
    weight_sum = sum(c.rule.weight for c in included)
    score = None if weight_sum <= 0 else sum(c.weighted_points for c in included) / weight_sum
    return CategoryScore(category=category, score=score, contributions=contributions)


def score_snapshot(
    snapshot,
    *,
    statistics: SectorStatistics | None = None,
    weights: dict[str, float] | None = None,
) -> TotalScore:
    """Berechnet alle Teilscores und den gewichteten Gesamtscore eines Titels.

    Nicht berechenbare Teilscores erhalten das Gewicht null; die uebrigen
    Gewichte werden proportional hochskaliert. Damit bleibt der Gesamtscore auf
    derselben Skala, ohne dass ein fehlender Bereich stillschweigend als
    Nullwert einfliesst.
    """
    requested = dict(weights or DEFAULT_WEIGHTS)
    sector = snapshot.profile.sector if snapshot.profile is not None else None

    categories = {
        "fundamental": score_category(
            "fundamental", snapshot.fundamental, sector=sector, statistics=statistics
        ),
        "technical": score_category(
            "technical", snapshot.technical, sector=sector, statistics=statistics
        ),
        "analyst": score_category(
            "analyst", snapshot.analyst, sector=sector, statistics=statistics
        ),
        "sentiment": score_category(
            "sentiment", MetricSet({}), sector=sector, statistics=statistics
        ),
    }

    usable = {
        name: requested.get(name, 0.0)
        for name, result in categories.items()
        if result.is_available and requested.get(name, 0.0) > 0
    }
    weight_sum = sum(usable.values())

    if weight_sum <= 0:
        effective = dict.fromkeys(categories, 0.0)
        total = None
    else:
        effective = {
            name: (usable.get(name, 0.0) / weight_sum) for name in categories
        }
        total = sum(
            categories[name].score * share for name, share in effective.items() if share > 0
        )

    return TotalScore(
        ticker=snapshot.ticker,
        total=total,
        categories=categories,
        effective_weights=effective,
        requested_weights=requested,
    )


def normalise_weights(weights: dict[str, float]) -> dict[str, float]:
    """Skaliert Gewichte auf die Summe 1. Bei Summe null bleiben alle bei null."""
    total = sum(max(0.0, value) for value in weights.values())
    if total <= 0:
        return dict.fromkeys(weights, 0.0)
    return {name: max(0.0, value) / total for name, value in weights.items()}
