"""Vergleich: zwei bis fuenf Titel in einer Kennzahlen-Matrix."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from aktienmonitor.scoring.engine import score_snapshot
from aktienmonitor.ui.common import (
    get_score_weights,
    get_sector_statistics,
    get_service,
    get_watchlist,
    page_header,
)
from aktienmonitor.ui.format import NOT_AVAILABLE, format_metric, german_number
from aktienmonitor.ui.table import build_comparison_matrix

MAX_TITEL = 5
MIN_TITEL = 2

page_header("Vergleich", "Zwei bis fuenf Titel nebeneinander")

watchlist = get_watchlist()
service = get_service()
eintraege = watchlist.all()

if len(eintraege) < MIN_TITEL:
    st.info(
        f"Fuer einen Vergleich werden mindestens {MIN_TITEL} Titel benoetigt. "
        "Bitte unter **Watchlist** weitere aufnehmen."
    )
    st.stop()

auswahl = st.multiselect(
    "Titel auswaehlen",
    options=[e.ticker for e in eintraege],
    max_selections=MAX_TITEL,
    format_func=lambda t: next(
        (f"{e.ticker} – {e.display_name}" if e.display_name else e.ticker
         for e in eintraege if e.ticker == t),
        t,
    ),
    help=f"Zwischen {MIN_TITEL} und {MAX_TITEL} Titeln.",
)

if len(auswahl) < MIN_TITEL:
    st.info(f"Bitte mindestens {MIN_TITEL} Titel auswaehlen.")
    st.stop()

# Vergleich arbeitet auf dem vorhandenen Datenstand - aktualisiert wird auf der
# Uebersichtsseite oder in der Detailansicht.
snapshots = service.get_snapshots(auswahl, cache_only=True)
fehlend = [t for t, s in snapshots.items() if not s.has_any_data]
if fehlend:
    st.warning(
        f"Fuer {', '.join(fehlend)} liegen keine zwischengespeicherten Daten vor. "
        "Bitte in der **Uebersicht** einmal aktualisieren."
    )

statistik = get_sector_statistics(watchlist.tickers())
gewichte = get_score_weights()
bewertungen = {t: score_snapshot(s, statistics=statistik, weights=gewichte)
               for t, s in snapshots.items()}

# --- Kopfzeile: Kurs und Scores ----------------------------------------------
st.subheader("Auf einen Blick")
spalten = st.columns(len(auswahl))
for spalte, kuerzel in zip(spalten, auswahl, strict=False):
    snapshot = snapshots[kuerzel]
    bewertung = bewertungen[kuerzel]
    with spalte:
        st.markdown(f"### {kuerzel}")
        st.caption(snapshot.profile.name or "")
        st.caption(snapshot.profile.sector or "Sektor unbekannt")
        st.metric(
            "Gesamtscore",
            f"{bewertung.total:.0f}" if bewertung.is_available else NOT_AVAILABLE,
        )
        st.metric(
            "Kurs",
            german_number(snapshot.price, 2) if snapshot.price is not None else NOT_AVAILABLE,
        )

st.subheader("Teilscores")
score_tabelle = pd.DataFrame(
    [
        {
            "Teilscore": bewertungen[auswahl[0]].categories[name].label,
            **{
                kuerzel: (
                    round(bewertungen[kuerzel].categories[name].score, 1)
                    if bewertungen[kuerzel].categories[name].is_available
                    else None
                )
                for kuerzel in auswahl
            },
            "Abdeckung": " / ".join(
                f"{bewertungen[k].categories[name].used_count}"
                f"-{bewertungen[k].categories[name].total_count}"
                for k in auswahl
            ),
        }
        for name in ("fundamental", "technical", "analyst", "sentiment")
    ]
)
st.dataframe(
    score_tabelle,
    width="stretch",
    hide_index=True,
    column_config={
        kuerzel: st.column_config.NumberColumn(format="%.0f") for kuerzel in auswahl
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
        ticker, zeilen = build_comparison_matrix(snapshots, bereich)
        if not zeilen:
            st.info("Keine Kennzahlen vorhanden.")
            continue

        waehrungen = {k: snapshots[k].currency for k in ticker}
        tabelle = []
        for zeile in zeilen:
            eintrag = {"Kennzahl": zeile["label"]}
            quelle = ""
            for kuerzel in ticker:
                metric = zeile.get(kuerzel)
                eintrag[kuerzel] = (
                    format_metric(metric, waehrungen[kuerzel])
                    if metric is not None
                    else NOT_AVAILABLE
                )
                if not quelle and metric is not None and metric.is_available:
                    quelle = metric.source_label
            eintrag["Quelle"] = quelle or "-"
            tabelle.append(eintrag)

        st.dataframe(pd.DataFrame(tabelle), width="stretch", hide_index=True)
