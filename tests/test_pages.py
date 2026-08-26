"""Durchlauftest aller Seiten mit Streamlits eigenem Testlaeufer.

Diese Tests fangen Fehler, die Unit-Tests nicht sehen: eine umbenannte Funktion,
eine fehlerhafte Spaltenkonfiguration oder ein Tippfehler in einer Seite faellt
sonst erst beim Aufruf im Browser auf.

Die Testdaten sind synthetisch und liegen in einer temporaeren Datenbank. Die
Ticker heissen bewusst TEST*, damit sie nicht mit echten Werten zu verwechseln
sind - in die Oberflaeche des Nutzers gelangen sie nie.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import TEST_SECURITIES

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VIEWS = PROJECT_ROOT / "views"

def run_page(name: str, timeout: int = 120):
    """Fuehrt eine Seite aus und gibt das Testergebnis zurueck."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(VIEWS / name), default_timeout=timeout)
    return app.run()


@pytest.mark.usefixtures("seeded_app")
class TestSeitenLaufen:
    """Jede Seite muss ohne Ausnahme durchlaufen."""

    @pytest.mark.parametrize(
        "seite",
        ["uebersicht.py", "watchlist.py", "detail.py", "vergleich.py",
         "datenquellen.py", "einstellungen.py"],
    )
    def test_seite_wirft_keine_ausnahme(self, seite):
        ergebnis = run_page(seite)
        assert not ergebnis.exception, [str(e.message) for e in ergebnis.exception]


@pytest.mark.usefixtures("seeded_app")
class TestUebersicht:
    def test_tabelle_enthaelt_alle_titel(self):
        ergebnis = run_page("uebersicht.py")
        tabelle = ergebnis.dataframe[0].value
        assert len(tabelle) == len(TEST_SECURITIES)
        assert set(tabelle["Ticker"]) == {t[0] for t in TEST_SECURITIES}

    def test_nach_gesamtscore_absteigend_sortiert(self):
        scores = [
            wert for wert in run_page("uebersicht.py").dataframe[0].value["Gesamtscore"]
            if wert == wert  # NaN aussortieren
        ]
        assert scores == sorted(scores, reverse=True)

    def test_export_knoepfe_vorhanden(self):
        ergebnis = run_page("uebersicht.py")
        beschriftungen = [k.label for k in ergebnis.button] + [
            k.label for k in getattr(ergebnis, "download_button", [])
        ]
        assert any("CSV" in text for text in beschriftungen)


@pytest.mark.usefixtures("seeded_app")
class TestVergleich:
    def test_zwei_titel_nebeneinander(self):
        ergebnis = run_page("vergleich.py")
        ergebnis.multiselect[0].select("TESTA").select("TESTF").run()
        assert not ergebnis.exception, [str(e.message) for e in ergebnis.exception]

        teilscores = ergebnis.dataframe[0].value
        assert "TESTA" in teilscores.columns
        assert "TESTF" in teilscores.columns
        assert list(teilscores["Teilscore"]) == [
            "Fundamental", "Technik", "Analysten", "Sentiment"
        ]

    def test_titel_ohne_vergleichsgruppe_hat_geringere_abdeckung(self):
        """TESTF ist der einzige Finanzwert - seine sektorrelativen Kennzahlen
        koennen mangels Vergleichsgruppe nicht bewertet werden."""
        ergebnis = run_page("vergleich.py")
        ergebnis.multiselect[0].select("TESTA").select("TESTF").run()
        zeile = ergebnis.dataframe[0].value.iloc[0]
        assert zeile["Teilscore"] == "Fundamental"
        # Format "20-20 / 11-20": TESTA nutzt alle, TESTF deutlich weniger.
        links, rechts = zeile["Abdeckung"].split(" / ")
        assert int(links.split("-")[0]) > int(rechts.split("-")[0])

    def test_ohne_auswahl_kein_fehler(self):
        ergebnis = run_page("vergleich.py")
        assert not ergebnis.exception


@pytest.mark.usefixtures("seeded_app")
class TestSentimentInDerOberflaeche:
    def test_sentiment_teilscore_wird_berechnet(self):
        """Mit eingeordneten Meldungen ist der vierte Teilscore vorhanden."""
        ergebnis = run_page("vergleich.py")
        ergebnis.multiselect[0].select("TESTA").select("TESTB").run()
        assert not ergebnis.exception, [str(e.message) for e in ergebnis.exception]

        teilscores = ergebnis.dataframe[0].value
        sentiment = teilscores[teilscores["Teilscore"] == "Sentiment"].iloc[0]
        assert sentiment["TESTA"] is not None
        assert not (isinstance(sentiment["TESTA"], float) and sentiment["TESTA"] != sentiment["TESTA"])

    def test_sentiment_geht_in_den_gesamtscore_ein(self):
        """Ist Sentiment berechenbar, wird sein Gewicht nicht mehr umverteilt."""
        from aktienmonitor.config import load_config
        from aktienmonitor.providers.fetcher import StockDataService
        from aktienmonitor.scoring.engine import score_snapshot

        service = StockDataService(load_config())
        snapshot = service.get_snapshot("TESTA", cache_only=True)
        bewertung = score_snapshot(snapshot)

        assert snapshot.sentiment["sentiment_balance"].is_available
        assert bewertung.categories["sentiment"].is_available
        assert bewertung.effective_weights["sentiment"] > 0
        assert "Sentiment" not in bewertung.redistributed

    def test_meldungen_behalten_quelle_und_link(self):
        from aktienmonitor.config import load_config
        from aktienmonitor.providers.fetcher import StockDataService

        service = StockDataService(load_config())
        snapshot = service.get_snapshot("TESTA", cache_only=True)
        assert snapshot.news
        for meldung in snapshot.news:
            assert meldung.url.startswith("https://")
            assert meldung.source_name
            # Vorab eingeordnet: Einordnung samt Begruendung liegt vor.
            assert meldung.sentiment in {"positiv", "neutral", "negativ"}
            assert meldung.sentiment_rationale
