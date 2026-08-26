"""Detailansicht eines einzelnen Titels."""

from __future__ import annotations

import streamlit as st

from aktienmonitor.formatting import NOT_AVAILABLE, format_change, german_number
from aktienmonitor.scoring.engine import score_snapshot
from aktienmonitor.ui.charts import INDICATOR_OPTIONS, price_chart
from aktienmonitor.ui.common import (
    clear_sector_cache,
    coverage_caption,
    get_config,
    get_sector_statistics,
    get_service,
    get_settings,
    get_watchlist,
    metrics_table,
    page_header,
    render_freshness,
)
from aktienmonitor.ui.scores import (
    render_breakdown,
    render_sector_note,
    render_total_score,
    weight_sliders,
)

page_header("Detailansicht", "Kennzahlen, Chart und Analystenbild eines Titels")

watchlist = get_watchlist()
service = get_service()
entries = watchlist.all()

if not entries:
    st.info("Das Universum ist leer. Bitte zuerst unter **Watchlist** Titel aufnehmen.")
    st.stop()

col_selection, col_period, col_button = st.columns([2, 1, 1])
with col_selection:
    ticker = st.selectbox(
        "Titel",
        options=[e.ticker for e in entries],
        format_func=lambda t: next(
            (f"{e.ticker} – {e.display_name}" if e.display_name else e.ticker
             for e in entries if e.ticker == t), t
        ),
    )
with col_period:
    period = st.selectbox(
        "Zeitraum", options=["1y", "2y", "5y", "10y", "max"], index=2,
        help="Laengere Zeitraeume werden fuer SMA 200 und Momentum 12 Monate benoetigt.",
    )
with col_button:
    st.write("")
    refresh_clicked = st.button("Jetzt aktualisieren", width="stretch",
                              help="Verwirft den Cache dieses Titels und ruft alle Daten neu ab.")

with st.spinner(f"Daten fuer {ticker} werden geladen ..."):
    snapshot = service.get_snapshot(
        ticker, force_refresh=refresh_clicked, history_period=period
    )

if not snapshot.has_any_data:
    st.error(
        f"Fuer **{ticker}** konnten keine Daten abgerufen werden. Moeglicherweise ist das "
        "Symbol unbekannt oder die Datenquelle gerade nicht erreichbar."
    )
    render_freshness(snapshot)
    st.stop()

# --- Kopfzeile ---------------------------------------------------------------
profile = snapshot.profile
title_text = profile.name or ticker
subtitle = " · ".join(t for t in (profile.sector, profile.industry, profile.exchange) if t)
st.header(title_text)
if subtitle:
    st.caption(subtitle)
if profile.is_fund:
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
    weights = weight_sliders(get_settings(), key_prefix="detail_")
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

statistics = get_sector_statistics(watchlist.tickers())
scored = score_snapshot(snapshot, statistics=statistics, weights=weights)
render_total_score(scored)
render_sector_note(statistics, snapshot.profile.sector)

for category_score in scored.categories.values():
    render_breakdown(category_score, snapshot.currency)

# --- Chart -------------------------------------------------------------------
st.subheader("Kursverlauf")
indicators = st.multiselect(
    "Indikatoren einblenden", options=list(INDICATOR_OPTIONS),
    default=["SMA 50", "SMA 200"],
)
chart_style = st.radio(
    "Darstellung", options=["Kerzen", "Linie"], horizontal=True, label_visibility="collapsed"
)
figure = price_chart(
    snapshot.bars, indicators=tuple(indicators), candlestick=(chart_style == "Kerzen")
)
if figure is None:
    st.info("Fuer diesen Titel liegt keine Kurshistorie vor.")
else:
    st.plotly_chart(figure, width="stretch")

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

    metric_consensus = snapshot.analyst.get("consensus_rating")
    metric_count = snapshot.analyst.get("analyst_count")
    metric_target = snapshot.analyst.get("target_mean")
    metric_upside = snapshot.analyst.get("target_upside")

    columns = st.columns(4)
    columns[0].metric(
        "Konsens-Einordnung",
        metric_consensus.text if metric_consensus and metric_consensus.is_available else NOT_AVAILABLE,
    )
    columns[1].metric(
        "Anzahl Analysten",
        german_number(metric_count.value, 0)
        if metric_count and metric_count.is_available else NOT_AVAILABLE,
    )
    columns[2].metric(
        "Kursziel (Schnitt)",
        german_number(metric_target.value, 2)
        if metric_target and metric_target.is_available else NOT_AVAILABLE,
    )
    columns[3].metric(
        "Abstand zum Kursziel",
        format_change(metric_upside.value if metric_upside else None),
    )

    st.dataframe(
        metrics_table(snapshot.analyst, snapshot.currency), width="stretch", hide_index=True
    )

# --- Schlagzeilen und Sentiment ----------------------------------------------
st.subheader("Schlagzeilen")

app_config = get_config()
unclassified = [m for m in snapshot.news if not m.sentiment]
if not app_config.has_anthropic and unclassified:
    # Nur melden, wenn tatsaechlich etwas unbewertet bleibt - bereits
    # eingeordnete Meldungen stehen weiterhin aus dem Cache zur Verfuegung.
    st.info(
        f"{len(unclassified)} von {len(snapshot.news)} Meldungen sind nicht eingeordnet: "
        "dafuer wird ein Anthropic-Schluessel benoetigt. Er laesst sich jederzeit in der "
        "`.env` unter `ANTHROPIC_API_KEY` nachtragen; bereits eingeordnete Meldungen "
        "bleiben erhalten.",
        icon="ℹ️",
    )

st.caption(coverage_caption(snapshot.sentiment, "Sentiment-Kennzahlen"))
st.dataframe(
    metrics_table(snapshot.sentiment, snapshot.currency), width="stretch", hide_index=True
)

if not snapshot.news:
    st.info(
        "Zu diesem Titel wurden keine Meldungen gefunden. Fuer nicht-amerikanische Titel "
        "ist die Nachrichtenlage der kostenlosen Quellen oft duenn."
    )
else:
    st.caption(
        "Die Einordnung stammt von einem Sprachmodell und ist eine Einschaetzung, keine "
        "Messung. Jede Meldung ist mit Quelle und Link versehen - die Einordnung laesst "
        "sich am Original nachlesen."
    )
    SYMBOLE = {"positiv": "🟢", "negativ": "🔴", "neutral": "⚪"}
    for item in snapshot.news[:25]:
        marker = SYMBOLE.get(item.sentiment or "", "▫️")
        verdict_label = item.sentiment or "nicht eingeordnet"
        st.markdown(
            f"{marker} **[{item.headline}]({item.url})**  \n"
            f"*{item.source_name} · {item.published_at:%d.%m.%Y %H:%M} · {verdict_label}*"
        )
        if item.sentiment_rationale:
            st.caption(f"Begruendung der Einordnung: {item.sentiment_rationale}")
        elif item.summary:
            st.caption(item.summary[:300])
        st.divider()
