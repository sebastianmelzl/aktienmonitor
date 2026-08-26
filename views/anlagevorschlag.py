"""Aufteilungsrechner: wie sich ein Betrag nach vorgegebenen Regeln verteilt."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from aktienmonitor.formatting import german_number
from aktienmonitor.scoring.allocation import (
    AllocationConstraints,
    AllocationMethod,
    allocate,
)
from aktienmonitor.scoring.engine import score_snapshot
from aktienmonitor.ui.common import (
    get_score_weights,
    get_sector_statistics,
    get_service,
    get_watchlist,
    page_header,
)

page_header("Aufteilung", "Wie sich ein Betrag nach festgelegten Regeln verteilt")

st.warning(
    "**Das ist ein Rechner, keine Anlageempfehlung.** Er verteilt einen Betrag nach den "
    "unten eingestellten Regeln - mehr nicht. Die zugrundeliegenden Scores beruhen auf "
    "Schwellen, die als Konvention gesetzt und **nicht auf Prognosekraft geprueft** wurden. "
    "Die Aufteilung beruecksichtigt weder Korrelationen zwischen den Titeln noch deine "
    "uebrige Vermoegenslage, deinen Anlagehorizont, Steuern oder Gebuehren. "
    "Die Entscheidung triffst du.",
    icon="⚠️",
)

watchlist = get_watchlist()
service = get_service()
entries = watchlist.all()

if not entries:
    st.info("Das Universum ist noch leer. Bitte zuerst unter **Watchlist** Titel aufnehmen.")
    st.stop()

# --- Eingaben ----------------------------------------------------------------
col_amount, col_method, col_group = st.columns([1, 1, 1])
with col_amount:
    amount = st.number_input(
        "Zu verteilender Betrag", min_value=0.0, value=10_000.0, step=500.0,
        help="In der Waehrung, in der die Titel notieren. Es wird nicht umgerechnet.",
    )
with col_method:
    method_label = st.radio(
        "Verteilung",
        options=[str(AllocationMethod.EQUAL), str(AllocationMethod.SCORE_WEIGHTED)],
        help="Gleichgewichtet verteilt auf alle gleich viel. Nach Score gewichtet gibt "
             "hoeher bewerteten Titeln mehr - was die Aussagekraft des Modells "
             "staerker voraussetzt.",
    )
    method = (
        AllocationMethod.EQUAL
        if method_label == str(AllocationMethod.EQUAL)
        else AllocationMethod.SCORE_WEIGHTED
    )
with col_group:
    groups = watchlist.groups()
    group = st.selectbox("Liste", options=["Alle Titel", *groups])

with st.sidebar:
    st.subheader("Regeln")
    max_position = st.slider("Hoechstanteil je Titel", 5, 100, 25, step=5) / 100.0
    max_sector = st.slider("Hoechstanteil je Branche", 10, 100, 40, step=5) / 100.0
    max_positions = st.slider("Hoechstzahl der Positionen", 2, 30, 10)
    min_position = st.number_input("Mindestbetrag je Position", min_value=0.0,
                                   value=250.0, step=50.0)
    min_coverage = st.slider(
        "Mindest-Datenabdeckung fundamental (%)", 0, 100, 35, step=5,
        help="Ohne Sektor-Vergleichsgruppe sind hoechstens rund 53 % erreichbar - "
             "eine hoehere Schwelle schliesst dann alles aus.",
    )
    use_min_score = st.checkbox("Mindestscore verlangen")
    min_score = st.slider("Mindestscore", 0, 100, 60, step=5) if use_min_score else None

constraints = AllocationConstraints(
    max_position_share=max_position,
    max_sector_share=max_sector,
    min_position_amount=min_position,
    min_coverage=float(min_coverage),
    min_score=float(min_score) if min_score is not None else None,
    max_positions=int(max_positions),
)

# --- Rechnen -----------------------------------------------------------------
tickers = watchlist.tickers(None if group == "Alle Titel" else group)
if not tickers:
    st.info(f"Der Liste '{group}' ist noch kein Titel zugeordnet.")
    st.stop()

snapshots = service.get_snapshots(tickers, cache_only=True)
statistics = get_sector_statistics(watchlist.tickers())
weights = get_score_weights()
candidates = [
    (snap, score_snapshot(snap, statistics=statistics, weights=weights))
    for snap in snapshots.values()
]

result = allocate(candidates, amount, method=method, constraints=constraints)

# --- Hinweise ----------------------------------------------------------------
for warning in result.warnings:
    st.warning(warning, icon="⚠️")

if not result.has_items:
    st.stop()

# --- Ergebnis ----------------------------------------------------------------
kpi = st.columns(4)
kpi[0].metric("Positionen", len(result.items))
kpi[1].metric("Verteilt", german_number(result.invested, 2))
kpi[2].metric("Rest", german_number(result.cash_left, 2))
kpi[3].metric("Branchen", len(result.sector_shares))

table = pd.DataFrame(
    [
        {
            "Ticker": item.ticker,
            "Name": item.name,
            "Branche": item.sector,
            "Score": round(item.score, 1),
            "Anteil %": round(item.weight * 100.0, 1),
            "Zielbetrag": round(item.target_amount, 2),
            "Kurs": round(item.price, 2) if item.price else None,
            "Stueck": item.shares,
            "Betrag": round(item.invested_amount, 2),
            "Rest": round(item.leftover, 2),
            "Waehrung": item.currency or "",
        }
        for item in result.items
    ]
)
st.dataframe(
    table, width="stretch", hide_index=True,
    column_config={
        "Score": st.column_config.NumberColumn(format="%.0f"),
        "Anteil %": st.column_config.ProgressColumn(
            format="%.1f", min_value=0, max_value=float(max(table["Anteil %"].max(), 1))
        ),
        "Zielbetrag": st.column_config.NumberColumn(format="localized"),
        "Kurs": st.column_config.NumberColumn(format="localized"),
        "Betrag": st.column_config.NumberColumn(format="localized"),
        "Rest": st.column_config.NumberColumn(format="localized"),
    },
)
st.caption(
    "**Stueck** sind ganze Anteile zum zuletzt bekannten Kurs - Bruchstuecke gibt es nicht. "
    "**Rest** ist der Teil des Zielbetrags, der dadurch nicht angelegt wird."
)

# --- Streuung ----------------------------------------------------------------
col_chart, col_rules = st.columns([2, 1])
with col_chart:
    st.subheader("Verteilung nach Branche")
    shares = result.sector_shares
    figure = go.Figure(
        go.Bar(
            x=list(shares.values()), y=list(shares.keys()), orientation="h",
            marker_color="#1f77b4",
        )
    )
    figure.add_vline(
        x=constraints.max_sector_share * 100.0, line_dash="dash",
        line_color="#d62728",
        annotation_text=f"Deckel {constraints.max_sector_share * 100:.0f} %",
    )
    figure.update_layout(
        height=max(200, 60 * len(shares)), margin={"l": 10, "r": 10, "t": 10, "b": 10},
        xaxis={"title": "Anteil in %"},
    )
    st.plotly_chart(figure, width="stretch")

with col_rules:
    st.subheader("Geltende Regeln")
    for rule in constraints.describe():
        st.markdown(f"- {rule}")
    st.caption(f"Verteilung: {method}")

# --- Ausgeschlossene ---------------------------------------------------------
if result.excluded:
    with st.expander(f"Nicht beruecksichtigt ({len(result.excluded)})"):
        st.dataframe(
            pd.DataFrame(result.excluded, columns=["Ticker", "Grund"]),
            width="stretch", hide_index=True,
        )
        st.caption(
            "Kein Titel verschwindet stillschweigend - hier steht zu jedem, warum er "
            "nicht in die Aufteilung eingegangen ist."
        )

st.download_button(
    "Aufteilung als CSV",
    data=table.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
    file_name="aufteilung.csv",
    mime="text/csv",
)
