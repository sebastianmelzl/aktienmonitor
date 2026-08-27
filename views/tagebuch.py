"""Entscheidungstagebuch: eigene Kauf-/Verkaufsentscheidungen mit Begruendung."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from aktienmonitor.benchmark.compare import return_between
from aktienmonitor.formatting import NOT_AVAILABLE, format_change, german_number
from aktienmonitor.scoring.engine import score_snapshot
from aktienmonitor.storage.journal import ACTIONS, JournalEntry
from aktienmonitor.ui.common import (
    get_config,
    get_journal,
    get_score_weights,
    get_service,
    get_watchlist,
    page_header,
)

page_header(
    "Entscheidungstagebuch",
    "Eigene Kauf-/Verkaufsentscheidungen mit Begruendung, im Rueckblick gegen die Benchmark",
)
st.caption(
    "Die Begruendung ist die eigene Einschaetzung zum Zeitpunkt der Entscheidung - nicht "
    "rueckblickend erzeugt und nicht von einem Sprachmodell verfasst. Der Sinn ist der "
    "Rueckblick: hat die Entscheidung besser abgeschnitten als ein einfacher Kauf der "
    "Benchmark - nicht, ob sie im Nachhinein klug klingt."
)

journal = get_journal()
service = get_service()
watchlist = get_watchlist()
config = get_config()

with st.expander("Neue Entscheidung eintragen", expanded=journal.count() == 0):
    ticker_options = [e.ticker for e in watchlist.all()]
    col_ticker, col_action, col_date = st.columns(3)
    with col_ticker:
        if ticker_options:
            ticker_input = st.selectbox("Titel", options=ticker_options)
        else:
            ticker_input = st.text_input("Ticker").strip().upper()
    with col_action:
        action = st.radio("Aktion", options=list(ACTIONS), horizontal=True)
    with col_date:
        decided_at = st.date_input(
            "Datum der Entscheidung", value=date.today(), max_value=date.today()
        )

    col_price, col_amount, col_shares = st.columns(3)
    with col_price:
        price = st.number_input("Kurs zum Zeitpunkt", min_value=0.0, value=0.0, step=0.1)
    with col_amount:
        amount = st.number_input("Betrag", min_value=0.0, value=0.0, step=50.0)
    with col_shares:
        shares = st.number_input("Stueckzahl", min_value=0.0, value=0.0, step=1.0)

    rationale = st.text_area(
        "Eigene Begruendung",
        placeholder="Warum jetzt? Was muesste eintreten, damit die Entscheidung im "
                    "Rueckblick falsch war?",
    )

    score_now = None
    if ticker_input:
        snap = service.get_snapshot(ticker_input, cache_only=True, with_news=False)
        if snap.has_any_data:
            score_now = score_snapshot(snap, weights=get_score_weights()).total
    if score_now is not None:
        st.caption(f"Aktueller Gesamtscore aus dem Cache: {score_now:.0f} - wird mit eingetragen.")

    if st.button("Eintragen", type="primary"):
        if not ticker_input:
            st.error("Bitte einen Titel angeben.")
        else:
            journal.add(
                JournalEntry(
                    ticker=ticker_input,
                    action=action,
                    decided_at=decided_at,
                    price=price or None,
                    amount=amount or None,
                    shares=shares or None,
                    score_at_decision=score_now,
                    rationale=rationale.strip() or None,
                )
            )
            st.success("Eingetragen.")
            st.rerun()

st.subheader("Bisherige Entscheidungen")
eintraege = journal.all()
if not eintraege:
    st.info("Noch keine Eintraege.")
    st.stop()

benchmark_bars = service.get_benchmark_bars(cache_only=True)
snapshots_cache: dict[str, object] = {}

zeilen = []
vorspruenge: list[float] = []
for eintrag in eintraege:
    if eintrag.ticker not in snapshots_cache:
        snapshots_cache[eintrag.ticker] = service.get_snapshot(
            eintrag.ticker, cache_only=True, with_news=False
        )
    aktueller_kurs = snapshots_cache[eintrag.ticker].price

    eigene_rendite = None
    if eintrag.price and eintrag.price > 0 and aktueller_kurs is not None:
        eigene_rendite = (aktueller_kurs / eintrag.price - 1.0) * 100.0

    benchmark_rendite = (
        return_between(benchmark_bars, eintrag.decided_at) if benchmark_bars else None
    )
    vorsprung = (
        None if eigene_rendite is None or benchmark_rendite is None
        else eigene_rendite - benchmark_rendite
    )
    if vorsprung is not None:
        vorspruenge.append(vorsprung)

    zeilen.append(
        {
            "Datum": eintrag.decided_at.strftime("%d.%m.%Y"),
            "Ticker": eintrag.ticker,
            "Aktion": eintrag.action,
            "Kurs damals": german_number(eintrag.price, 2) if eintrag.price else NOT_AVAILABLE,
            "Kurs heute": german_number(aktueller_kurs, 2) if aktueller_kurs else NOT_AVAILABLE,
            "Kursentwicklung seither": format_change(eigene_rendite),
            f"{config.benchmark_ticker} seither": format_change(benchmark_rendite),
            "Vorsprung": format_change(vorsprung),
            "Score damals": (
                german_number(eintrag.score_at_decision, 0)
                if eintrag.score_at_decision is not None else NOT_AVAILABLE
            ),
            "Begruendung": eintrag.rationale or "",
        }
    )

st.dataframe(pd.DataFrame(zeilen), width="stretch", hide_index=True)
st.caption(
    "**Kursentwicklung seither** misst vom eingetragenen Kurs bis zum aktuellen Kurs - bei "
    "einem Verkauf zeigt sie, wie sich der Titel entwickelt haette, waere man geblieben. "
    "Verglichen werden reine Kursrenditen ohne Dividenden, siehe **Benchmark-Vergleich**."
)

if vorspruenge:
    kpi = st.columns(3)
    kpi[0].metric("Entscheidungen mit Vergleich", len(vorspruenge))
    kpi[1].metric("Mittlerer Vorsprung", format_change(sum(vorspruenge) / len(vorspruenge)))
    gewonnen = sum(1 for v in vorspruenge if v > 0)
    kpi[2].metric("Anteil mit Vorsprung", f"{gewonnen / len(vorspruenge) * 100:.0f} %")

with st.expander("Eintrag loeschen"):
    auswahl = st.selectbox(
        "Eintrag",
        options=eintraege,
        format_func=lambda e: f"{e.decided_at.strftime('%d.%m.%Y')} · {e.ticker} · {e.action}",
    )
    if st.button("Endgueltig loeschen"):
        journal.delete(auswahl.id)
        st.success("Eintrag geloescht.")
        st.rerun()
