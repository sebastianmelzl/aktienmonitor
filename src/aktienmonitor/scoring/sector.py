"""Sektorvergleich.

Kennzahlen wie das KGV sind absolut kaum vergleichbar: Banken handeln
strukturell niedriger als Softwarehaeuser. Ein absoluter Massstab wuerde
deshalb immer dieselben Branchen nach oben spuelen. Bewertet wird darum der
Rang innerhalb der eigenen Branche.

Die Vergleichsgruppe ist das eigene beobachtete Universum - eine kostenlose
Quelle fuer echte Sektor-Mediane gibt es nicht. Das hat eine wichtige Folge:
**der Sektorvergleich ist relativ zur eigenen Watchlist**, nicht zum
Gesamtmarkt. Bei zu kleiner Vergleichsgruppe wird gar nicht bewertet, statt
einen Rang aus zwei Titeln zu behaupten.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field

from ..models import MetricSet

# Ab wie vielen Titeln derselben Branche ein Perzentilrang gebildet wird.
DEFAULT_MIN_PEERS = 3

# Sammelbezeichnung fuer Titel ohne Branchenangabe.
SECTOR_UNKNOWN = "Ohne Branchenangabe"


@dataclass(frozen=True)
class PeerComparison:
    """Ergebnis eines Sektorvergleichs fuer eine Kennzahl."""

    sector: str
    metric_key: str
    value: float
    percentile: float
    peer_count: int
    median: float

    @property
    def summary(self) -> str:
        return (
            f"Rang {self.percentile:.0f}. Perzentil in '{self.sector}' "
            f"(Median {self.median:.2f}, {self.peer_count} Vergleichstitel)"
        )


@dataclass
class SectorStatistics:
    """Kennzahlenverteilung je Branche, gebildet aus dem eigenen Universum."""

    min_peers: int = DEFAULT_MIN_PEERS
    # {Branche: {Kennzahl: [Werte]}}
    values: dict[str, dict[str, list[float]]] = field(default_factory=dict)

    @classmethod
    def from_universe(
        cls,
        entries: Iterable[tuple[str, MetricSet]],
        *,
        min_peers: int = DEFAULT_MIN_PEERS,
    ) -> SectorStatistics:
        """Baut die Statistik aus ``(Branche, Kennzahlen)``-Paaren des Universums."""
        stats = cls(min_peers=min_peers)
        for sector, metrics in entries:
            bucket = stats.values.setdefault(sector or SECTOR_UNKNOWN, {})
            for metric in metrics:
                if metric.value is None:
                    continue
                bucket.setdefault(metric.key, []).append(float(metric.value))
        return stats

    def peer_values(self, sector: str | None, metric_key: str) -> list[float]:
        return list(self.values.get(sector or SECTOR_UNKNOWN, {}).get(metric_key, []))

    def peer_count(self, sector: str | None, metric_key: str) -> int:
        return len(self.peer_values(sector, metric_key))

    def median(self, sector: str | None, metric_key: str) -> float | None:
        peers = self.peer_values(sector, metric_key)
        return statistics.median(peers) if peers else None

    def compare(
        self, sector: str | None, metric_key: str, value: float, *, higher_is_better: bool
    ) -> PeerComparison | None:
        """Perzentilrang eines Werts in seiner Branche.

        Der Rang folgt der ueblichen Definition
        ``(schlechtere + 0.5 * gleiche) / Anzahl * 100``: 100 heisst bester Wert
        der Gruppe, 0 der schlechteste. Bei ``higher_is_better=False`` gilt ein
        niedrigerer Kennzahlenwert als besser.

        Ergebnis ``None``, wenn die Vergleichsgruppe zu klein ist - ein Rang aus
        zwei Titeln waere keine Aussage.
        """
        peers = self.peer_values(sector, metric_key)
        if len(peers) < self.min_peers:
            return None

        if higher_is_better:
            worse = sum(1 for peer in peers if peer < value)
        else:
            worse = sum(1 for peer in peers if peer > value)
        equal = sum(1 for peer in peers if peer == value)

        percentile = (worse + 0.5 * equal) / len(peers) * 100.0
        return PeerComparison(
            sector=sector or SECTOR_UNKNOWN,
            metric_key=metric_key,
            value=value,
            percentile=percentile,
            peer_count=len(peers),
            median=statistics.median(peers),
        )

    @property
    def sectors(self) -> list[str]:
        return sorted(self.values)

    def coverage_report(self) -> list[dict[str, object]]:
        """Uebersicht, welche Branchen ueberhaupt gross genug fuer Vergleiche sind."""
        report = []
        for sector in self.sectors:
            metrics = self.values[sector]
            largest = max((len(v) for v in metrics.values()), default=0)
            report.append(
                {
                    "Branche": sector,
                    "Titel mit Daten": largest,
                    "Vergleich moeglich": "ja" if largest >= self.min_peers else "nein",
                }
            )
        return report
