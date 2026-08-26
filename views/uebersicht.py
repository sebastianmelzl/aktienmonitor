"""Startseite: Ueberblick ueber Universum, Ausbaustand und Datenquellen."""

from __future__ import annotations

import streamlit as st

from aktienmonitor.ui.common import (
    get_config,
    get_watchlist,
    page_header,
)

page_header(
    "Aktienmonitor",
    "Kennzahlenanalyse fuer das eigene Beobachtungsuniversum - lokal, ohne Weitergabe von Daten",
)

config = get_config()
watchlist = get_watchlist()
entries = watchlist.all()

col_left, col_right = st.columns([2, 1])

with col_left:
    st.subheader("Aktueller Stand")
    if not entries:
        st.write(
            "Das Universum ist noch leer. Unter **Watchlist** koennen Titel per Ticker "
            "hinzugefuegt oder als CSV importiert werden."
        )
    else:
        gruppen = watchlist.groups()
        st.write(
            f"**{len(entries)}** Titel im Universum"
            + (f", verteilt auf **{len(gruppen)}** Listen." if gruppen else ".")
        )
        st.write("Detailauswertung je Titel unter **Detailansicht**.")

    st.subheader("Ausbaustand")
    st.markdown(
        """
        | Phase | Inhalt | Stand |
        |---|---|---|
        | 0 | Datenabruf, Cache, Rate-Limits, Quellen-Check | fertig |
        | 1 | Watchlist, Kennzahlen, Detailansicht | fertig |
        | 2 | Scoring mit Sektorvergleich und Gewichtungs-Slidern | fertig |
        | 3 | Uebersicht auf Knopfdruck, Filter, CSV-Export, Vergleich | offen |
        | 4 | News und Sentiment-Einordnung | offen |
        """
    )

with col_right:
    st.subheader("Datenquellen")
    st.write("**yfinance** – Hauptquelle, kein Schluessel noetig")
    if config.has_finnhub:
        st.write("**Finnhub** – Schluessel hinterlegt, wird ergaenzend genutzt")
    else:
        st.write("**Finnhub** – kein Schluessel hinterlegt (optional)")
    if config.has_anthropic:
        st.write("**Anthropic** – Schluessel hinterlegt (Sentiment ab Phase 4)")
    else:
        st.write("**Anthropic** – kein Schluessel (Sentiment bleibt n/a)")

    st.caption(
        "Welche Endpunkte mit den hinterlegten Schluesseln tatsaechlich nutzbar sind, "
        "zeigt die Seite **Datenquellen**."
    )

    with st.expander("Cache-Lebensdauer"):
        st.write(
            {
                "Kurs": f"{config.ttl_seconds['quote']} s",
                "Kurshistorie": f"{config.ttl_seconds['price_history']} s",
                "Abschluesse": f"{config.ttl_seconds['fundamentals']} s",
                "Stammdaten": f"{config.ttl_seconds['profile']} s",
                "Analysten": f"{config.ttl_seconds['analyst']} s",
                "News": f"{config.ttl_seconds['news']} s",
            }
        )
