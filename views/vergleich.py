"""Vergleich: zwei bis fuenf Titel in einer Kennzahlen-Matrix."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from aktienmonitor.formatting import NOT_AVAILABLE, format_metric, german_number
from aktienmonitor.scoring.engine import score_snapshot
from aktienmonitor.ui.common import (
    get_score_weights,
    get_sector_statistics,
    get_service,
    get_watchlist,
    page_header,
)
from aktienmonitor.ui.table import build_comparison_matrix

MAX_TITEL = 5
MIN_TITEL = 2

page_header("Vergleich", "Zwei bis fuenf Titel nebeneinander")

watchlist = get_watchlist()
service = get_service()
entries = watchlist.all()

if len(entries) < MIN_TITEL:
    st.info(
        f"Fuer einen Vergleich werden mindestens {MIN_TITEL} Titel benoetigt. "
        "Bitte unter **Watchlist** weitere aufnehmen."
    )
    st.stop()

selection = st.multiselect(
    "Titel auswaehlen",
    options=[e.ticker for e in entries],
    max_selections=MAX_TITEL,
    format_func=lambda t: next(
        (f"{e.ticker} – {e.display_name}" if e.display_name else e.ticker
         for e in entries if e.ticker == t),
        t,
    ),
    help=f"Zwischen {MIN_TITEL} und {MAX_TITEL} Titeln.",
)

if len(selection) < MIN_TITEL:
    st.info(f"Bitte mindestens {MIN_TITEL} Titel auswaehlen.")
    st.stop()

# Vergleich arbeitet auf dem vorhandenen Datenstand - aktualisiert wird auf der
# Uebersichtsseite oder in der Detailansicht.
snapshots = service.get_snapshots(selection, cache_only=True)
missing_data = [t for t, s in snapshots.items() if not s.has_any_data]
if missing_data:
    st.warning(
        f"Fuer {', '.join(missing_data)} liegen keine zwischengespeicherten Daten vor. "
        "Bitte in der **Uebersicht** einmal aktualisieren."
    )

statistics = get_sector_statistics(watchlist.tickers())
weights = get_score_weights()
scored_by_ticker = {t: score_snapshot(s, statistics=statistics, weights=weights)
               for t, s in snapshots.items()}

# --- Kopfzeile: Kurs und Scores ----------------------------------------------
st.subheader("Auf einen Blick")
columns = st.columns(len(selection))
for column, kuerzel in zip(columns, selection, strict=False):
    snapshot = snapshots[kuerzel]
    scored = scored_by_ticker[kuerzel]
    with column:
        st.markdown(f"### {kuerzel}")
        st.caption(snapshot.profile.name or "")
        st.caption(snapshot.profile.sector or "Sektor unbekannt")
        st.metric(
            "Gesamtscore",
            f"{scored.total:.0f}" if scored.is_available else NOT_AVAILABLE,
        )
        st.metric(
            "Kurs",
            german_number(snapshot.price, 2) if snapshot.price is not None else NOT_AVAILABLE,
        )

st.subheader("Teilscores")
score_table = pd.DataFrame(
    [
        {
            "Teilscore": scored_by_ticker[selection[0]].categories[name].label,
            **{
                kuerzel: (
                    round(scored_by_ticker[kuerzel].categories[name].score, 1)
                    if scored_by_ticker[kuerzel].categories[name].is_available
                    else None
                )
                for kuerzel in selection
            },
            "Abdeckung": " / ".join(
                f"{scored_by_ticker[k].categories[name].used_count}"
                f"-{scored_by_ticker[k].categories[name].total_count}"
                for k in selection
            ),
        }
        for name in ("fundamental", "technical", "analyst", "sentiment")
    ]
)
st.dataframe(
    score_table,
    width="stretch",
    hide_index=True,
    column_config={
        kuerzel: st.column_config.NumberColumn(format="%.0f") for kuerzel in selection
    },
)
st.caption(
    "Spalte **Abdeckung**: genutzte zu moeglichen Kennzahlen je Titel, in der Reihenfolge "
    "der Spalten. Ein hoher Score aus wenigen Kennzahlen ist weniger belastbar als derselbe "
    "Score aus vielen."
)

# --- Kennzahlen-Matrix -------------------------------------------------------
st.subheader("Kennzahlen")
st.caption(
    "Leere Felder bedeuten, dass die Kennzahl fuer diesen Titel nicht abrufbar war. "
    "Die Spalte **Quelle** nennt die Herkunft des jeweils ersten verfuegbaren Werts."
)

tabs = st.tabs(["Fundamental", "Technik", "Analysten"])
for tab, bereich in zip(tabs, ("fundamental", "technical", "analyst"), strict=False):
    with tab:
        ticker, rows = build_comparison_matrix(snapshots, bereich)
        if not rows:
            st.info("Keine Kennzahlen vorhanden.")
            continue

        currencies = {k: snapshots[k].currency for k in ticker}
        table = []
        for row in rows:
            entry = {"Kennzahl": row["label"]}
            quelle = ""
            for kuerzel in ticker:
                metric = row.get(kuerzel)
                entry[kuerzel] = (
                    format_metric(metric, currencies[kuerzel])
                    if metric is not None
                    else NOT_AVAILABLE
                )
                if not quelle and metric is not None and metric.is_available:
                    quelle = metric.source_label
            entry["Quelle"] = quelle or "-"
            table.append(entry)

        st.dataframe(pd.DataFrame(table), width="stretch", hide_index=True)
