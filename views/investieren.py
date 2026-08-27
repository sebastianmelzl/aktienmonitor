"""Investieren: Betrag eingeben, 5 Titel nach Fundamentalanalyse vorgeschlagen bekommen.

Anders als die Aufteilung (eigene Watchlist) und die Vorschlaege (mehrstufiger
Assistent) ist das hier ein einzelner Knopf: Marktsuche, vollstaendige
Bewertung und Verteilung auf genau fuenf Titel in einem Schritt, ausgewaehlt
nach dem fundamentalen Teilscore.
"""

from __future__ import annotations

import textwrap

import pandas as pd
import streamlit as st

from aktienmonitor.formatting import NOT_AVAILABLE, german_number
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
    DISCLAIMER,
    coverage_caption,
    get_config,
    get_score_weights,
    get_service,
    metrics_table,
)
from aktienmonitor.ui.costs import render_allocation_costs

ANZAHL_TITEL = 5
# So viele Treffer der Marktsuche werden vollstaendig bewertet - begrenzt, weil
# je Titel mehrere Endpunkte abgerufen werden.
ANALYSE_LIMIT = 15

RESULT_KEY = "_investieren_ergebnis"


def _inject_style() -> None:
    """Eigenes, dunkelblau-goldenes Erscheinungsbild nur fuer diese Seite.

    Reine CSS-Ueberlagerung per ``st.markdown`` - sie wirkt ausschliesslich
    waehrend diese Seite aktiv ist. Beim Wechsel auf eine andere Seite baut
    Streamlit das Skript neu auf, ohne dieses ``<style>`` erneut einzufuegen;
    die uebrigen Seiten bleiben unangetastet.
    """
    st.html(
        textwrap.dedent(
            """
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700;800&family=Inter:wght@400;500;600&display=swap"
              rel="stylesheet">
        <style>
        :root {
            --im-bg: #05070d;
            --im-bg-2: #0a1120;
            --im-surface: #0f1830;
            --im-surface-2: #131f3d;
            --im-border: rgba(201, 162, 39, 0.24);
            --im-border-strong: rgba(201, 162, 39, 0.55);
            --im-gold: #c9a227;
            --im-gold-light: #ecd18a;
            --im-gold-soft: rgba(201, 162, 39, 0.12);
            --im-text: #f2efe6;
            --im-text-muted: #97a2bd;
            --im-text-faint: #6b7590;
        }

        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(1200px 600px at 12% -10%, rgba(201,162,39,0.10), transparent 60%),
                radial-gradient(1000px 700px at 100% 0%, rgba(30,58,110,0.35), transparent 55%),
                linear-gradient(180deg, var(--im-bg) 0%, var(--im-bg-2) 100%);
        }
        [data-testid="stHeader"] { background: transparent; }
        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #070b16 0%, #0a1120 100%);
            border-right: 1px solid var(--im-border);
        }
        section[data-testid="stSidebar"] * { color: var(--im-text) !important; }

        [data-testid="stMainBlockContainer"] {
            font-family: 'Inter', sans-serif;
            color: var(--im-text);
            padding-top: 2.5rem;
            max-width: 1180px;
        }
        [data-testid="stMainBlockContainer"] h1,
        [data-testid="stMainBlockContainer"] h2,
        [data-testid="stMainBlockContainer"] h3 {
            font-family: 'Sora', sans-serif;
            color: var(--im-text);
            letter-spacing: -0.01em;
        }
        [data-testid="stMainBlockContainer"] p,
        [data-testid="stMainBlockContainer"] li,
        [data-testid="stMainBlockContainer"] span,
        [data-testid="stMainBlockContainer"] label { color: var(--im-text); }
        [data-testid="stMainBlockContainer"] small,
        [data-testid="stCaptionContainer"] { color: var(--im-text-muted) !important; }
        [data-testid="stMainBlockContainer"] a { color: var(--im-gold-light); }
        hr { border-color: var(--im-border); }

        /* --- Hero --------------------------------------------------------- */
        .im-hero { padding: 0.25rem 0 1.75rem 0; }
        .im-eyebrow {
            font-family: 'Sora', sans-serif;
            font-size: 0.72rem;
            font-weight: 600;
            letter-spacing: 0.28em;
            color: var(--im-gold);
            text-transform: uppercase;
            margin-bottom: 0.6rem;
        }
        .im-title {
            font-family: 'Sora', sans-serif;
            font-weight: 800;
            font-size: 2.6rem;
            line-height: 1.1;
            margin: 0 0 0.6rem 0;
            background: linear-gradient(100deg, #ffffff 0%, var(--im-gold-light) 55%, var(--im-gold) 100%);
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .im-subtitle {
            font-size: 1.05rem;
            color: var(--im-text-muted);
            max-width: 640px;
            margin: 0;
        }
        .im-divider {
            height: 1px;
            margin: 1.75rem 0;
            background: linear-gradient(90deg, var(--im-border-strong), transparent 70%);
            border: none;
        }
        .im-section-label {
            font-family: 'Sora', sans-serif;
            font-size: 0.72rem;
            font-weight: 600;
            letter-spacing: 0.2em;
            text-transform: uppercase;
            color: var(--im-gold);
            margin: 0 0 0.75rem 0;
        }

        /* --- Widgets -------------------------------------------------------- */
        [data-testid="stNumberInputContainer"],
        [data-testid="stTextInputRootElement"] {
            background-color: var(--im-surface) !important;
            border: 1px solid var(--im-border) !important;
            border-radius: 10px !important;
        }
        [data-testid="stNumberInputField"],
        [data-testid="stTextInput"] input {
            background-color: transparent !important;
            color: var(--im-text) !important;
        }
        [data-testid="stNumberInputStepDown"], [data-testid="stNumberInputStepUp"] {
            color: var(--im-text-muted) !important;
        }
        [data-testid="stMultiSelect"] .react-aria-ComboBox > div,
        [data-testid="stMultiSelect"] [data-baseweb="select"] > div {
            background-color: var(--im-surface) !important;
            border: 1px solid var(--im-border) !important;
            border-radius: 10px !important;
        }
        [data-testid="stMultiSelect"] input { color: var(--im-text) !important; }
        [data-testid="stMultiSelectTagsContainer"] span[data-tag] {
            background-color: var(--im-gold-soft) !important;
            border: 1px solid var(--im-border-strong) !important;
            color: var(--im-gold-light) !important;
            border-radius: 999px !important;
        }
        [data-testid="stWidgetLabel"] p {
            color: var(--im-text-muted) !important;
            font-weight: 500;
            font-size: 0.85rem;
        }
        [data-testid="stRadioOption"] { color: var(--im-text) !important; }
        [data-testid="stRadioOption"][data-selected="true"] {
            background: var(--im-gold-soft);
            border-radius: 999px;
        }
        [data-testid="stRadioOption"] > div > div > div {
            border-color: var(--im-border-strong) !important;
        }
        [data-testid="stRadioOption"][data-selected="true"] > div > div > div {
            border-color: var(--im-gold) !important;
        }
        [data-testid="stRadioOption"][data-selected="true"] > div > div > div > div {
            background-color: var(--im-gold) !important;
        }

        [data-testid="stMainBlockContainer"] button[data-testid^="stBaseButton"] {
            background: linear-gradient(135deg, var(--im-gold) 0%, #a9820f 100%) !important;
            color: #0a0e1a !important;
            font-weight: 700;
            font-family: 'Sora', sans-serif;
            border: none !important;
            border-radius: 999px !important;
            padding: 0.6rem 1.6rem !important;
            box-shadow: 0 8px 24px -8px rgba(201, 162, 39, 0.55);
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        [data-testid="stMainBlockContainer"] button[data-testid^="stBaseButton"]:hover {
            transform: translateY(-1px);
            box-shadow: 0 12px 28px -8px rgba(201, 162, 39, 0.7);
            color: #0a0e1a !important;
        }
        [data-testid="stMainBlockContainer"] button[data-testid^="stBaseButton"] p {
            color: #0a0e1a !important;
        }

        /* --- Metrics, expanders, alerts, progress --------------------------- */
        [data-testid="stMetric"] {
            background: linear-gradient(160deg, var(--im-surface) 0%, var(--im-surface-2) 100%);
            border: 1px solid var(--im-border);
            border-radius: 14px;
            padding: 1rem 1.1rem;
        }
        [data-testid="stMetricLabel"] {
            color: var(--im-text-muted) !important;
            font-size: 0.72rem !important;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        [data-testid="stMetricValue"] {
            color: var(--im-gold-light) !important;
            font-family: 'Sora', sans-serif;
        }

        [data-testid="stExpander"] {
            background: var(--im-surface);
            border: 1px solid var(--im-border);
            border-radius: 14px;
            overflow: hidden;
        }
        [data-testid="stExpander"] summary { color: var(--im-text) !important; }
        [data-testid="stExpander"] summary:hover { color: var(--im-gold-light) !important; }

        [data-testid="stAlertContainer"] {
            border-radius: 10px !important;
            overflow: hidden;
        }
        [data-testid="stAlertContentInfo"],
        [data-testid="stAlertContentWarning"],
        [data-testid="stAlertContentError"],
        [data-testid="stAlertContentSuccess"] {
            background: var(--im-surface) !important;
            border: 1px solid var(--im-border) !important;
            border-left: 3px solid var(--im-gold) !important;
            border-radius: 10px !important;
            color: var(--im-text) !important;
        }
        [data-testid="stAlertContentInfo"] p,
        [data-testid="stAlertContentWarning"] p,
        [data-testid="stAlertContentError"] p,
        [data-testid="stAlertContentSuccess"] p { color: var(--im-text) !important; }

        [data-testid="stProgress"] div[role="progressbar"] > div {
            background: linear-gradient(90deg, var(--im-gold) 0%, var(--im-gold-light) 100%) !important;
        }
        [data-testid="stProgress"] { background-color: var(--im-surface-2) !important; border-radius: 999px; }

        [data-testid="stDataFrame"] {
            border: 1px solid var(--im-border) !important;
            border-radius: 12px;
            overflow: hidden;
        }

        /* --- Eigene Tabelle -------------------------------------------------- */
        .im-table-wrap {
            border: 1px solid var(--im-border);
            border-radius: 14px;
            overflow: hidden;
            margin-bottom: 0.75rem;
        }
        table.im-table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
        table.im-table th {
            font-family: 'Sora', sans-serif;
            text-align: left;
            font-size: 0.7rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--im-gold);
            background: var(--im-surface-2);
            padding: 0.7rem 0.9rem;
            border-bottom: 1px solid var(--im-border);
        }
        table.im-table td {
            padding: 0.65rem 0.9rem;
            color: var(--im-text);
            border-bottom: 1px solid rgba(201,162,39,0.08);
        }
        table.im-table tbody tr:hover { background: rgba(201,162,39,0.06); }
        table.im-table tbody tr:last-child td { border-bottom: none; }
        .im-ticker { font-weight: 700; color: var(--im-gold-light); font-family: 'Sora', sans-serif; }
        .im-muted { color: var(--im-text-muted); }
        .im-num { text-align: right; font-variant-numeric: tabular-nums; }
        .im-bar {
            position: relative;
            width: 100%;
            min-width: 90px;
            height: 8px;
            background: var(--im-surface-2);
            border-radius: 999px;
            overflow: hidden;
        }
        .im-bar-fill {
            position: absolute; left: 0; top: 0; bottom: 0;
            background: linear-gradient(90deg, #8a6d16, var(--im-gold) 60%, var(--im-gold-light));
            border-radius: 999px;
        }
        .im-bar-label { font-size: 0.78rem; color: var(--im-text-muted); margin-left: 0.4rem; }
        </style>
        """
        )
    )


def _score_bar(value: float | None) -> str:
    if value is None:
        return '<span class="im-muted">n/a</span>'
    wert = max(0.0, min(100.0, value))
    return (
        '<div style="display:flex;align-items:center;">'
        f'<div class="im-bar"><div class="im-bar-fill" style="width:{wert:.0f}%"></div></div>'
        f'<span class="im-bar-label">{wert:.0f}</span></div>'
    )


def _render_table(rows: list[dict], columns: list[str]) -> None:
    """Rendert eine schlicht gehaltene HTML-Tabelle im Seitendesign.

    ``st.dataframe`` nutzt ein eigenes, canvasbasiertes Raster, das sich per
    CSS nicht umfaerben laesst - fuer die zentrale Ergebnistabelle dieser
    Seite wird deshalb reines HTML gerendert, das vollstaendig im Griff ist.
    """
    kopf = "".join(f"<th>{col}</th>" for col in columns)
    body = ""
    for row in rows:
        klassen = row.get("_cls", {})
        zellen = "".join(
            f'<td class="{klassen.get(col, "")}">{row[col]}</td>' for col in columns
        )
        body += f"<tr>{zellen}</tr>"
    st.markdown(
        f'<div class="im-table-wrap"><table class="im-table">'
        f"<thead><tr>{kopf}</tr></thead><tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )


_inject_style()

st.markdown(
    textwrap.dedent(
        f"""
    <div class="im-hero">
        <div class="im-eyebrow">Vermoegensaufbau</div>
        <h1 class="im-title">Investieren</h1>
        <p class="im-subtitle">Betrag eingeben – die App durchsucht den Markt und schlaegt
        {ANZAHL_TITEL} Titel nach Fundamentalanalyse vor.</p>
    </div>
    """
    ),
    unsafe_allow_html=True,
)
st.info(DISCLAIMER, icon="ℹ️")
st.warning(
    "**Keine Anlageempfehlung.** Ausgewaehlt wird nach dem fundamentalen Teilscore - "
    "Schwellen, die als Konvention gesetzt und nicht auf Prognosekraft geprueft wurden. "
    "Wer eine grosse Menge an Titeln durchsucht, findet oben in der Liste mit hoher "
    "Wahrscheinlichkeit auch Zufall statt Signal. Die Entscheidung triffst du.",
    icon="⚠️",
)
st.markdown('<hr class="im-divider">', unsafe_allow_html=True)

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
st.markdown('<p class="im-section-label">Vorschlag</p>', unsafe_allow_html=True)
kpi = st.columns(4)
kpi[0].metric("Positionen", len(result.items))
kpi[1].metric("Verteilt", german_number(result.invested, 2))
kpi[2].metric("Rest", german_number(result.cash_left, 2))
kpi[3].metric("Branchen", len(result.sector_shares))

scored_by_ticker = {snap.ticker: scored for snap, scored in daten["top"]}
snapshot_by_ticker = {snap.ticker: snap for snap, _ in daten["top"]}

csv_quelle = pd.DataFrame(
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

_render_table(
    [
        {
            "Ticker": f'<span class="im-ticker">{item.ticker}</span>',
            "Name": f'{item.name}<br><span class="im-muted">{item.sector}</span>',
            "Fundamental": _score_bar(scored_by_ticker[item.ticker].categories["fundamental"].score),
            "Gesamt": (
                f"{scored_by_ticker[item.ticker].total:.0f}"
                if scored_by_ticker[item.ticker].is_available else '<span class="im-muted">n/a</span>'
            ),
            "Anteil": f"{item.weight * 100.0:.1f} %",
            "Kurs": german_number(item.price, 2) if item.price else NOT_AVAILABLE,
            "Stueck": str(item.shares),
            "Betrag": german_number(item.invested_amount, 2),
            "_cls": {"Gesamt": "im-num", "Anteil": "im-num", "Kurs": "im-num",
                     "Stueck": "im-num", "Betrag": "im-num"},
        }
        for item in result.items
    ],
    ["Ticker", "Name", "Fundamental", "Gesamt", "Anteil", "Kurs", "Stueck", "Betrag"],
)
st.download_button(
    "Vorschlag als CSV",
    data=csv_quelle.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
    file_name="investieren.csv",
    mime="text/csv",
)

if result.excluded:
    with st.expander(f"Nicht beruecksichtigt ({len(result.excluded)})"):
        _render_table(
            [{"Ticker": f'<span class="im-ticker">{t}</span>', "Grund": grund}
             for t, grund in result.excluded],
            ["Ticker", "Grund"],
        )

# --- Fundamentalanalyse je Titel ------------------------------------------------
st.markdown('<p class="im-section-label">Fundamentalanalyse je Titel</p>', unsafe_allow_html=True)
for item in result.items:
    snap = snapshot_by_ticker[item.ticker]
    scored = scored_by_ticker[item.ticker]
    with st.expander(f"{item.ticker} – {item.name}"):
        st.caption(coverage_caption(snap.fundamental, "Fundamentaldaten"))
        st.progress(snap.fundamental.coverage)
        fundamental_df = metrics_table(snap.fundamental, snap.currency)
        _render_table(
            fundamental_df.to_dict("records"), list(fundamental_df.columns)
        )
        with st.expander("Vollstaendiges Faktenblatt (alle Teilscores)"):
            st.text(build_briefing(snap, scored))

# --- Kosten und Benchmark --------------------------------------------------------
st.markdown('<p class="im-section-label">Kaufkosten (Trade Republic)</p>', unsafe_allow_html=True)
render_allocation_costs(result.items)

st.markdown('<p class="im-section-label">Vergleich mit einer Benchmark</p>', unsafe_allow_html=True)
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
