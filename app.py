"""Aktienmonitor - Einstiegspunkt der Streamlit-Anwendung.

Start mit:  streamlit run app.py

Die Navigation wird hier ausdruecklich definiert, damit die Seiten im Menue
deutsche Bezeichnungen tragen.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Aktienmonitor", page_icon="📊", layout="wide")

navigation = st.navigation(
    [
        st.Page("views/uebersicht.py", title="Start", icon="📊", default=True),
        st.Page("views/watchlist.py", title="Watchlist", icon="📋"),
        st.Page("views/detail.py", title="Detailansicht", icon="🔍"),
        st.Page("views/datenquellen.py", title="Datenquellen", icon="🔌"),
        st.Page("views/einstellungen.py", title="Einstellungen", icon="⚙️"),
    ]
)
navigation.run()
