"""Investieren: Betrag eingeben, 5 Titel nach Fundamentalanalyse vorgeschlagen bekommen.

Anders als die Aufteilung (eigene Watchlist) und die Vorschlaege (mehrstufiger
Assistent) ist das hier ein einzelner Knopf: Marktsuche, vollstaendige
Bewertung und Verteilung auf genau fuenf Titel in einem Schritt, ausgewaehlt
nach dem fundamentalen Teilscore.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from aktienmonitor.formatting import german_number
from aktienmonitor.narrative.briefing import build_briefing
from aktienmonitor.scoring.allocation import AllocationConstraints, AllocationMethod, allocate
from aktienmonitor.scoring.engine import score_snapshot
from aktienmonitor.scoring.sector import SectorStatistics
from aktienmonitor.screening.profiles import (
    PROFILES,
    PROFILES_BY_KEY,
    REGIONS,
    ScreenRequest,
    diagnose_result_count,
    parse_hits,
)
from aktienmonitor.ui.benchmark import render_portfolio_comparison
from aktienmonitor.ui.common import (
    coverage_caption,
    get_config,
    get_score_weights,
    get_service,
    metrics_table,
    page_header,
)
from aktienmonitor.ui.costs import render_allocation_costs

ANZAHL_TITEL = 5
# So viele Treffer der Marktsuche werden vollstaendig bewertet - begrenzt, weil
# je Titel mehrere Endpunkte abgerufen werden.
ANALYSE_LIMIT = 15

RESULT_KEY = "_investieren_ergebnis"

page_header(
    "Investieren",
    f"Betrag eingeben - die App sucht am Markt und schlaegt {ANZAHL_TITEL} Titel "
    "nach Fundamentalanalyse vor",
)
st.warning(
    "**Keine Anlageempfehlung.** Ausgewaehlt wird nach dem fundamentalen Teilscore - "
    "Schwellen, die als Konvention gesetzt und nicht auf Prognosekraft geprueft wurden. "
    "Wer eine grosse Menge an Titeln durchsucht, findet oben in der Liste mit hoher "
    "Wahrscheinlichkeit auch Zufall statt Signal. Die Entscheidung triffst du.",
    icon="⚠️",
)

service = get_service()
config = get_config()

col_amount, col_profile = st.columns([1, 2])
with col_amount:
    amount = st.number_input(
        "Zu investierender Betrag", min_value=0.0, value=5_000.0, step=500.0
    )
with col_profile:
    profile_keys = [p.key for p in PROFILES]
    profile_key = st.radio(
        "Suchprofil (harte Mindestanforderungen der Marktsuche)",
        options=profile_keys, format_func=lambda key: PROFILES_BY_KEY[key].name,
        horizontal=True, index=profile_keys.index("qualitaet"),
    )
profile = PROFILES_BY_KEY[profile_key]
st.caption(profile.description)

regions = st.multiselect(
    "Region", options=list(REGIONS), default=["de"],
    format_func=lambda code: f"{REGIONS[code]} ({code.upper()})",
)

if not regions:
    st.info("Bitte mindestens eine Region waehlen.")
    st.stop()

request = ScreenRequest(
    profile=profile, regions=tuple(regions), min_market_cap=1e9, limit=100
)

if st.button(f"{ANZAHL_TITEL} Titel vorschlagen", type="primary"):
    with st.spinner("Der Markt wird durchsucht ..."):
        screen_result = service.screener.run(request, force_refresh=True)
    if not screen_result.ok:
        st.error(f"Die Marktsuche ist fehlgeschlagen: {screen_result.error}")
        st.stop()

    hits = parse_hits(screen_result.data)
    hinweis = diagnose_result_count(len(hits), request.limit)
    auswahl = hits[:ANALYSE_LIMIT]

    if not auswahl:
        st.session_state[RESULT_KEY] = None
        st.warning(hinweis or "Keine Treffer fuer dieses Profil und diese Region.")
        st.stop()

    progress = st.progress(0.0, text="Kennzahlen werden geholt ...")

    def report(index: int, total: int, ticker: str) -> None:
        progress.progress(
            min(1.0, index / total if total else 1.0),
            text=f"{ticker} wird geholt ({index + 1} von {total}) ..." if ticker
            else f"{index} von {total} geholt",
        )

    with st.spinner("Vollstaendige Bewertung laeuft ..."):
        snapshots = service.get_snapshots(
            [h.ticker for h in auswahl], with_news=False, progress=report
        )
    progress.empty()

    # Vergleichsgruppe der sektorrelativen Regeln ist die Trefferliste selbst,
    # nicht die Watchlist - beide stammen aus derselben Suche.
    statistics = SectorStatistics.from_universe(
        [(s.profile.sector, s.fundamental) for s in snapshots.values()]
    )
    weights = get_score_weights()
    scored_by_ticker = {
        ticker: score_snapshot(snap, statistics=statistics, weights=weights)
        for ticker, snap in snapshots.items()
    }

    # Nach dem fundamentalen Teilscore sortieren - das ist die Grundlage der
    # Auswahl, nicht der Gesamtscore.
    bewertbar = [
        (snap, scored_by_ticker[ticker])
        for ticker, snap in snapshots.items()
        if scored_by_ticker[ticker].categories["fundamental"].is_available
    ]
    bewertbar.sort(key=lambda paar: paar[1].categories["fundamental"].score, reverse=True)
    top = bewertbar[:ANZAHL_TITEL]

    allocation_result = allocate(
        top, amount, method=AllocationMethod.EQUAL,
        constraints=AllocationConstraints(max_positions=ANZAHL_TITEL),
    )

    st.session_state[RESULT_KEY] = {
        "hinweis": hinweis,
        "n_hits": len(hits),
        "n_analysed": len(auswahl),
        "n_bewertbar": len(bewertbar),
        "top": top,
        "allocation": allocation_result,
        "benchmark_bars": service.get_benchmark_bars(cache_only=True),
    }

daten = st.session_state.get(RESULT_KEY)
if not daten:
    st.info("Noch kein Vorschlag berechnet.")
    st.stop()

if daten["hinweis"]:
    st.warning(daten["hinweis"], icon="⚠️")
st.caption(
    f"{daten['n_hits']} Treffer der Marktsuche, {daten['n_analysed']} davon vollstaendig "
    f"bewertet, {daten['n_bewertbar']} mit berechenbarem Fundamental-Score."
)

result = daten["allocation"]
for warning in result.warnings:
    st.warning(warning, icon="⚠️")

if daten["n_bewertbar"] < ANZAHL_TITEL:
    st.info(
        f"Nur {daten['n_bewertbar']} von {ANZAHL_TITEL} gewuenschten Titeln haben ueberhaupt "
        "einen berechenbaren Fundamental-Score - mehr gibt die Marktsuche mit diesem Profil "
        "und dieser Region gerade nicht her."
    )

if not result.has_items:
    st.stop()

# --- Ergebnis ------------------------------------------------------------------
st.subheader("Vorschlag")
kpi = st.columns(4)
kpi[0].metric("Positionen", len(result.items))
kpi[1].metric("Verteilt", german_number(result.invested, 2))
kpi[2].metric("Rest", german_number(result.cash_left, 2))
kpi[3].metric("Branchen", len(result.sector_shares))

scored_by_ticker = {snap.ticker: scored for snap, scored in daten["top"]}
snapshot_by_ticker = {snap.ticker: snap for snap, _ in daten["top"]}

tabelle = pd.DataFrame(
    [
        {
            "Ticker": item.ticker,
            "Name": item.name,
            "Branche": item.sector,
            "Fundamental-Score": round(
                scored_by_ticker[item.ticker].categories["fundamental"].score, 0
            ),
            "Gesamtscore": (
                round(scored_by_ticker[item.ticker].total, 0)
                if scored_by_ticker[item.ticker].is_available else None
            ),
            "Anteil %": round(item.weight * 100.0, 1),
            "Zielbetrag": round(item.target_amount, 2),
            "Kurs": round(item.price, 2) if item.price else None,
            "Stueck": item.shares,
            "Betrag": round(item.invested_amount, 2),
        }
        for item in result.items
    ]
)
st.dataframe(
    tabelle, width="stretch", hide_index=True,
    column_config={
        "Fundamental-Score": st.column_config.ProgressColumn(
            format="%.0f", min_value=0, max_value=100
        ),
        "Gesamtscore": st.column_config.NumberColumn(format="%.0f"),
        "Anteil %": st.column_config.ProgressColumn(
            format="%.1f", min_value=0, max_value=float(max(tabelle["Anteil %"].max(), 1))
        ),
        "Zielbetrag": st.column_config.NumberColumn(format="localized"),
        "Kurs": st.column_config.NumberColumn(format="localized"),
        "Betrag": st.column_config.NumberColumn(format="localized"),
    },
)
st.download_button(
    "Vorschlag als CSV",
    data=tabelle.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
    file_name="investieren.csv",
    mime="text/csv",
)

if result.excluded:
    with st.expander(f"Nicht beruecksichtigt ({len(result.excluded)})"):
        st.dataframe(
            pd.DataFrame(result.excluded, columns=["Ticker", "Grund"]),
            width="stretch", hide_index=True,
        )

# --- Fundamentalanalyse je Titel ------------------------------------------------
st.subheader("Fundamentalanalyse je Titel")
for item in result.items:
    snap = snapshot_by_ticker[item.ticker]
    scored = scored_by_ticker[item.ticker]
    with st.expander(f"{item.ticker} – {item.name}"):
        st.caption(coverage_caption(snap.fundamental, "Fundamentaldaten"))
        st.progress(snap.fundamental.coverage)
        st.dataframe(
            metrics_table(snap.fundamental, snap.currency), width="stretch", hide_index=True
        )
        with st.expander("Vollstaendiges Faktenblatt (alle Teilscores)"):
            st.text(build_briefing(snap, scored))

# --- Kosten und Benchmark --------------------------------------------------------
st.subheader("Kaufkosten (Trade Republic)")
render_allocation_costs(result.items)

st.subheader("Vergleich mit einer Benchmark")
st.caption(
    f"Was haette derselbe Betrag im selben Zeitraum in **{config.benchmark_ticker}** "
    "erzielt? Auf Basis der historischen Kursrenditen der vorgeschlagenen Positionen, "
    "gewichtet nach Zielanteil."
)
weighted_bars = [(item.weight, snapshot_by_ticker[item.ticker].bars) for item in result.items]
render_portfolio_comparison(config.benchmark_ticker, daten["benchmark_bars"], weighted_bars)

with st.expander("Wie dieser Vorschlag entsteht"):
    st.markdown(
        """
        **1. Marktsuche.** Eine Abfrage an Yahoo Finance mit den harten Kriterien des
        gewaehlten Profils, begrenzt auf Region und Mindestgroesse.

        **2. Vollstaendige Bewertung.** Fuer die ersten Treffer wird derselbe
        Kennzahlensatz geholt und bewertet wie fuer die eigene Watchlist.

        **3. Auswahl nach Fundamental-Score.** Die fuenf Titel mit dem hoechsten
        fundamentalen Teilscore werden ausgewaehlt - nicht nach Gesamtscore, weil
        gerade die Fundamentaldaten hier im Vordergrund stehen sollen.

        **4. Verteilung.** Der Betrag wird gleichgewichtet auf die Auswahl verteilt,
        mit denselben Obergrenzen wie auf der Seite **Aufteilung** (Positions- und
        Branchendeckel, Mindestgroesse je Position, ganze Stueckzahlen).

        **Vergleichsgruppe.** Die sektorrelativen Kennzahlen vergleichen gegen die
        anderen analysierten Treffer dieser Suche, nicht gegen die Watchlist oder
        den Gesamtmarkt.
        """
    )
