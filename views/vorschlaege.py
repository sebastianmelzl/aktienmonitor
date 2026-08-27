"""Vorschlaege: Kandidaten aus dem Markt, nicht aus der eigenen Watchlist."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from aktienmonitor.formatting import compact_currency
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
from aktienmonitor.ui.common import (
    clear_sector_cache,
    get_score_weights,
    get_service,
    get_watchlist,
    page_header,
)

HITS_KEY = "_vorschlaege_treffer"
REQUEST_KEY = "_vorschlaege_anfrage"
ANALYSED_KEY = "_vorschlaege_analysiert"

SECTORS = [
    "Basic Materials", "Communication Services", "Consumer Cyclical",
    "Consumer Defensive", "Energy", "Financial Services", "Healthcare",
    "Industrials", "Real Estate", "Technology", "Utilities",
]

page_header("Vorschlaege", "Kandidaten aus dem Markt finden, nicht nur die eigene Liste bewerten")

st.warning(
    "**Zur Einordnung einer Marktsuche:** Wer Hunderte Titel nach Schwellen durchsucht, "
    "die nie auf Prognosekraft geprueft wurden, findet oben in der Liste mit hoher "
    "Wahrscheinlichkeit Zufall statt Signal - und zwar umso staerker, je groesser die "
    "durchsuchte Menge ist. Die Profile arbeiten deshalb mit Mindestanforderungen an die "
    "Qualitaet statt mit einer blossen Rangfolge. Das mildert den Effekt, es beseitigt "
    "ihn nicht.",
    icon="⚠️",
)

service = get_service()
watchlist = get_watchlist()
bereits_beobachtet = set(watchlist.tickers())

# --- Suchauftrag -------------------------------------------------------------
st.subheader("1. Suchprofil")

profile_key = st.radio(
    "Profil",
    options=[p.key for p in PROFILES],
    format_func=lambda key: PROFILES_BY_KEY[key].name,
    horizontal=True,
)
profile = PROFILES_BY_KEY[profile_key]
st.caption(profile.description)

col_region, col_sector, col_cap = st.columns([2, 2, 1])
with col_region:
    regions = st.multiselect(
        "Region", options=list(REGIONS), default=["de"],
        format_func=lambda code: f"{REGIONS[code]} ({code.upper()})",
    )
with col_sector:
    sectors = st.multiselect("Branche (leer = alle)", options=SECTORS)
with col_cap:
    min_cap_mrd = st.number_input("Mindestgroesse (Mrd.)", min_value=0.0, value=1.0, step=0.5)

with st.expander("Welche Kriterien dieses Profil anlegt"):
    for criterion in profile.criteria:
        st.markdown(f"- **{criterion.describe()}** – {criterion.rationale}")
    st.caption(
        "Die Einheiten der Screenerfelder sind nicht dokumentiert und liessen sich in der "
        "Entwicklungsumgebung nicht pruefen. Wenn die Suche null oder sehr viele Treffer "
        "liefert, liegt das haeufiger an einer falsch angenommenen Einheit als am Markt."
    )

if not regions:
    st.info("Bitte mindestens eine Region waehlen.")
    st.stop()

request = ScreenRequest(
    profile=profile,
    regions=tuple(regions),
    sectors=tuple(sectors),
    min_market_cap=float(min_cap_mrd) * 1e9,
    limit=100,
)

if st.button("Marktsuche starten", type="primary"):
    with st.spinner("Der Markt wird durchsucht ..."):
        result = service.screener.run(request, force_refresh=True)
    if not result.ok:
        st.error(f"Die Marktsuche ist fehlgeschlagen: {result.error}")
        st.stop()
    st.session_state[HITS_KEY] = parse_hits(result.data)
    st.session_state[REQUEST_KEY] = request.describe()
    st.session_state.pop(ANALYSED_KEY, None)

hits = st.session_state.get(HITS_KEY)
if hits is None:
    st.info("Noch keine Suche ausgefuehrt.")
    st.stop()

# --- Treffer -----------------------------------------------------------------
st.subheader(f"2. Treffer ({len(hits)})")

hinweis = diagnose_result_count(len(hits), request.limit)
if hinweis:
    st.warning(hinweis, icon="⚠️")

if not hits:
    st.stop()

neu = [h for h in hits if h.ticker not in bereits_beobachtet]
st.caption(
    f"{len(neu)} davon stehen noch nicht in deiner Watchlist. "
    "Die Marktsuche liefert nur eine Vorauswahl anhand weniger Kennzahlen - die "
    "eigentliche Bewertung entsteht erst im naechsten Schritt."
)

st.dataframe(
    pd.DataFrame(
        [
            {
                "Ticker": h.ticker,
                "Name": h.name or "",
                "Branche": h.sector or "",
                "Boerse": h.exchange or "",
                "Marktkapitalisierung": compact_currency(h.market_cap) if h.market_cap else "",
                "Schon beobachtet": "ja" if h.ticker in bereits_beobachtet else "",
            }
            for h in hits
        ]
    ),
    width="stretch", hide_index=True,
)

# --- Tiefenanalyse -----------------------------------------------------------
st.subheader("3. Vollstaendige Analyse")
st.caption(
    "Je Titel werden mehrere Endpunkte abgerufen. Das dauert und belastet die "
    "Rate-Limits - deshalb nur fuer eine begrenzte Auswahl."
)

col_count, col_only_new, col_run = st.columns([1, 1, 1])
with col_count:
    count = st.slider("Anzahl", min_value=3, max_value=min(40, len(hits)),
                      value=min(12, len(hits)))
with col_only_new:
    only_new = st.checkbox("Nur noch nicht beobachtete", value=True)
with col_run:
    st.write("")
    analysieren = st.button("Auswahl analysieren", width="stretch")

auswahl = [h for h in (neu if only_new else hits)][:count]

if analysieren and auswahl:
    progress = st.progress(0.0, text="Analyse wird vorbereitet ...")

    def report(index: int, total: int, ticker: str) -> None:
        progress.progress(
            min(1.0, index / total if total else 1.0),
            text=f"{ticker} wird geholt ({index + 1} von {total}) ..." if ticker
            else f"{index} von {total} geholt",
        )

    with st.spinner("Kennzahlen werden geholt ..."):
        snapshots = service.get_snapshots(
            [h.ticker for h in auswahl], with_news=False, progress=report
        )
    progress.empty()
    st.session_state[ANALYSED_KEY] = list(snapshots)
    clear_sector_cache()

analysed = st.session_state.get(ANALYSED_KEY)
if not analysed:
    st.info("Noch keine Auswahl analysiert.")
    st.stop()

snapshots = service.get_snapshots(analysed, cache_only=True, with_news=False)
# Vergleichsgruppe sind hier die analysierten Treffer selbst - sie stammen aus
# derselben Suche und sind damit die naheliegendere Gruppe als die Watchlist.
statistics = SectorStatistics.from_universe(
    [(s.profile.sector, s.fundamental) for s in snapshots.values()]
)
weights = get_score_weights()
scored_by_ticker = {
    ticker: score_snapshot(snap, statistics=statistics, weights=weights)
    for ticker, snap in snapshots.items()
}

rows = sorted(
    (
        {
            "Ticker": ticker,
            "Name": snap.profile.name or "",
            "Branche": snap.profile.sector or "",
            "Gesamtscore": scored_by_ticker[ticker].total,
            "Fundamental": scored_by_ticker[ticker].categories["fundamental"].score,
            "Technik": scored_by_ticker[ticker].categories["technical"].score,
            "Analysten": scored_by_ticker[ticker].categories["analyst"].score,
            "Abdeckung %": scored_by_ticker[ticker].categories["fundamental"].weight_coverage
            * 100.0,
            "Kurs": snap.price,
            "Hinweis": "" if snap.has_any_data else "Keine Daten abrufbar",
        }
        for ticker, snap in snapshots.items()
    ),
    key=lambda r: (r["Gesamtscore"] is None, -(r["Gesamtscore"] or 0.0)),
)

st.dataframe(
    pd.DataFrame(rows), width="stretch", hide_index=True,
    column_config={
        "Gesamtscore": st.column_config.ProgressColumn(
            format="%.0f", min_value=0, max_value=100
        ),
        "Fundamental": st.column_config.NumberColumn(format="%.0f"),
        "Technik": st.column_config.NumberColumn(format="%.0f"),
        "Analysten": st.column_config.NumberColumn(format="%.0f"),
        "Abdeckung %": st.column_config.NumberColumn(format="%.0f"),
        "Kurs": st.column_config.NumberColumn(format="localized"),
    },
)
st.caption(
    "**Abdeckung %** ist der Anteil der genutzten Gewichtung. Ein hoher Score aus wenig "
    "Daten ist weniger belastbar als derselbe Score aus vielen - bei frisch gefundenen "
    "Titeln ist die Abdeckung oft niedriger, weil noch keine Vergleichsgruppe existiert."
)

# --- Uebernahme --------------------------------------------------------------
st.subheader("4. In die Watchlist uebernehmen")
uebernehmbar = [r["Ticker"] for r in rows if r["Ticker"] not in bereits_beobachtet]
if not uebernehmbar:
    st.caption("Alle analysierten Titel stehen bereits in deiner Watchlist.")
else:
    auswahl_uebernahme = st.multiselect(
        "Titel", options=uebernehmbar,
        default=[r["Ticker"] for r in rows[:3] if r["Ticker"] in uebernehmbar],
    )
    gruppe = st.text_input("Liste (optional)", value=profile.name)
    if st.button("Uebernehmen") and auswahl_uebernahme:
        for ticker in auswahl_uebernahme:
            watchlist.add(ticker)
            if gruppe.strip():
                watchlist.assign(ticker, gruppe.strip())
        clear_sector_cache()
        st.success(
            f"{len(auswahl_uebernahme)} Titel uebernommen. Sie erscheinen jetzt in der "
            "Uebersicht und werden beim naechsten Aktualisieren mitgeholt."
        )
        st.rerun()

with st.expander("Wie dieser Vorschlag entsteht"):
    st.markdown(
        """
        **Stufe 1 – Marktsuche.** Eine einzige Abfrage an Yahoo Finance mit den harten
        Kriterien des Profils. Sie liefert bis zu 250 Titel und stuetzt sich nur auf
        wenige Kennzahlen.

        **Stufe 2 – Vollstaendige Analyse.** Fuer die gewaehlten Treffer wird derselbe
        Kennzahlensatz geholt und bewertet wie fuer die eigene Watchlist. Erst hier
        entsteht ein Score.

        **Vergleichsgruppe.** Die sektorrelativen Kennzahlen vergleichen hier gegen die
        anderen analysierten Treffer - nicht gegen deine Watchlist und nicht gegen den
        Gesamtmarkt. Bei wenigen Treffern derselben Branche entfallen sie ganz, was die
        ausgewiesene Abdeckung senkt.
        """
    )
    if REQUEST_KEY in st.session_state:
        st.markdown("**Zuletzt gesuchte Kriterien**")
        for line in st.session_state[REQUEST_KEY]:
            st.markdown(f"- {line}")
