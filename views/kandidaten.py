"""Kandidaten: was sich seit dem letzten Lauf bewegt hat."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from aktienmonitor.formatting import NOT_AVAILABLE
from aktienmonitor.narrative.briefing import build_briefing
from aktienmonitor.scoring.changes import DEFAULT_THRESHOLD, detect_changes, rank_by_relevance
from aktienmonitor.scoring.engine import score_snapshot
from aktienmonitor.ui.common import (
    get_score_weights,
    get_sector_statistics,
    get_service,
    get_watchlist,
    page_header,
)

page_header(
    "Kandidaten",
    "Titel, an denen sich seit dem letzten Stand etwas bewegt hat",
)

watchlist = get_watchlist()
service = get_service()
entries = watchlist.all()

if not entries:
    st.info("Das Universum ist noch leer. Bitte zuerst unter **Watchlist** Titel aufnehmen.")
    st.stop()

st.caption(
    "Diese Seite vergleicht den aktuellen Stand mit dem letzten gespeicherten. Der Verlauf "
    "waechst mit jedem Aktualisieren in der **Uebersicht** - beim allerersten Lauf gibt es "
    "deshalb noch wenig zu sehen."
)

tickers = watchlist.tickers()
snapshots = service.get_snapshots(tickers, cache_only=True)
statistics = get_sector_statistics(tickers)
weights = get_score_weights()

threshold = st.sidebar.slider(
    "Schwelle fuer Uebertritte", min_value=40, max_value=90, value=int(DEFAULT_THRESHOLD),
    step=5,
    help="Ein Ueber- oder Unterschreiten dieses Gesamtscores gilt als Ereignis.",
)

scored_by_ticker = {}
all_changes = []
for ticker, snap in snapshots.items():
    scored = score_snapshot(snap, statistics=statistics, weights=weights)
    scored_by_ticker[ticker] = scored
    all_changes.append(
        detect_changes(snap, scored, service.history.previous(ticker), threshold=float(threshold))
    )

ranked = rank_by_relevance(all_changes)

# --- Kopfzeile ---------------------------------------------------------------
kpi = st.columns(4)
kpi[0].metric("Titel im Universum", len(snapshots))
kpi[1].metric("Mit Veraenderung", len(ranked))
kpi[2].metric("Verlaufseintraege", service.history.count())
positive = sum(1 for c in ranked if any(e.is_positive for e in c.events))
kpi[3].metric("Davon mit Aufwaertsereignis", positive)

if service.history.count() == 0:
    st.warning(
        "Es gibt noch keinen Verlauf. Bitte einmal in der **Uebersicht** auf "
        "*Alle Werte aktualisieren* druecken - danach entsteht bei jedem weiteren "
        "Lauf ein Vergleichsstand.",
        icon="ℹ️",
    )

if not ranked:
    st.info("Derzeit keine nennenswerten Veraenderungen im Universum.")
    st.stop()

# --- Begruendungen -----------------------------------------------------------
narrator = service.narrator
generate = False
if narrator.available:
    generate = st.checkbox(
        "Begruendungen erzeugen",
        help="Erzeugt zu jedem Kandidaten einen kurzen Text aus den berechneten Zahlen. "
             "Kostet einmalig wenige Cent je Titel; unveraenderte Staende kommen aus dem Cache.",
    )
else:
    st.caption(f"Keine Begruendungen moeglich: {narrator.unavailable_reason}")

# --- Kandidaten --------------------------------------------------------------
SYMBOLS = {1: "▲", -1: "▼", 0: "•"}

for changes in ranked:
    ticker = changes.ticker
    snap = snapshots[ticker]
    scored = scored_by_ticker[ticker]

    title = f"{ticker}"
    if snap.profile.name:
        title += f" – {snap.profile.name}"
    score_text = f"{scored.total:.0f}" if scored.is_available else NOT_AVAILABLE
    delta_text = (
        f" ({changes.score_delta:+.0f})" if changes.score_delta is not None else ""
    )

    with st.expander(f"{title}  ·  Score {score_text}{delta_text}", expanded=False):
        st.caption(f"Vergleich {changes.reference_text}")

        for event in changes.events:
            st.markdown(f"{SYMBOLS.get(event.direction, '•')} **{event.label}** – {event.detail}")

        st.divider()
        columns = st.columns(4)
        for column, category in zip(columns, scored.categories.values(), strict=False):
            column.metric(
                category.label,
                f"{category.score:.0f}" if category.is_available else NOT_AVAILABLE,
            )

        # Verlauf
        series = service.history.series(ticker, limit=100)
        points = [(e.recorded_at, e.total) for e in series if e.total is not None]
        if len(points) >= 2:
            figure = go.Figure()
            figure.add_trace(
                go.Scatter(
                    x=[p[0] for p in points], y=[p[1] for p in points],
                    mode="lines+markers", name="Gesamtscore",
                    line={"color": "#1f77b4", "width": 2},
                )
            )
            figure.update_layout(
                height=220, margin={"l": 10, "r": 10, "t": 10, "b": 10},
                yaxis={"range": [0, 100], "title": "Gesamtscore"},
            )
            st.plotly_chart(figure, width="stretch")

        # Begruendung
        briefing = build_briefing(snap, scored, changes)
        narrative = narrator.generate(ticker, briefing, cache_only=not generate)
        if narrative is not None:
            st.markdown("**Einordnung**")
            st.write(narrative.einordnung)
            if narrative.dafuer:
                st.markdown("**Hohe Punktzahlen aus**")
                for point in narrative.dafuer:
                    st.markdown(f"- {point}")
            if narrative.dagegen:
                st.markdown("**Niedrige Punktzahlen aus**")
                for point in narrative.dagegen:
                    st.markdown(f"- {point}")
            if narrative.datenluecken:
                st.markdown("**Datenluecken**")
                for point in narrative.datenluecken:
                    st.markdown(f"- {point}")
            st.caption(
                "Der Text fasst ausschliesslich die berechneten Zahlen zusammen. Er ist "
                "keine Einschaetzung des Titels und keine Prognose."
            )
        elif generate:
            st.caption("Fuer diesen Titel konnte kein Text erzeugt werden.")

        with st.popover("Faktenblatt ansehen"):
            st.code(briefing, language=None)

st.divider()
with st.expander("Wie diese Liste entsteht"):
    st.markdown(
        f"""
        Bei jedem Aktualisieren in der Uebersicht wird je Titel ein Stand gespeichert
        (Scores, Datenabdeckung, Kurs). Diese Seite vergleicht den aktuellen Stand mit
        dem letzten, der mindestens sechs Stunden zurueckliegt, und meldet:

        - Gesamtscore um mindestens 8 Punkte veraendert
        - Teilscore um mindestens 12 Punkte veraendert
        - Gesamtscore hat {threshold} ueber- oder unterschritten
        - Golden Cross oder Death Cross in den letzten 30 Tagen
        - Revisionssaldo hat das Vorzeichen gewechselt
        - Kurs um mindestens 12 % gefallen, waehrend der Fundamental-Teilscore
          nahezu unveraendert blieb
        - Datenabdeckung um mindestens 15 Prozentpunkte gestiegen

        Die Schwellen sind Konvention: sie bestimmen, ab wann eine Bewegung
        erwaehnenswert ist, und sagen nichts ueber kuenftige Kursentwicklung.
        """
    )
