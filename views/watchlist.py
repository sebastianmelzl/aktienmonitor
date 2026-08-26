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
        col_ticker, col_group, col_button = st.columns([2, 2, 1])
        with col_ticker:
            entered = st.text_input(
                "Ticker", placeholder="z.B. AAPL, SAP.DE, 7203.T",
                help="Symbol wie bei Yahoo Finance. Deutsche Titel enden auf .DE",
            )
        with col_group:
            groups = watchlist.groups()
            group = st.selectbox(
                "Liste (optional)", options=["– keine –", *groups, "+ neue Liste"], index=0
            )
            new_group = (
                st.text_input("Name der neuen Liste", key="neue_liste")
                if group == "+ neue Liste"
                else ""
            )
        with col_button:
            st.write("")
            st.write("")
            add_clicked = st.form_submit_button("Hinzufuegen", width="stretch")

    if add_clicked:
        ticker = normalise_ticker(entered)
        if ticker is None:
            st.error(
                f"'{entered}' ist kein gueltiger Ticker. Erlaubt sind Buchstaben, Ziffern, "
                "Punkt und Bindestrich."
            )
        else:
            watchlist.add(ticker)
            target_group = new_group.strip() if group == "+ neue Liste" else (
                group if group not in ("– keine –", "+ neue Liste") else ""
            )
            if target_group:
                watchlist.assign(ticker, target_group)
            st.success(f"{ticker} aufgenommen." + (f" Liste: {target_group}" if target_group else ""))
            st.rerun()

    st.divider()

    entries = watchlist.all()
    if not entries:
        st.info("Noch keine Titel im Universum.")
    else:
        st.caption(f"{len(entries)} Titel im Universum")
        for entry in entries:
            col_name, col_groups, col_remove = st.columns([3, 3, 1])
            with col_name:
                bezeichnung = entry.display_name or ""
                st.write(f"**{entry.ticker}**" + (f" – {bezeichnung}" if bezeichnung else ""))
            with col_groups:
                selection = st.multiselect(
                    "Listen", options=watchlist.groups(), default=list(entry.groups),
                    key=f"gruppen_{entry.ticker}", label_visibility="collapsed",
                    placeholder="keiner Liste zugeordnet",
                )
                if set(selection) != set(entry.groups):
                    watchlist.set_groups(entry.ticker, selection)
                    st.rerun()
            with col_remove:
                if st.button("Entfernen", key=f"weg_{entry.ticker}", width="stretch"):
                    watchlist.remove(entry.ticker)
                    st.rerun()

with tab_import:
    st.write(
        "Erwartet wird eine CSV mit einer Spalte `ticker` (Pflicht) sowie optional "
        "`name` und `gruppe`. Ohne Kopfzeile wird die erste Spalte als Ticker gelesen. "
        "Komma, Semikolon und Tabulator werden als Trennzeichen erkannt."
    )
    st.code("ticker,name,gruppe\nAAPL,Apple Inc.,Tech\nSAP.DE,SAP SE,Tech\nO,Realty Income,Dividende")

    uploaded_file = st.file_uploader("CSV-Datei", type=["csv", "txt"])
    if uploaded_file is not None and st.button("Importieren"):
        content = uploaded_file.getvalue().decode("utf-8-sig", errors="replace")
        accepted, rejected = watchlist.import_csv(content)
        if accepted:
            st.success(f"{len(accepted)} Titel uebernommen: {', '.join(accepted)}")
        if rejected:
            # Abgelehnte Zeilen werden benannt, nicht stillschweigend verworfen.
            st.warning(f"{len(rejected)} Eintraege abgelehnt: {', '.join(rejected)}")
        if not accepted and not rejected:
            st.info("Die Datei enthielt keine verwertbaren Zeilen.")

with tab_listen:
    with st.form("liste_anlegen", clear_on_submit=True):
        name = st.text_input("Neue Liste", placeholder="z.B. Dividende")
        if st.form_submit_button("Anlegen") and name.strip():
            watchlist.create_group(name)
            st.success(f"Liste '{name.strip()}' angelegt.")
            st.rerun()

    groups = watchlist.groups()
    if not groups:
        st.info("Noch keine Listen angelegt.")
    else:
        entries = watchlist.all()
        overview = pd.DataFrame(
            [
                {
                    "Liste": group,
                    "Titel": len([e for e in entries if group in e.groups]),
                    "Ticker": ", ".join(e.ticker for e in entries if group in e.groups),
                }
                for group in groups
            ]
        )
        st.dataframe(overview, width="stretch", hide_index=True)

        to_delete = st.selectbox("Liste loeschen", options=["– auswaehlen –", *groups])
        if to_delete != "– auswaehlen –" and st.button("Liste loeschen"):
            watchlist.delete_group(to_delete)
            st.success(f"Liste '{to_delete}' geloescht. Die Titel bleiben erhalten.")
            st.rerun()
