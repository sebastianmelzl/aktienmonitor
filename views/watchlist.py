"""Verwaltung des beobachteten Universums."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from aktienmonitor.storage.watchlist import normalise_ticker
from aktienmonitor.ui.common import get_watchlist, page_header

page_header("Watchlist", "Titel und Listen des beobachteten Universums")

watchlist = get_watchlist()

tab_titel, tab_import, tab_listen = st.tabs(["Titel", "CSV-Import", "Listen"])

with tab_titel:
    with st.form("titel_hinzufuegen", clear_on_submit=True):
        spalte_ticker, spalte_gruppe, spalte_knopf = st.columns([2, 2, 1])
        with spalte_ticker:
            eingabe = st.text_input(
                "Ticker", placeholder="z.B. AAPL, SAP.DE, 7203.T",
                help="Symbol wie bei Yahoo Finance. Deutsche Titel enden auf .DE",
            )
        with spalte_gruppe:
            gruppen = watchlist.groups()
            gruppe = st.selectbox(
                "Liste (optional)", options=["– keine –", *gruppen, "+ neue Liste"], index=0
            )
            neue_gruppe = (
                st.text_input("Name der neuen Liste", key="neue_liste")
                if gruppe == "+ neue Liste"
                else ""
            )
        with spalte_knopf:
            st.write("")
            st.write("")
            hinzufuegen = st.form_submit_button("Hinzufuegen", width="stretch")

    if hinzufuegen:
        ticker = normalise_ticker(eingabe)
        if ticker is None:
            st.error(
                f"'{eingabe}' ist kein gueltiger Ticker. Erlaubt sind Buchstaben, Ziffern, "
                "Punkt und Bindestrich."
            )
        else:
            watchlist.add(ticker)
            ziel = neue_gruppe.strip() if gruppe == "+ neue Liste" else (
                gruppe if gruppe not in ("– keine –", "+ neue Liste") else ""
            )
            if ziel:
                watchlist.assign(ticker, ziel)
            st.success(f"{ticker} aufgenommen." + (f" Liste: {ziel}" if ziel else ""))
            st.rerun()

    st.divider()

    eintraege = watchlist.all()
    if not eintraege:
        st.info("Noch keine Titel im Universum.")
    else:
        st.caption(f"{len(eintraege)} Titel im Universum")
        for eintrag in eintraege:
            spalte_name, spalte_gruppen, spalte_entfernen = st.columns([3, 3, 1])
            with spalte_name:
                bezeichnung = eintrag.display_name or ""
                st.write(f"**{eintrag.ticker}**" + (f" – {bezeichnung}" if bezeichnung else ""))
            with spalte_gruppen:
                auswahl = st.multiselect(
                    "Listen", options=watchlist.groups(), default=list(eintrag.groups),
                    key=f"gruppen_{eintrag.ticker}", label_visibility="collapsed",
                    placeholder="keiner Liste zugeordnet",
                )
                if set(auswahl) != set(eintrag.groups):
                    watchlist.set_groups(eintrag.ticker, auswahl)
                    st.rerun()
            with spalte_entfernen:
                if st.button("Entfernen", key=f"weg_{eintrag.ticker}", width="stretch"):
                    watchlist.remove(eintrag.ticker)
                    st.rerun()

with tab_import:
    st.write(
        "Erwartet wird eine CSV mit einer Spalte `ticker` (Pflicht) sowie optional "
        "`name` und `gruppe`. Ohne Kopfzeile wird die erste Spalte als Ticker gelesen. "
        "Komma, Semikolon und Tabulator werden als Trennzeichen erkannt."
    )
    st.code("ticker,name,gruppe\nAAPL,Apple Inc.,Tech\nSAP.DE,SAP SE,Tech\nO,Realty Income,Dividende")

    datei = st.file_uploader("CSV-Datei", type=["csv", "txt"])
    if datei is not None and st.button("Importieren"):
        inhalt = datei.getvalue().decode("utf-8-sig", errors="replace")
        uebernommen, abgelehnt = watchlist.import_csv(inhalt)
        if uebernommen:
            st.success(f"{len(uebernommen)} Titel uebernommen: {', '.join(uebernommen)}")
        if abgelehnt:
            # Abgelehnte Zeilen werden benannt, nicht stillschweigend verworfen.
            st.warning(f"{len(abgelehnt)} Eintraege abgelehnt: {', '.join(abgelehnt)}")
        if not uebernommen and not abgelehnt:
            st.info("Die Datei enthielt keine verwertbaren Zeilen.")

with tab_listen:
    with st.form("liste_anlegen", clear_on_submit=True):
        name = st.text_input("Neue Liste", placeholder="z.B. Dividende")
        if st.form_submit_button("Anlegen") and name.strip():
            watchlist.create_group(name)
            st.success(f"Liste '{name.strip()}' angelegt.")
            st.rerun()

    gruppen = watchlist.groups()
    if not gruppen:
        st.info("Noch keine Listen angelegt.")
    else:
        eintraege = watchlist.all()
        uebersicht = pd.DataFrame(
            [
                {
                    "Liste": gruppe,
                    "Titel": len([e for e in eintraege if gruppe in e.groups]),
                    "Ticker": ", ".join(e.ticker for e in eintraege if gruppe in e.groups),
                }
                for gruppe in gruppen
            ]
        )
        st.dataframe(uebersicht, width="stretch", hide_index=True)

        zu_loeschen = st.selectbox("Liste loeschen", options=["– auswaehlen –", *gruppen])
        if zu_loeschen != "– auswaehlen –" and st.button("Liste loeschen"):
            watchlist.delete_group(zu_loeschen)
            st.success(f"Liste '{zu_loeschen}' geloescht. Die Titel bleiben erhalten.")
            st.rerun()
