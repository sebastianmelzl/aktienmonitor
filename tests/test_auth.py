"""Tests des Zugangsschutzes.

Der wichtigste Fall ist der letzte: gehostet ohne Passwort darf die App nicht
starten. Sonst koennte jeder mit der URL Datenabrufe ausloesen und damit die
hinterlegten API-Schluessel verbrauchen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aktienmonitor.ui.auth import (
    HOSTING_MARKERS,
    MAX_ATTEMPTS,
    PASSWORD_ENV,
    configured_password,
    is_hosted,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def saubere_umgebung(monkeypatch):
    """Entfernt alle Hoster- und Passwortvariablen vor jedem Test."""
    for marker in HOSTING_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.delenv(PASSWORD_ENV, raising=False)


class TestUmgebungserkennung:
    @pytest.mark.parametrize("marker", HOSTING_MARKERS)
    def test_hoster_wird_erkannt(self, marker, monkeypatch):
        monkeypatch.setenv(marker, "8080")
        assert is_hosted()

    def test_lokal_ohne_marker(self):
        assert not is_hosted()

    def test_leere_variable_zaehlt_nicht_als_hoster(self, monkeypatch):
        monkeypatch.setenv("PORT", "")
        assert not is_hosted()


class TestPasswortkonfiguration:
    def test_ohne_variable(self):
        assert configured_password() is None

    def test_leere_variable_gilt_als_nicht_gesetzt(self, monkeypatch):
        monkeypatch.setenv(PASSWORD_ENV, "   ")
        assert configured_password() is None

    def test_gesetztes_passwort_wird_getrimmt(self, monkeypatch):
        monkeypatch.setenv(PASSWORD_ENV, "  geheim  ")
        assert configured_password() == "geheim"


def run_app(timeout: int = 60):
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=timeout).run()


@pytest.mark.usefixtures("seeded_app")
class TestZugang:
    """Durchlaeufe der echten App unter verschiedenen Umgebungen."""

    def test_lokal_ohne_passwort_laeuft_durch(self, monkeypatch):
        ergebnis = run_app()
        assert not ergebnis.exception
        # Keine Anmeldemaske, kein Abbruch.
        assert not any("Passwort" in (e.value or "") for e in ergebnis.error)

    def test_gehostet_ohne_passwort_verweigert_den_start(self, monkeypatch):
        """Der Kernfall: kein Passwort im gehosteten Betrieb -> kein Zugriff."""
        monkeypatch.setenv("PORT", "8080")
        ergebnis = run_app()

        meldungen = " ".join(e.value or "" for e in ergebnis.error)
        assert "Start verweigert" in meldungen
        assert PASSWORD_ENV in meldungen
        # Die Navigation darf gar nicht erst aufgebaut worden sein.
        assert not ergebnis.dataframe

    def test_gehostet_mit_passwort_zeigt_anmeldung(self, monkeypatch):
        monkeypatch.setenv("PORT", "8080")
        monkeypatch.setenv(PASSWORD_ENV, "geheim")
        ergebnis = run_app()

        assert not ergebnis.exception
        assert ergebnis.text_input, "Es muss ein Passwortfeld geben"
        # Ohne Anmeldung keine Inhalte.
        assert not ergebnis.dataframe

    def test_falsches_passwort_gewaehrt_keinen_zugang(self, monkeypatch):
        monkeypatch.setenv("PORT", "8080")
        monkeypatch.setenv(PASSWORD_ENV, "geheim")
        ergebnis = run_app()
        ergebnis.text_input[0].set_value("falsch").run()
        ergebnis.button[0].click().run()

        meldungen = " ".join(e.value or "" for e in ergebnis.error)
        assert "Falsches Passwort" in meldungen
        assert not ergebnis.dataframe

    def test_richtiges_passwort_gewaehrt_zugang(self, monkeypatch):
        monkeypatch.setenv("PORT", "8080")
        monkeypatch.setenv(PASSWORD_ENV, "geheim")
        ergebnis = run_app()
        ergebnis.text_input[0].set_value("geheim").run()
        ergebnis.button[0].click().run()

        assert not ergebnis.exception
        # Nach der Anmeldung ist die Uebersicht da.
        assert ergebnis.dataframe, "Nach erfolgreicher Anmeldung muss die Uebersicht erscheinen"

    def test_zu_viele_fehlversuche_sperren(self, monkeypatch):
        monkeypatch.setenv("PORT", "8080")
        monkeypatch.setenv(PASSWORD_ENV, "geheim")
        ergebnis = run_app()
        for _ in range(MAX_ATTEMPTS):
            ergebnis.text_input[0].set_value("falsch").run()
            ergebnis.button[0].click().run()

        meldungen = " ".join(e.value or "" for e in ergebnis.error)
        assert "Fehlversuche" in meldungen
        assert not ergebnis.dataframe
