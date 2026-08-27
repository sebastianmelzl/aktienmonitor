"""Backtest des technischen Teilscores - Grenzen siehe der Hinweis auf der Seite."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from aktienmonitor.backtest.technical import LIMITATIONS, bucket_by_score, pearson_correlation, walk_forward
from aktienmonitor.formatting import NOT_AVAILABLE, format_change
from aktienmonitor.ui.common import get_config, get_service, get_watchlist, page_header

MIN_BEOBACHTUNGEN = 10

page_header("Backtest", "Nur der technische Teilscore laesst sich ehrlich zurueckrechnen")

st.warning(
    "**Kein Beleg fuer die Treffsicherheit des Scores - eine Beobachtung mit "
    "bekannten Grenzen:**\n\n" + "\n".join(f"- {text}" for text in LIMITATIONS),
    icon="⚠️",
)

watchlist = get_watchlist()
service = get_service()
config = get_config()
entries = watchlist.all()

if not entries:
    st.info("Das Universum ist noch leer. Bitte zuerst unter **Watchlist** Titel aufnehmen.")
    st.stop()

col_ticker, col_horizon, col_step = st.columns([2, 1, 1])
with col_ticker:
    alle_ticker = [e.ticker for e in entries]
    ausgewaehlt = st.multiselect(
        "Titel", options=alle_ticker, default=alle_ticker[: min(10, len(alle_ticker))]
    )
with col_horizon:
    horizonte = {
        "1 Monat (21 Handelstage)": 21,
        "3 Monate (63)": 63,
        "6 Monate (126)": 126,
        "1 Jahr (252)": 252,
    }
    horizon_label = st.selectbox("Horizont der Folgerendite", options=list(horizonte))
    horizon_days = horizonte[horizon_label]
with col_step:
    step_days = st.slider(
        "Abstand zwischen Stichtagen (Handelstage)", 5, 63, 21,
        help="Kurze Abstaende erzeugen mehr, aber staerker ueberlappende Beobachtungen - "
             "das sind keine unabhaengigen Stichproben.",
    )

if not ausgewaehlt:
    st.info("Bitte mindestens einen Titel auswaehlen.")
    st.stop()

if not st.button("Backtest berechnen", type="primary"):
    st.stop()

with st.spinner("Wird aus dem Cache berechnet - kein neuer Datenabruf ..."):
    snapshots = service.get_snapshots(ausgewaehlt, cache_only=True, with_news=False)
    benchmark_bars = service.get_benchmark_bars(cache_only=True)

    je_titel = {
        ticker: walk_forward(
            snapshots[ticker].bars, horizon_days=horizon_days, step_days=step_days,
            benchmark_bars=benchmark_bars,
        )
        for ticker in ausgewaehlt
    }

alle_punkte = [p for punkte in je_titel.values() for p in punkte]
verwendbar = [p for p in alle_punkte if p.usable]

ohne_historie = [t for t, p in je_titel.items() if not p]
if ohne_historie:
    st.info(
        f"Fuer {len(ohne_historie)} Titel reicht die zwischengespeicherte Kurshistorie nicht "
        f"fuer den gewaehlten Horizont: {', '.join(ohne_historie[:12])}"
        + (" ..." if len(ohne_historie) > 12 else ""),
        icon="ℹ️",
    )

if len(verwendbar) < MIN_BEOBACHTUNGEN:
    st.warning(
        f"Nur {len(verwendbar)} auswertbare Beobachtungen - das ist zu wenig fuer eine "
        "sinnvolle Aussage. Mehr Titel waehlen oder in der Detailansicht eine laengere "
        "Kurshistorie abrufen.",
        icon="⚠️",
    )
    st.stop()

st.subheader(f"{len(verwendbar)} Beobachtungen aus {len(ausgewaehlt)} Titeln")

gruppen = bucket_by_score(alle_punkte)
tabelle = pd.DataFrame(
    [
        {
            "Score-Terzil": gruppe.label,
            "Score-Spanne": f"{gruppe.lower:.0f}-{gruppe.upper:.0f}",
            "n": gruppe.n,
            "Mittlere Folgerendite": format_change(gruppe.mean_forward_return),
            f"Mittlere Rendite {config.benchmark_ticker}": format_change(
                gruppe.mean_benchmark_return
            ),
            "Anteil mit Vorsprung": (
                f"{gruppe.win_rate:.0f} %" if gruppe.win_rate is not None else NOT_AVAILABLE
            ),
        }
        for gruppe in gruppen
    ]
)
st.dataframe(tabelle, width="stretch", hide_index=True)
st.caption(
    "Terzile statt fester Schwellen: die Beobachtungen werden in drei gleich grosse Gruppen "
    "nach dem damaligen technischen Score geteilt. **Mittlere Folgerendite** ist die "
    "tatsaechliche Kursrendite der folgenden Handelstage - nicht der Score selbst."
)

korrelation = pearson_correlation(alle_punkte)
st.metric(
    "Korrelation Score / Folgerendite",
    f"{korrelation:.2f}" if korrelation is not None else NOT_AVAILABLE,
)
st.caption(
    "Ueber alle Beobachtungen und Titel hinweg gebildet - bei ueberlappenden Zeitfenstern "
    "und mehreren gleichzeitig beobachteten Titeln keine strenge statistische Kennzahl, "
    "sondern eine grobe Richtungsangabe."
)

with st.expander("Je Titel"):
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Ticker": ticker,
                    "Stichtage": len(punkte),
                    "Auswertbar": len([p for p in punkte if p.usable]),
                }
                for ticker, punkte in je_titel.items()
            ]
        ),
        width="stretch", hide_index=True,
    )
