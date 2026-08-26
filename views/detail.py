"""Detailansicht eines einzelnen Titels."""

from __future__ import annotations

import streamlit as st

from aktienmonitor.scoring.engine import score_snapshot
from aktienmonitor.ui.charts import INDICATOR_OPTIONS, price_chart
from aktienmonitor.ui.common import (
    clear_sector_cache,
    coverage_caption,
    get_sector_statistics,
    get_service,
    get_settings,
    get_watchlist,
    metrics_table,
    page_header,
    render_freshness,
)
from aktienmonitor.ui.format import NOT_AVAILABLE, format_change, german_number
from aktienmonitor.ui.scores import (
    render_breakdown,
    render_sector_note,
    render_total_score,
    weight_sliders,
)

page_header("Detailansicht", "Kennzahlen, Chart und Analystenbild eines Titels")

watchlist = get_watchlist()
service = get_service()
eintraege = watchlist.all()

if not eintraege:
    st.info("Das Universum ist leer. Bitte zuerst unter **Watchlist** Titel aufnehmen.")
    st.stop()

spalte_auswahl, spalte_zeitraum, spalte_knopf = st.columns([2, 1, 1])
with spalte_auswahl:
    ticker = st.selectbox(
        "Titel",
        options=[e.ticker for e in eintraege],
        format_func=lambda t: next(
            (f"{e.ticker} – {e.display_name}" if e.display_name else e.ticker
             for e in eintraege if e.ticker == t), t
        ),
    )
with spalte_zeitraum:
    zeitraum = st.selectbox(
        "Zeitraum", options=["1y", "2y", "5y", "10y", "max"], index=2,
        help="Laengere Zeitraeume werden fuer SMA 200 und Momentum 12 Monate benoetigt.",
    )
with spalte_knopf:
    st.write("")
    aktualisieren = st.button("Jetzt aktualisieren", width="stretch",
                              help="Verwirft den Cache dieses Titels und ruft alle Daten neu ab.")

with st.spinner(f"Daten fuer {ticker} werden geladen ..."):
    snapshot = service.get_snapshot(
        ticker, force_refresh=aktualisieren, history_period=zeitraum
    )

if not snapshot.has_any_data:
    st.error(
        f"Fuer **{ticker}** konnten keine Daten abgerufen werden. Moeglicherweise ist das "
        "Symbol unbekannt oder die Datenquelle gerade nicht erreichbar."
    )
    render_freshness(snapshot)
    st.stop()

# --- Kopfzeile ---------------------------------------------------------------
profil = snapshot.profile
titel = profil.name or ticker
untertitel = " · ".join(t for t in (profil.sector, profil.industry, profil.exchange) if t)
st.header(titel)
if untertitel:
    st.caption(untertitel)
if profil.is_fund:
    st.warning(
        "Dieser Titel ist ein Fonds bzw. ETF. Unternehmenskennzahlen wie ROE, Margen "
        "oder ROIC existieren dafuer nicht und werden als 'n/a' gefuehrt.",
        icon="⚠️",
    )

kpi_kurs, kpi_veraenderung, kpi_waehrung, kpi_stand = st.columns(4)
kpi_kurs.metric(
    "Kurs",
    german_number(snapshot.price, 2) if snapshot.price is not None else NOT_AVAILABLE,
)
kpi_veraenderung.metric("Veraenderung zum Vortag", format_change(snapshot.change_percent))
kpi_waehrung.metric("Waehrung", snapshot.currency or NOT_AVAILABLE)
kpi_stand.metric(
    "Aeltester Datenstand",
    next((f.age_text for f in snapshot.freshness if f.fetched_at == snapshot.oldest_fetch),
         NOT_AVAILABLE),
)

render_freshness(snapshot)

# --- Bewertung ---------------------------------------------------------------
with st.sidebar:
    st.subheader("Gewichtung")
    st.caption(
        "Bestimmt, wie stark die vier Teilscores in den Gesamtscore eingehen. "
        "Die Einstellung gilt in der gesamten App."
    )
    gewichte = weight_sliders(get_settings(), key_prefix="detail_")
    if st.button("Sektordaten neu aufbauen", width="stretch"):
        clear_sector_cache()
        st.rerun()

st.subheader("Bewertung")
st.caption(
    "Der Score fasst Kennzahlen zu einer Vergleichsgroesse zusammen. Er ist eine "
    "Aufbereitung, keine Einschaetzung des Titels - die Schwellen des Regelwerks sind "
    "eine Konvention. Jeder Teilscore laesst sich unten bis zur einzelnen Kennzahl "
    "aufklappen."
)

statistik = get_sector_statistics(watchlist.tickers())
bewertung = score_snapshot(snapshot, statistics=statistik, weights=gewichte)
render_total_score(bewertung)
render_sector_note(statistik, snapshot.profile.sector)

for teilscore in bewertung.categories.values():
    render_breakdown(teilscore, snapshot.currency)

# --- Chart -------------------------------------------------------------------
st.subheader("Kursverlauf")
indikatoren = st.multiselect(
    "Indikatoren einblenden", options=list(INDICATOR_OPTIONS),
    default=["SMA 50", "SMA 200"],
)
darstellung = st.radio(
    "Darstellung", options=["Kerzen", "Linie"], horizontal=True, label_visibility="collapsed"
)
figur = price_chart(
    snapshot.bars, indicators=tuple(indikatoren), candlestick=(darstellung == "Kerzen")
)
if figur is None:
    st.info("Fuer diesen Titel liegt keine Kurshistorie vor.")
else:
    st.plotly_chart(figur, width="stretch")

# --- Kennzahlen --------------------------------------------------------------
st.subheader("Kennzahlen")
st.caption(
    "Die Spalte **Quelle** weist aus, woher jeder Wert stammt. Als *berechnet* "
    "markierte Kennzahlen wurden aus anderen Groessen abgeleitet. Fehlende Werte "
    "erscheinen als **n/a** mit Begruendung – es werden keine Ersatzwerte eingesetzt."
)

tab_fundamental, tab_technik, tab_analysten = st.tabs(
    ["Fundamental", "Technik", "Analysten"]
)

with tab_fundamental:
    st.caption(coverage_caption(snapshot.fundamental, "Fundamentaldaten"))
    st.progress(snapshot.fundamental.coverage)
    st.dataframe(
        metrics_table(snapshot.fundamental, snapshot.currency),
        width="stretch", hide_index=True,
    )

with tab_technik:
    st.caption(coverage_caption(snapshot.technical, "Technische Kennzahlen"))
    st.progress(snapshot.technical.coverage)
    st.dataframe(
        metrics_table(snapshot.technical, snapshot.currency), width="stretch", hide_index=True
    )

with tab_analysten:
    st.caption(coverage_caption(snapshot.analyst, "Analystendaten"))
    st.progress(snapshot.analyst.coverage)

    kennzahl_konsens = snapshot.analyst.get("consensus_rating")
    kennzahl_anzahl = snapshot.analyst.get("analyst_count")
    kennzahl_ziel = snapshot.analyst.get("target_mean")
    kennzahl_abstand = snapshot.analyst.get("target_upside")

    spalten = st.columns(4)
    spalten[0].metric(
        "Konsens-Einordnung",
        kennzahl_konsens.text if kennzahl_konsens and kennzahl_konsens.is_available else NOT_AVAILABLE,
    )
    spalten[1].metric(
        "Anzahl Analysten",
        german_number(kennzahl_anzahl.value, 0)
        if kennzahl_anzahl and kennzahl_anzahl.is_available else NOT_AVAILABLE,
    )
    spalten[2].metric(
        "Kursziel (Schnitt)",
        german_number(kennzahl_ziel.value, 2)
        if kennzahl_ziel and kennzahl_ziel.is_available else NOT_AVAILABLE,
    )
    spalten[3].metric(
        "Abstand zum Kursziel",
        format_change(kennzahl_abstand.value if kennzahl_abstand else None),
    )

    st.dataframe(
        metrics_table(snapshot.analyst, snapshot.currency), width="stretch", hide_index=True
    )

# --- News --------------------------------------------------------------------
st.subheader("Schlagzeilen")
st.caption(
    "Sentiment-Einordnung folgt in Phase 4. Bis dahin werden die Meldungen "
    "unbewertet mit Quelle und Link angezeigt."
)
if st.button("Schlagzeilen laden"):
    with st.spinner("Meldungen werden geladen ..."):
        meldungen = service.get_news(ticker, force_refresh=aktualisieren)
    if not meldungen:
        st.info("Zu diesem Titel wurden keine Meldungen gefunden.")
    for meldung in meldungen[:20]:
        st.markdown(
            f"**[{meldung.headline}]({meldung.url})**  \n"
            f"*{meldung.source_name} · {meldung.published_at:%d.%m.%Y %H:%M}*"
        )
        if meldung.summary:
            st.caption(meldung.summary[:400])
        st.divider()
