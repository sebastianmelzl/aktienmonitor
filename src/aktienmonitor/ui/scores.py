"""Darstellung der Scores samt Herleitung.

Die Anzeige folgt der Vorgabe, dass jede Zahl bis zur Rohquelle
zurueckverfolgbar sein muss: zu jedem Teilscore lassen sich alle Beitraege
aufklappen - mit Kennzahlenwert, Bewertungsart, Punkten, Gewicht und der
Begruendung der Regel. Ausgeschlossene Kennzahlen werden mit Grund genannt,
nicht verschwiegen.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..models import MetricSet
from ..scoring.definitions import CATEGORY_LABELS, DEFAULT_WEIGHTS
from ..scoring.engine import CategoryScore, TotalScore
from ..scoring.sector import SectorStatistics
from .format import NOT_AVAILABLE, format_metric, german_number

WEIGHTS_SETTING_KEY = "score_weights"
MIN_PEERS_SETTING_KEY = "sector_min_peers"

# Neutrale Formulierungen - das Werkzeug bereitet auf, es empfiehlt nicht.
SCORE_BANDS = (
    (80.0, "sehr hoher Score"),
    (65.0, "hoher Score"),
    (45.0, "mittlerer Score"),
    (30.0, "niedriger Score"),
    (0.0, "sehr niedriger Score"),
)


def score_band(score: float | None) -> str:
    if score is None:
        return "kein Score"
    for schwelle, text in SCORE_BANDS:
        if score >= schwelle:
            return text
    return "sehr niedriger Score"


def weight_sliders(store, *, container=None, key_prefix: str = "") -> dict[str, float]:
    """Schieberegler fuer die Gewichtung der vier Teilscores.

    Die Werte werden dauerhaft gespeichert und gelten in der gesamten App.
    """
    target = container or st
    stored = store.get(WEIGHTS_SETTING_KEY, None)
    current = dict(DEFAULT_WEIGHTS)
    if isinstance(stored, dict):
        current.update({k: float(v) for k, v in stored.items() if k in DEFAULT_WEIGHTS})

    werte: dict[str, float] = {}
    for kategorie, beschriftung in CATEGORY_LABELS.items():
        werte[kategorie] = target.slider(
            beschriftung,
            min_value=0.0,
            max_value=1.0,
            value=float(current.get(kategorie, 0.0)),
            step=0.05,
            key=f"{key_prefix}weight_{kategorie}",
        )

    summe = sum(werte.values())
    if summe <= 0:
        target.warning(
            "Alle Gewichte stehen auf null - damit laesst sich kein Gesamtscore bilden."
        )
    else:
        target.caption(
            f"Summe {german_number(summe, 2)} – die Gewichte werden intern auf 100 % "
            "normiert, die Verhaeltnisse zaehlen."
        )

    if werte != current:
        store.set(WEIGHTS_SETTING_KEY, werte)
    return werte


def render_total_score(result: TotalScore) -> None:
    """Kopfzeile mit Gesamtscore und den vier Teilscores."""
    spalten = st.columns(5)
    spalten[0].metric(
        "Gesamtscore",
        f"{result.total:.0f}" if result.is_available else NOT_AVAILABLE,
        help="Gewichteter Mittelwert der verfuegbaren Teilscores, Skala 0-100.",
    )
    if result.is_available:
        spalten[0].caption(score_band(result.total))

    for spalte, (name, teilscore) in zip(spalten[1:], result.categories.items(), strict=False):
        anteil = result.effective_weights.get(name, 0.0)
        spalte.metric(
            teilscore.label,
            f"{teilscore.score:.0f}" if teilscore.is_available else NOT_AVAILABLE,
            help=teilscore.coverage_text,
        )
        spalte.caption(
            f"Gewicht {anteil * 100:.0f} %" if anteil > 0 else "geht nicht in den Gesamtscore ein"
        )

    if result.redistributed:
        st.caption(
            "Ohne Daten und daher nicht im Gesamtscore: "
            + ", ".join(result.redistributed)
            + ". Das jeweilige Gewicht wurde auf die uebrigen Teilscores verteilt, "
            "statt den Bereich als null zu werten."
        )


def render_breakdown(teilscore: CategoryScore, currency: str | None = None) -> None:
    """Aufklappbare Herleitung eines Teilscores."""
    with st.expander(teilscore.coverage_text, expanded=False):
        if teilscore.is_available:
            st.progress(teilscore.weight_coverage)

        if teilscore.included:
            zeilen = []
            for beitrag in teilscore.included:
                zeilen.append(
                    {
                        "Kennzahl": beitrag.metric.label,
                        "Wert": format_metric(beitrag.metric, currency),
                        "Bewertung": beitrag.mode_label,
                        "Punkte": round(beitrag.points, 1),
                        "Gewicht": beitrag.rule.weight,
                        "Beitrag": round(beitrag.weighted_points, 1),
                        "Quelle": beitrag.metric.source_label,
                        "Vergleichsgruppe": (
                            f"{beitrag.comparison.peer_count} Titel, Median "
                            f"{german_number(beitrag.comparison.median, 2)}"
                            if beitrag.comparison
                            else ""
                        ),
                    }
                )
            tabelle = pd.DataFrame(zeilen)
            st.dataframe(tabelle, width="stretch", hide_index=True)
            st.caption(
                f"Teilscore = Summe der Beitraege ({tabelle['Beitrag'].sum():.1f}) geteilt "
                f"durch die Summe der genutzten Gewichte ({tabelle['Gewicht'].sum():.1f})"
                + (f" = {teilscore.score:.1f}" if teilscore.is_available else "")
            )
        else:
            st.info("Keine dieser Kennzahlen ist verfuegbar - der Teilscore bleibt n/a.")

        if teilscore.excluded:
            st.markdown("**Nicht eingegangen**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Kennzahl": b.metric.label,
                            "Grund": b.excluded_reason or "",
                            "Hinweis der Datenquelle": b.metric.missing_reason or "",
                        }
                        for b in teilscore.excluded
                    ]
                ),
                width="stretch",
                hide_index=True,
            )

        st.markdown("**Begruendung der Regeln**")
        for beitrag in teilscore.contributions:
            st.caption(f"**{beitrag.metric.label}** ({beitrag.mode_label}): {beitrag.rule.rationale}")


def render_sector_note(statistics: SectorStatistics | None, sector: str | None) -> None:
    """Hinweis, worauf sich der Sektorvergleich stuetzt."""
    if statistics is None:
        st.caption(
            "Kein Sektorvergleich moeglich: es liegen keine zwischengespeicherten Daten "
            "anderer Titel vor. Bewertungskennzahlen wie das KGV bleiben deshalb ohne Punkte."
        )
        return

    anzahl = max(
        (statistics.peer_count(sector, key) for key in ("pe_trailing", "ev_ebitda", "roe")),
        default=0,
    )
    branche = sector or "ohne Angabe"
    st.caption(
        f"Sektorvergleich gegen **{anzahl}** Titel der Branche '{branche}' aus dem eigenen "
        f"Universum (Mindestgruppe {statistics.min_peers} Titel). Der Vergleich ist damit "
        "relativ zur eigenen Watchlist, nicht zum Gesamtmarkt."
    )


def empty_metrics() -> MetricSet:
    return MetricSet({})
