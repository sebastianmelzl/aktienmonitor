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

from ..formatting import NOT_AVAILABLE, format_metric, german_number
from ..models import MetricSet
from ..scoring.definitions import CATEGORY_LABELS, DEFAULT_WEIGHTS
from ..scoring.engine import CategoryScore, TotalScore
from ..scoring.sector import SectorStatistics

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
    for threshold, text in SCORE_BANDS:
        if score >= threshold:
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
    for kategorie, label in CATEGORY_LABELS.items():
        werte[kategorie] = target.slider(
            label,
            min_value=0.0,
            max_value=1.0,
            value=float(current.get(kategorie, 0.0)),
            step=0.05,
            key=f"{key_prefix}weight_{kategorie}",
        )

    total = sum(werte.values())
    if total <= 0:
        target.warning(
            "Alle Gewichte stehen auf null - damit laesst sich kein Gesamtscore bilden."
        )
    else:
        target.caption(
            f"Summe {german_number(total, 2)} – die Gewichte werden intern auf 100 % "
            "normiert, die Verhaeltnisse zaehlen."
        )

    if werte != current:
        store.set(WEIGHTS_SETTING_KEY, werte)
    return werte


def render_total_score(result: TotalScore) -> None:
    """Kopfzeile mit Gesamtscore und den vier Teilscores."""
    columns = st.columns(5)
    columns[0].metric(
        "Gesamtscore",
        f"{result.total:.0f}" if result.is_available else NOT_AVAILABLE,
        help="Gewichteter Mittelwert der verfuegbaren Teilscores, Skala 0-100.",
    )
    if result.is_available:
        columns[0].caption(score_band(result.total))

    for column, (name, category_score) in zip(columns[1:], result.categories.items(), strict=False):
        anteil = result.effective_weights.get(name, 0.0)
        column.metric(
            category_score.label,
            f"{category_score.score:.0f}" if category_score.is_available else NOT_AVAILABLE,
            help=category_score.coverage_text,
        )
        column.caption(
            f"Gewicht {anteil * 100:.0f} %" if anteil > 0 else "geht nicht in den Gesamtscore ein"
        )

    if result.redistributed:
        st.caption(
            "Ohne Daten und daher nicht im Gesamtscore: "
            + ", ".join(result.redistributed)
            + ". Das jeweilige Gewicht wurde auf die uebrigen Teilscores verteilt, "
            "statt den Bereich als null zu werten."
        )


def render_breakdown(category_score: CategoryScore, currency: str | None = None) -> None:
    """Aufklappbare Herleitung eines Teilscores."""
    with st.expander(category_score.coverage_text, expanded=False):
        if category_score.is_available:
            st.progress(category_score.weight_coverage)

        if category_score.included:
            rows = []
            for contribution in category_score.included:
                rows.append(
                    {
                        "Kennzahl": contribution.metric.label,
                        "Wert": format_metric(contribution.metric, currency),
                        "Bewertung": contribution.mode_label,
                        "Punkte": round(contribution.points, 1),
                        "Gewicht": contribution.rule.weight,
                        "Beitrag": round(contribution.weighted_points, 1),
                        "Quelle": contribution.metric.source_label,
                        "Vergleichsgruppe": (
                            f"{contribution.comparison.peer_count} Titel, Median "
                            f"{german_number(contribution.comparison.median, 2)}"
                            if contribution.comparison
                            else ""
                        ),
                    }
                )
            table = pd.DataFrame(rows)
            st.dataframe(table, width="stretch", hide_index=True)
            st.caption(
                f"Teilscore = Summe der Beitraege ({table['Beitrag'].sum():.1f}) geteilt "
                f"durch die Summe der genutzten Gewichte ({table['Gewicht'].sum():.1f})"
                + (f" = {category_score.score:.1f}" if category_score.is_available else "")
            )
        else:
            st.info("Keine dieser Kennzahlen ist verfuegbar - der Teilscore bleibt n/a.")

        if category_score.excluded:
            st.markdown("**Nicht eingegangen**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Kennzahl": b.metric.label,
                            "Grund": b.excluded_reason or "",
                            "Hinweis der Datenquelle": b.metric.missing_reason or "",
                        }
                        for b in category_score.excluded
                    ]
                ),
                width="stretch",
                hide_index=True,
            )

        st.markdown("**Begruendung der Regeln**")
        for contribution in category_score.contributions:
            st.caption(
                f"**{contribution.metric.label}** ({contribution.mode_label}): "
                f"{contribution.rule.rationale}"
            )


def render_sector_note(statistics: SectorStatistics | None, sector: str | None) -> None:
    """Hinweis, worauf sich der Sektorvergleich stuetzt."""
    if statistics is None:
        st.caption(
            "Kein Sektorvergleich moeglich: es liegen keine zwischengespeicherten Daten "
            "anderer Titel vor. Bewertungskennzahlen wie das KGV bleiben deshalb ohne Punkte."
        )
        return

    count = max(
        (statistics.peer_count(sector, key) for key in ("pe_trailing", "ev_ebitda", "roe")),
        default=0,
    )
    branche = sector or "ohne Angabe"
    st.caption(
        f"Sektorvergleich gegen **{count}** Titel der Branche '{branche}' aus dem eigenen "
        f"Universum (Mindestgruppe {statistics.min_peers} Titel). Der Vergleich ist damit "
        "relativ zur eigenen Watchlist, nicht zum Gesamtmarkt."
    )


def empty_metrics() -> MetricSet:
    return MetricSet({})
