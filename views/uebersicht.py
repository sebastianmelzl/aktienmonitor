"""Uebersicht: alle Titel des Universums auf einen Blick."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from aktienmonitor.scoring.engine import score_snapshot
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
from aktienmonitor.ui.format import NOT_AVAILABLE, german_number
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

eintraege = watchlist.all()
if not eintraege:
    st.info(
        "Das Universum ist noch leer. Unter **Watchlist** koennen Titel per Ticker "
        "hinzugefuegt oder als CSV importiert werden."
    )
    st.stop()

# --- Auswahl und Aktualisierung ---------------------------------------------
gruppen = watchlist.groups()
spalte_gruppe, spalte_modus, spalte_knopf = st.columns([2, 2, 1])

with spalte_gruppe:
    gruppe = st.selectbox("Liste", options=["Alle Titel", *gruppen])
with spalte_modus:
    alles_neu = st.checkbox(
        "Cache verwerfen",
        help="Ohne Haken werden nur Daten geholt, deren Cache-Lebensdauer abgelaufen ist. "
             "Mit Haken wird alles neu abgerufen - das dauert deutlich laenger und belastet "
             "die Rate-Limits der Anbieter.",
    )
    mit_news = st.checkbox(
        "Schlagzeilen und Sentiment mitladen",
        value=config.has_anthropic,
        help="Holt zu jedem Titel die Meldungen und ordnet neue Schlagzeilen per "
             "Sprachmodell ein. Bereits eingeordnete Schlagzeilen kommen aus dem Cache "
             "und kosten nichts. Ohne Anthropic-Schluessel werden die Meldungen nur "
             "geholt, nicht bewertet.",
    )
with spalte_knopf:
    st.write("")
    aktualisieren = st.button("Alle Werte aktualisieren", type="primary", width="stretch")

ticker = watchlist.tickers(None if gruppe == "Alle Titel" else gruppe)
if not ticker:
    st.info(f"Der Liste '{gruppe}' ist noch kein Titel zugeordnet.")
    st.stop()

if aktualisieren:
    fortschritt = st.progress(0.0, text="Abruf wird vorbereitet ...")

    def melde(index: int, gesamt: int, kuerzel: str) -> None:
        anteil = index / gesamt if gesamt else 1.0
        text = (
            f"{index} von {gesamt} Titeln abgerufen"
            if not kuerzel
            else f"{kuerzel} wird abgerufen ({index + 1} von {gesamt}) ..."
        )
        fortschritt.progress(min(1.0, anteil), text=text)

    with st.spinner("Daten werden geholt - bei kaltem Cache dauert das einige Minuten."):
        service.get_snapshots(
            ticker, force_refresh=alles_neu, with_news=mit_news, progress=melde
        )
    fortschritt.empty()
    store.set(LAST_REFRESH_KEY, datetime.now(UTC).isoformat())
    clear_sector_cache()
    st.success(f"{len(ticker)} Titel aktualisiert.")

# --- Daten laden (ohne Netzzugriff) -----------------------------------------
# Die Ansicht selbst ruft nie ab: sonst wuerde jedes Umstellen eines Filters
# einen Abruf ausloesen. Neue Daten kommen ausschliesslich ueber den Knopf.
snapshots = service.get_snapshots(ticker, cache_only=True)
statistik = get_sector_statistics(watchlist.tickers())
gewichte = get_score_weights()
bewertungen = {t: score_snapshot(s, statistics=statistik, weights=gewichte) for t, s in snapshots.items()}
zeilen = build_rows(snapshots, bewertungen)

ohne_daten = [z["ticker"] for z in zeilen if z["note"] == "Keine Daten abrufbar"]

# --- Filter ------------------------------------------------------------------
with st.sidebar:
    st.subheader("Gewichtung")
    weight_sliders(store, key_prefix="uebersicht_")

    st.subheader("Filter")
    min_score = st.slider("Mindest-Gesamtscore", 0, 100, 0, step=5)
    sektoren = sorted({z["sector"] for z in zeilen if z["sector"]})
    gewaehlte_sektoren = st.multiselect("Sektor", options=sektoren, placeholder="alle Sektoren")

    st.caption("Marktkapitalisierung (Mrd.)")
    spalte_min, spalte_max = st.columns(2)
    kap_min = spalte_min.number_input("von", min_value=0.0, value=0.0, step=1.0)
    kap_max = spalte_max.number_input("bis", min_value=0.0, value=0.0, step=1.0,
                                      help="0 bedeutet: keine Obergrenze")

    min_dividende = st.slider("Mindest-Dividendenrendite (%)", 0.0, 10.0, 0.0, step=0.5)
    max_kgv = st.slider("Hoechstes KGV", 0, 100, 0, step=5,
                        help="0 bedeutet: keine Obergrenze")
    fonds_zeigen = st.checkbox("ETFs und Fonds einbeziehen", value=True)

kriterien = OverviewFilter(
    min_score=float(min_score) if min_score > 0 else None,
    sectors=gewaehlte_sektoren,
    min_market_cap=kap_min * 1e9 if kap_min > 0 else None,
    max_market_cap=kap_max * 1e9 if kap_max > 0 else None,
    min_dividend_yield=min_dividende if min_dividende > 0 else None,
    max_pe=float(max_kgv) if max_kgv > 0 else None,
    include_funds=fonds_zeigen,
)
ergebnis = apply_filters(zeilen, kriterien)

# --- Kopfzeile ---------------------------------------------------------------
letzte = store.get(LAST_REFRESH_KEY, None)
kpi = st.columns(4)
kpi[0].metric("Titel im Universum", len(zeilen))
kpi[1].metric("Nach Filter", len(ergebnis.rows))
bewertbar = [z["score_total"] for z in ergebnis.rows if z["score_total"] is not None]
kpi[2].metric(
    "Mittlerer Score",
    german_number(sum(bewertbar) / len(bewertbar), 1) if bewertbar else NOT_AVAILABLE,
)
if isinstance(letzte, str):
    try:
        stand = datetime.fromisoformat(letzte)
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

if ohne_daten:
    st.warning(
        f"Fuer {len(ohne_daten)} Titel liegen keine Daten vor: {', '.join(ohne_daten[:12])}"
        + (" ..." if len(ohne_daten) > 12 else "")
        + ". Bitte einmal aktualisieren; bleiben sie leer, ist das Symbol vermutlich unbekannt."
    )

if ergebnis.excluded_by_missing:
    st.info(
        f"{ergebnis.excluded_by_missing} Titel sind nicht durch den Filter gefallen, sondern "
        f"**nicht pruefbar** - die gefilterte Kennzahl fehlt dort: "
        f"{', '.join(ergebnis.missing_tickers[:12])}"
        + (" ..." if len(ergebnis.missing_tickers) > 12 else ""),
        icon="ℹ️",
    )

# --- Tabelle -----------------------------------------------------------------
if not ergebnis.rows:
    st.warning("Kein Titel erfuellt die gewaehlten Filterkriterien.")
    st.stop()

anzeige = pd.DataFrame(ergebnis.rows)[[key for key, _ in COLUMNS]]
anzeige.columns = [label for _, label in COLUMNS]

st.dataframe(
    anzeige,
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
spalte_de, spalte_en = st.columns(2)
zeitstempel = datetime.now().strftime("%Y%m%d_%H%M")
spalte_de.download_button(
    "Als CSV exportieren (deutsches Format)",
    data=rows_to_csv(ergebnis.rows, german=True).encode("utf-8-sig"),
    file_name=f"aktienmonitor_{zeitstempel}.csv",
    mime="text/csv",
    width="stretch",
    help="Semikolon als Trennzeichen, Komma als Dezimaltrennzeichen - oeffnet in Excel direkt.",
)
spalte_en.download_button(
    "Als CSV exportieren (internationales Format)",
    data=rows_to_csv(ergebnis.rows, german=False).encode("utf-8"),
    file_name=f"aktienmonitor_{zeitstempel}_intl.csv",
    mime="text/csv",
    width="stretch",
)
