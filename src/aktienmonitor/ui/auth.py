"""Zugangsschutz.

Die App war als lokale Anwendung entworfen. Wird sie gehostet, aendert sich die
Lage grundlegend: wer die URL kennt, kann Datenabrufe ausloesen - und damit die
hinterlegten API-Schluessel verbrauchen. Beim Sprachmodell entstehen dabei
echte Kosten.

Deshalb gilt hier: **im gehosteten Betrieb ohne Passwort startet die App nicht.**
Lokal (kein ``PORT`` gesetzt) bleibt sie ohne Passwort nutzbar, damit die
Einstiegshuerde niedrig ist.

Zur Einordnung: Das ist ein einzelnes gemeinsames Passwort, keine
Benutzerverwaltung. Es schuetzt vor zufaelligem Zugriff und ungewollten Kosten -
nicht vor einem entschlossenen Angreifer.
"""

from __future__ import annotations

import hmac
import os

import streamlit as st

PASSWORD_ENV = "AKTIENMONITOR_APP_PASSWORD"
SESSION_KEY = "_zugang_gewaehrt"
ATTEMPT_KEY = "_zugang_versuche"

# Railway, Render, Fly und die meisten anderen Anbieter setzen PORT. Lokal ist
# die Variable normalerweise nicht gesetzt.
HOSTING_MARKERS = ("PORT", "RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID")

MAX_ATTEMPTS = 5


def is_hosted() -> bool:
    """Erkennt, ob die App bei einem Hoster laeuft statt lokal."""
    return any(os.getenv(marker) for marker in HOSTING_MARKERS)


def configured_password() -> str | None:
    wert = (os.getenv(PASSWORD_ENV) or "").strip()
    return wert or None


def require_access() -> None:
    """Laesst den Seitenaufbau nur mit gueltigem Zugang weiterlaufen.

    Ohne Zugang wird der Seitenaufbau mit ``st.stop()`` beendet - es gibt keinen
    Pfad, auf dem Inhalte ohne Freigabe gerendert werden.
    """
    password = configured_password()

    if password is None:
        if is_hosted():
            _refuse_start()
        return  # lokaler Betrieb ohne Passwort

    if st.session_state.get(SESSION_KEY) is True:
        return

    _render_login(password)


def _refuse_start() -> None:
    """Bricht ab, wenn gehostet und kein Passwort gesetzt ist."""
    st.error(
        "**Start verweigert: kein Zugangspasswort gesetzt.**\n\n"
        "Diese Anwendung laeuft offenbar bei einem Hoster, aber die Variable "
        f"`{PASSWORD_ENV}` ist leer. Ohne Passwort koennte jeder mit dieser URL "
        "Datenabrufe ausloesen und damit die hinterlegten API-Schluessel "
        "verbrauchen - beim Sprachmodell entstehen dabei echte Kosten.\n\n"
        f"Bitte `{PASSWORD_ENV}` in den Umgebungsvariablen setzen und neu starten.",
        icon="🔒",
    )
    st.stop()


def _render_login(expected: str) -> None:
    st.title("Aktienmonitor")
    st.caption("Bitte Zugangspasswort eingeben.")

    attempts = st.session_state.get(ATTEMPT_KEY, 0)
    if attempts >= MAX_ATTEMPTS:
        st.error(
            f"{MAX_ATTEMPTS} Fehlversuche. Bitte die Seite neu laden, um es erneut "
            "zu versuchen.",
            icon="🔒",
        )
        st.stop()

    with st.form("anmeldung"):
        entered = st.text_input("Passwort", type="password")
        submitted = st.form_submit_button("Anmelden")

    if submitted:
        # Konstantzeitiger Vergleich, damit die Laufzeit nichts ueber das
        # Passwort verraet.
        if hmac.compare_digest(entered, expected):
            st.session_state[SESSION_KEY] = True
            st.session_state[ATTEMPT_KEY] = 0
            st.rerun()

        attempts += 1
        st.session_state[ATTEMPT_KEY] = attempts
        if attempts >= MAX_ATTEMPTS:
            # Sperre sofort melden, nicht erst beim naechsten Seitenaufbau.
            st.error(
                f"{MAX_ATTEMPTS} Fehlversuche. Bitte die Seite neu laden, um es erneut "
                "zu versuchen.",
                icon="🔒",
            )
        else:
            st.error(f"Falsches Passwort ({attempts} von {MAX_ATTEMPTS} Versuchen).")

    st.stop()


def logout_button(container=None) -> None:
    """Abmelden - nur sinnvoll, wenn ein Passwort gesetzt ist."""
    if configured_password() is None:
        return
    target_group = container or st.sidebar
    if target_group.button("Abmelden", width="stretch"):
        st.session_state[SESSION_KEY] = False
        st.rerun()
