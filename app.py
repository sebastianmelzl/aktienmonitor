"""Aktienmonitor - Einstiegspunkt der Streamlit-Anwendung.

Start mit:  streamlit run app.py

Die Navigation wird hier ausdruecklich definiert, damit die Seiten im Menue
deutsche Bezeichnungen tragen.
"""

from __future__ import annotations

import streamlit as st

from aktienmonitor.ui.auth import logout_button, require_access

st.set_page_config(page_title="Aktienmonitor", page_icon="📊", layout="wide")

# Vor jedem Seitenaufbau: im gehosteten Betrieb ist ein Passwort Pflicht.
require_access()

navigation = st.navigation(
    [
        st.Page("views/uebersicht.py", title="Uebersicht", icon="📊", default=True),
        st.Page("views/watchlist.py", title="Watchlist", icon="📋"),
        st.Page("views/detail.py", title="Detailansicht", icon="🔍"),
        st.Page("views/kandidaten.py", title="Kandidaten", icon="🔔"),
        st.Page("views/vorschlaege.py", title="Vorschlaege", icon="🧭"),
        st.Page("views/vergleich.py", title="Vergleich", icon="⚖️"),
        st.Page("views/anlagevorschlag.py", title="Aufteilung", icon="🧮"),
        st.Page("views/datenquellen.py", title="Datenquellen", icon="🔌"),
        st.Page("views/einstellungen.py", title="Einstellungen", icon="⚙️"),
    ]
)
logout_button()
navigation.run()
