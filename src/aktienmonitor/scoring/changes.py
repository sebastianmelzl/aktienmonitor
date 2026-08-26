"""Erkennung von Veraenderungen zwischen zwei Staenden.

Eine Rangliste beantwortet die Frage "wer steht oben". Nuetzlicher ist oft
"wo hat sich etwas bewegt": ein Titel, dessen Score seit dem letzten Lauf
deutlich gestiegen ist, verdient einen Blick, auch wenn er nicht ganz vorne
liegt.

Wie das uebrige Rechenwerk arbeitet dieses Modul ohne Netz und ohne
Oberflaeche: es bekommt einen Snapshot, seine Bewertung und den vorherigen
Verlaufseintrag und gibt Ereignisse zurueck.

Alle Schwellen sind Konvention, keine belegte Prognosekraft - sie bestimmen
lediglich, ab wann eine Bewegung erwaehnenswert ist.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..storage.history import HistoryEntry


class ChangeKind(StrEnum):
    SCORE_UP = "Score gestiegen"
    SCORE_DOWN = "Score gefallen"
    THRESHOLD_UP = "Schwelle ueberschritten"
    THRESHOLD_DOWN = "Schwelle unterschritten"
    CATEGORY_UP = "Teilscore gestiegen"
    CATEGORY_DOWN = "Teilscore gefallen"
    GOLDEN_CROSS = "Golden Cross"
    DEATH_CROSS = "Death Cross"
    REVISIONS_POSITIVE = "Revisionen gedreht (positiv)"
    REVISIONS_NEGATIVE = "Revisionen gedreht (negativ)"
    PRICE_DROP_STABLE = "Kurs gefallen, Fundamentaldaten stabil"
    COVERAGE_UP = "Datenlage verbessert"


# Ab wann eine Bewegung als Ereignis gilt.
SCORE_DELTA_MIN = 8.0
CATEGORY_DELTA_MIN = 12.0
COVERAGE_DELTA_MIN = 15.0
PRICE_DROP_MIN = -12.0
# Als "stabil" gilt der Fundamental-Teilscore, wenn er sich um weniger als das
# bewegt hat - dann ist der Kursrueckgang nicht durch schlechtere Zahlen erklaert.
FUNDAMENTAL_STABLE_BAND = 3.0
DEFAULT_THRESHOLD = 70.0

CATEGORY_LABELS = {
    "fundamental": "Fundamental",
    "technical": "Technik",
    "analyst": "Analysten",
    "sentiment": "Sentiment",
}


@dataclass(frozen=True)
class ChangeEvent:
    """Ein einzelnes Ereignis an einem Titel."""

    kind: ChangeKind
    detail: str
    # Betrag der Bewegung - dient nur der Sortierung nach Auffaelligkeit.
    magnitude: float = 0.0
    # +1 aufwaerts, -1 abwaerts, 0 richtungslos
    direction: int = 0

    @property
    def label(self) -> str:
        return str(self.kind)

    @property
    def is_positive(self) -> bool:
        return self.direction > 0

    @property
    def is_negative(self) -> bool:
        return self.direction < 0


@dataclass(frozen=True)
class TickerChanges:
    """Alle Ereignisse eines Titels samt Bezugspunkt."""

    ticker: str
    events: list[ChangeEvent]
    previous: HistoryEntry | None = None
    score_delta: float | None = None

    @property
    def has_events(self) -> bool:
        return bool(self.events)

    @property
    def relevance(self) -> float:
        """Auffaelligkeit fuer die Sortierung: staerkstes Ereignis zaehlt."""
        return max((e.magnitude for e in self.events), default=0.0)

    @property
    def reference_text(self) -> str:
        if self.previous is None:
            return "kein Vergleichsstand"
        tage = self.previous.age_days
        if tage < 1.5:
            return "gegenueber gestern"
        if tage < 45:
            return f"gegenueber vor {tage:.0f} Tagen"
        return f"gegenueber {self.previous.recorded_at:%d.%m.%Y}"


def _delta(current: float | None, earlier: float | None) -> float | None:
    if current is None or earlier is None:
        return None
    return current - earlier


def detect_changes(
    snapshot,
    scored,
    previous: HistoryEntry | None,
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> TickerChanges:
    """Ermittelt die Ereignisse eines Titels gegenueber seinem Vorstand.

    Ereignisse, die keinen Vergleichsstand brauchen (ein frisches Kreuzen der
    Durchschnitte), werden auch beim allerersten Lauf gemeldet.
    """
    events: list[ChangeEvent] = []

    # --- Ereignisse ohne Vergleichsstand -------------------------------------
    ma_cross = snapshot.technical.get("ma_cross")
    if ma_cross is not None and ma_cross.is_available:
        # Die Kennzahl meldet nur ein Kreuzen der letzten 30 Tage - sie ist
        # damit selbst schon ein Ereignis.
        if ma_cross.text == "Golden Cross":
            events.append(
                ChangeEvent(
                    ChangeKind.GOLDEN_CROSS,
                    "SMA 50 hat SMA 200 von unten nach oben gekreuzt (letzte 30 Tage)",
                    magnitude=20.0,
                    direction=1,
                )
            )
        elif ma_cross.text == "Death Cross":
            events.append(
                ChangeEvent(
                    ChangeKind.DEATH_CROSS,
                    "SMA 50 hat SMA 200 von oben nach unten gekreuzt (letzte 30 Tage)",
                    magnitude=20.0,
                    direction=-1,
                )
            )

    if previous is None:
        return TickerChanges(ticker=snapshot.ticker, events=events, previous=None)

    # --- Gesamtscore ---------------------------------------------------------
    score_delta = _delta(scored.total, previous.total)
    if score_delta is not None and abs(score_delta) >= SCORE_DELTA_MIN:
        aufwaerts = score_delta > 0
        events.append(
            ChangeEvent(
                ChangeKind.SCORE_UP if aufwaerts else ChangeKind.SCORE_DOWN,
                f"Gesamtscore {previous.total:.0f} -> {scored.total:.0f} "
                f"({score_delta:+.0f} Punkte)",
                magnitude=abs(score_delta),
                direction=1 if aufwaerts else -1,
            )
        )

    # --- Schwellenuebertritt -------------------------------------------------
    if scored.total is not None and previous.total is not None:
        if previous.total < threshold <= scored.total:
            events.append(
                ChangeEvent(
                    ChangeKind.THRESHOLD_UP,
                    f"Gesamtscore hat {threshold:.0f} ueberschritten "
                    f"({previous.total:.0f} -> {scored.total:.0f})",
                    magnitude=25.0,
                    direction=1,
                )
            )
        elif scored.total < threshold <= previous.total:
            events.append(
                ChangeEvent(
                    ChangeKind.THRESHOLD_DOWN,
                    f"Gesamtscore ist unter {threshold:.0f} gefallen "
                    f"({previous.total:.0f} -> {scored.total:.0f})",
                    magnitude=25.0,
                    direction=-1,
                )
            )

    # --- Teilscores ----------------------------------------------------------
    for name, label in CATEGORY_LABELS.items():
        aktuell = scored.categories[name].score
        vorher = getattr(previous, name, None)
        delta = _delta(aktuell, vorher)
        if delta is None or abs(delta) < CATEGORY_DELTA_MIN:
            continue
        aufwaerts = delta > 0
        events.append(
            ChangeEvent(
                ChangeKind.CATEGORY_UP if aufwaerts else ChangeKind.CATEGORY_DOWN,
                f"{label} {vorher:.0f} -> {aktuell:.0f} ({delta:+.0f} Punkte)",
                magnitude=abs(delta),
                direction=1 if aufwaerts else -1,
            )
        )

    # --- Revisionssaldo dreht ------------------------------------------------
    saldo = snapshot.analyst.value_of("revision_balance")
    if saldo is not None and previous.revision_balance is not None:
        if previous.revision_balance < 0 <= saldo:
            events.append(
                ChangeEvent(
                    ChangeKind.REVISIONS_POSITIVE,
                    f"Revisionssaldo {previous.revision_balance:.0f} -> {saldo:.0f}",
                    magnitude=15.0,
                    direction=1,
                )
            )
        elif saldo < 0 <= previous.revision_balance:
            events.append(
                ChangeEvent(
                    ChangeKind.REVISIONS_NEGATIVE,
                    f"Revisionssaldo {previous.revision_balance:.0f} -> {saldo:.0f}",
                    magnitude=15.0,
                    direction=-1,
                )
            )

    # --- Kursrueckgang bei stabilen Fundamentaldaten -------------------------
    # Der interessanteste Fall: der Kurs faellt, ohne dass sich die Zahlen
    # verschlechtert haben.
    if snapshot.price is not None and previous.price:
        kursaenderung = (snapshot.price / previous.price - 1.0) * 100.0
        fundamental_delta = _delta(
            scored.categories["fundamental"].score, previous.fundamental
        )
        if (
            kursaenderung <= PRICE_DROP_MIN
            and fundamental_delta is not None
            and abs(fundamental_delta) < FUNDAMENTAL_STABLE_BAND
        ):
            events.append(
                ChangeEvent(
                    ChangeKind.PRICE_DROP_STABLE,
                    f"Kurs {kursaenderung:+.1f} %, Fundamental-Teilscore nahezu unveraendert "
                    f"({fundamental_delta:+.1f})",
                    magnitude=abs(kursaenderung),
                    direction=1,
                )
            )

    # --- Datenlage verbessert ------------------------------------------------
    abdeckung = scored.categories["fundamental"].weight_coverage * 100.0
    abdeckung_delta = _delta(abdeckung, previous.coverage_fundamental)
    if abdeckung_delta is not None and abdeckung_delta >= COVERAGE_DELTA_MIN:
        events.append(
            ChangeEvent(
                ChangeKind.COVERAGE_UP,
                f"Fundamentale Abdeckung {previous.coverage_fundamental:.0f} % -> "
                f"{abdeckung:.0f} % - der Score ist jetzt belastbarer",
                magnitude=abdeckung_delta,
                direction=0,
            )
        )

    return TickerChanges(
        ticker=snapshot.ticker,
        events=events,
        previous=previous,
        score_delta=score_delta,
    )


def rank_by_relevance(changes: list[TickerChanges]) -> list[TickerChanges]:
    """Sortiert nach Auffaelligkeit; Titel ohne Ereignisse fallen heraus."""
    mit_ereignissen = [c for c in changes if c.has_events]
    return sorted(mit_ereignissen, key=lambda c: (-c.relevance, c.ticker))
