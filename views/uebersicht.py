"""Uebersicht: alle Titel des Universums auf einen Blick."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from aktienmonitor.benchmark.compare import total_return
from aktienmonitor.formatting import NOT_AVAILABLE, format_change, german_number
from aktienmonitor.scoring.engine import score_snapshot
from aktienmonitor.storage.history import entry_from
from aktienmonitor.ui.common import (
    clear_sector_cache,
    get_config,
    get_score_weights,
    get_sector_statistics,
    get_service,
    get_settings,
    get_watchlist,
    page_header,
)
from aktienmonitor.ui.scores import weight_sliders
from aktienmonitor.ui.table import (
    COLUMNS,
    OverviewFilter,
    apply_filters,
    build_rows,
    rows_to_csv,
)

LAST_REFRESH_KEY = "last_universe_refresh"

page_header(
    "Uebersicht",
    "Alle beobachteten Titel mit Score, Kurs und Datenstand",
)

watchlist = get_watchlist()
service = get_service()
store = get_settings()
config = get_config()

entries = watchlist.all()
if not entries:
    st.info(
        "Das Universum ist noch leer. Unter **Watchlist** koennen Titel per Ticker "
        "hinzugefuegt oder als CSV importiert werden."
    )
    with st.expander("Erste Schritte - so ist die App gedacht", expanded=True):
        st.markdown(
            "1. **Watchlist**: ein paar Titel eintragen, die du kennst oder pruefen willst.\n"
            "2. **Uebersicht** (hier): auf *Alle Werte aktualisieren* klicken, dann Scores "
            "und Datenstand aller Titel auf einen Blick sehen.\n"
            "3. **Detailansicht**: bei einem einzelnen Titel nachvollziehen, welche Kennzahl "
            "wie viele Punkte beigetragen hat.\n"
            "4. **Kandidaten** / **Vorschlaege**: wenn du noch nicht weisst, welche Titel "
            "ueberhaupt in Frage kommen.\n"
            "5. **Aufteilung**: wenn du einen Betrag anlegen willst - zeigt auch gleich die "
            "Kaufkosten bei Trade Republic.\n"
            "6. **Tagebuch**: jede Entscheidung mit eigener Begruendung eintragen, um spaeter "
            "ehrlich nachvollziehen zu koennen, ob sie sich gelohnt hat.\n\n"
            "Die uebrigen Seiten (**Vergleich**, **Backtest**, **Datenquellen**, "
            "**Einstellungen**) sind fuer spaeter - nichts davon ist fuer den Einstieg noetig."
        )
    st.stop()

# --- Auswahl und Aktualisierung ---------------------------------------------
groups = watchlist.groups()
col_group, col_mode, col_button = st.columns([2, 2, 1])

with col_group:
    group = st.selectbox("Liste", options=["Alle Titel", *groups])
with col_mode:
    discard_cache = st.checkbox(
        "Cache verwerfen",
        help="Ohne Haken werden nur Daten geholt, deren Cache-Lebensdauer abgelaufen ist. "
             "Mit Haken wird alles neu abgerufen - das dauert deutlich laenger und belastet "
             "die Rate-Limits der Anbieter.",
    )
    with_news_selected = st.checkbox(
        "Schlagzeilen und Sentiment mitladen",
        value=config.has_anthropic,
        help="Holt zu jedem Titel die Meldungen und ordnet neue Schlagzeilen per "
             "Sprachmodell ein. Bereits eingeordnete Schlagzeilen kommen aus dem Cache "
             "und kosten nichts. Ohne Anthropic-Schluessel werden die Meldungen nur "
             "geholt, nicht bewertet.",
    )
with col_button:
    st.write("")
    refresh_clicked = st.button("Alle Werte aktualisieren", type="primary", width="stretch")

ticker = watchlist.tickers(None if group == "Alle Titel" else group)
if not ticker:
    st.info(f"Der Liste '{group}' ist noch kein Titel zugeordnet.")
    st.stop()

if refresh_clicked:
    progress_bar = st.progress(0.0, text="Abruf wird vorbereitet ...")

    def report_progress(index: int, gesamt: int, kuerzel: str) -> None:
        anteil = index / gesamt if gesamt else 1.0
        text = (
            f"{index} von {gesamt} Titeln abgerufen"
            if not kuerzel
            else f"{kuerzel} wird abgerufen ({index + 1} von {gesamt}) ..."
        )
        progress_bar.progress(min(1.0, anteil), text=text)

    with st.spinner("Daten werden geholt - bei kaltem Cache dauert das einige Minuten."):
        service.get_snapshots(
            ticker, force_refresh=discard_cache, with_news=with_news_selected, progress=report_progress
        )
    progress_bar.empty()
    store.set(LAST_REFRESH_KEY, datetime.now(UTC).isoformat())
    clear_sector_cache()
    st.success(f"{len(ticker)} Titel aktualisiert.")

# --- Daten laden (ohne Netzzugriff) -----------------------------------------
# Die Ansicht selbst ruft nie ab: sonst wuerde jedes Umstellen eines Filters
# einen Abruf ausloesen. Neue Daten kommen ausschliesslich ueber den Knopf.
snapshots = service.get_snapshots(ticker, cache_only=True)
statistics = get_sector_statistics(watchlist.tickers())
weights = get_score_weights()
scored_by_ticker = {
    ticker_key: score_snapshot(snap, statistics=statistics, weights=weights)
    for ticker_key, snap in snapshots.items()
}
# Den Verlauf nur beim ausdruecklichen Aktualisieren fortschreiben - sonst
# entstuende bei jedem Seitenaufbau ein neuer Eintrag und die
# Veraenderungserkennung haette nie einen brauchbaren Vergleichsstand.
if refresh_clicked:
    service.history.record_many(
        [entry_from(snapshots[t], scored_by_ticker[t]) for t in snapshots]
    )

rows = build_rows(snapshots, scored_by_ticker)

without_data = [z["ticker"] for z in rows if z["note"] == "Keine Daten abrufbar"]

# --- Filter ------------------------------------------------------------------
with st.sidebar:
    st.subheader("Gewichtung")
    weight_sliders(store, key_prefix="uebersicht_")

    st.subheader("Filter")
    min_score = st.slider("Mindest-Gesamtscore", 0, 100, 0, step=5)
    sectors = sorted({z["sector"] for z in rows if z["sector"]})
    selected_sectors = st.multiselect("Sektor", options=sectors, placeholder="alle Sektoren")

    st.caption("Marktkapitalisierung (Mrd.)")
    col_min, col_max = st.columns(2)
    cap_min = col_min.number_input("von", min_value=0.0, value=0.0, step=1.0)
    cap_max = col_max.number_input("bis", min_value=0.0, value=0.0, step=1.0,
                                      help="0 bedeutet: keine Obergrenze")

    min_dividend = st.slider("Mindest-Dividendenrendite (%)", 0.0, 10.0, 0.0, step=0.5)
    max_pe_input = st.slider("Hoechstes KGV", 0, 100, 0, step=5,
                        help="0 bedeutet: keine Obergrenze")
    show_funds = st.checkbox("ETFs und Fonds einbeziehen", value=True)

criteria = OverviewFilter(
    min_score=float(min_score) if min_score > 0 else None,
    sectors=selected_sectors,
    min_market_cap=cap_min * 1e9 if cap_min > 0 else None,
    max_market_cap=cap_max * 1e9 if cap_max > 0 else None,
    min_dividend_yield=min_dividend if min_dividend > 0 else None,
    max_pe=float(max_pe_input) if max_pe_input > 0 else None,
    include_funds=show_funds,
)
result = apply_filters(rows, criteria)

# --- Kopfzeile ---------------------------------------------------------------
last_refresh = store.get(LAST_REFRESH_KEY, None)
kpi = st.columns(5)
kpi[0].metric("Titel im Universum", len(rows))
kpi[1].metric("Nach Filter", len(result.rows))
scored_values = [z["score_total"] for z in result.rows if z["score_total"] is not None]
kpi[2].metric(
    "Mittlerer Score",
    german_number(sum(scored_values) / len(scored_values), 1) if scored_values else NOT_AVAILABLE,
)
if isinstance(last_refresh, str):
    try:
        stand = datetime.fromisoformat(last_refresh)
        stunden = (datetime.now(UTC) - stand).total_seconds() / 3600
        kpi[3].metric(
            "Letzte Aktualisierung",
            "gerade eben" if stunden < 1 else f"vor {int(stunden)} Std."
            if stunden < 48 else f"vor {int(stunden / 24)} Tg.",
        )
    except ValueError:
        kpi[3].metric("Letzte Aktualisierung", NOT_AVAILABLE)
else:
    kpi[3].metric("Letzte Aktualisierung", "noch nie")

benchmark_return = total_return(
    service.get_benchmark_bars(cache_only=True), trading_days=252
)
kpi[4].metric(
    f"Benchmark 1J ({config.benchmark_ticker})",
    format_change(benchmark_return),
    help="Kursrendite des Referenz-ETF ueber die letzten 252 Handelstage - zur Einordnung "
         "des mittleren Scores, kein Bestandteil der Berechnung.",
)

if without_data:
    st.warning(
        f"Fuer {len(without_data)} Titel liegen keine Daten vor: {', '.join(without_data[:12])}"
        + (" ..." if len(without_data) > 12 else "")
        + ". Bitte einmal aktualisieren; bleiben sie leer, ist das Symbol vermutlich unbekannt."
    )

if result.excluded_by_missing:
    st.info(
        f"{result.excluded_by_missing} Titel sind nicht durch den Filter gefallen, sondern "
        f"**nicht pruefbar** - die gefilterte Kennzahl fehlt dort: "
        f"{', '.join(result.missing_tickers[:12])}"
        + (" ..." if len(result.missing_tickers) > 12 else ""),
        icon="ℹ️",
    )

# --- Tabelle -----------------------------------------------------------------
if not result.rows:
    st.warning("Kein Titel erfuellt die gewaehlten Filterkriterien.")
    st.stop()

display_frame = pd.DataFrame(result.rows)[[key for key, _ in COLUMNS]]
display_frame.columns = [label for _, label in COLUMNS]

st.dataframe(
    display_frame,
    width="stretch",
    hide_index=True,
    column_config={
        "Kurs": st.column_config.NumberColumn(format="localized"),
        "Veraenderung": st.column_config.NumberColumn(
            format="localized", help="Veraenderung zum Vortagesschluss in Prozent"
        ),
        "Gesamtscore": st.column_config.ProgressColumn(
            format="%.0f", min_value=0, max_value=100,
            help="Gewichteter Mittelwert der verfuegbaren Teilscores",
        ),
        "Fundamental": st.column_config.NumberColumn(format="%.0f"),
        "Technik": st.column_config.NumberColumn(format="%.0f"),
        "Analysten": st.column_config.NumberColumn(format="%.0f"),
        "Sentiment": st.column_config.NumberColumn(
            format="%.0f",
            help="Leer, solange kein Anthropic-Schluessel hinterlegt ist oder zu "
                 "wenige Meldungen eingeordnet wurden",
        ),
        "Abdeckung fundamental": st.column_config.NumberColumn(
            format="%.0f", help="Anteil der genutzten Gewichtung in Prozent"
        ),
        "Marktkapitalisierung": st.column_config.NumberColumn(format="compact"),
        "Dividendenrendite": st.column_config.NumberColumn(format="localized"),
        "KGV": st.column_config.NumberColumn(format="localized"),
    },
)
st.caption(
    "Spalten sind durch Klick auf die Kopfzeile sortierbar. Leere Felder bedeuten, dass die "
    "Kennzahl nicht abrufbar war - es werden keine Ersatzwerte eingesetzt. Details je Titel "
    "in der **Detailansicht**."
)

# --- Export ------------------------------------------------------------------
col_de, col_en = st.columns(2)
timestamp = datetime.now().strftime("%Y%m%d_%H%M")
col_de.download_button(
    "Als CSV exportieren (deutsches Format)",
    data=rows_to_csv(result.rows, german=True).encode("utf-8-sig"),
    file_name=f"aktienmonitor_{timestamp}.csv",
    mime="text/csv",
    width="stretch",
    help="Semikolon als Trennzeichen, Komma als Dezimaltrennzeichen - oeffnet in Excel direkt.",
)
col_en.download_button(
    "Als CSV exportieren (internationales Format)",
    data=rows_to_csv(result.rows, german=False).encode("utf-8"),
    file_name=f"aktienmonitor_{timestamp}_intl.csv",
    mime="text/csv",
    width="stretch",
)
