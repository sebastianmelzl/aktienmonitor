"""Tests von Cache, Watchlist und Einstellungen."""

from __future__ import annotations

import time

import pytest

from aktienmonitor.storage.cache import Cache, build_key
from aktienmonitor.storage.call_log import CallLog
from aktienmonitor.storage.db import Database
from aktienmonitor.storage.settings_store import SettingsStore
from aktienmonitor.storage.watchlist import Watchlist, normalise_ticker


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


class TestCache:
    def test_eintrag_wird_gespeichert_und_gelesen(self, db):
        cache = Cache(db)
        cache.set("k", {"a": 1}, source="yfinance", data_kind="quote", ttl_seconds=60)
        entry = cache.get("k")
        assert entry.payload == {"a": 1}
        assert entry.source == "yfinance"
        assert entry.age_seconds < 5

    def test_abgelaufener_eintrag_wird_nicht_geliefert(self, db):
        cache = Cache(db)
        cache.set("k", {"a": 1}, source="yfinance", data_kind="quote", ttl_seconds=0)
        time.sleep(0.01)
        assert cache.get("k") is None

    def test_abgelaufener_eintrag_als_rueckfallebene(self, db):
        cache = Cache(db)
        cache.set("k", {"a": 1}, source="yfinance", data_kind="quote", ttl_seconds=0)
        time.sleep(0.01)
        entry = cache.get("k", allow_stale=True)
        assert entry is not None
        assert entry.is_expired

    def test_ueberschreiben_aktualisiert_den_zeitstempel(self, db):
        cache = Cache(db)
        first = cache.set("k", {"a": 1}, source="yfinance", data_kind="quote", ttl_seconds=60)
        time.sleep(0.01)
        second = cache.set("k", {"a": 2}, source="yfinance", data_kind="quote", ttl_seconds=60)
        assert second.fetched_at > first.fetched_at
        assert cache.get("k").payload == {"a": 2}

    def test_invalidierung_je_titel(self, db):
        cache = Cache(db)
        cache.set("a", 1, source="yfinance", data_kind="quote", ttl_seconds=60, ticker="AAPL")
        cache.set("b", 2, source="yfinance", data_kind="quote", ttl_seconds=60, ticker="MSFT")
        assert cache.invalidate_ticker("AAPL") == 1
        assert cache.get("a") is None
        assert cache.get("b") is not None

    def test_schluessel_ist_stabil_und_unterscheidend(self):
        assert build_key("yf", "info", "aapl") == build_key("yf", "info", "AAPL")
        assert build_key("yf", "info", "AAPL") != build_key("yf", "info", "MSFT")
        assert build_key("yf", "hist", "AAPL", "1y") != build_key("yf", "hist", "AAPL", "5y")


class TestCallLog:
    def test_zugriffe_werden_protokolliert(self, db):
        log = CallLog(db)
        log.record(source="yfinance", endpoint="info", ticker="AAPL", cache_hit=False, status="ok")
        log.record(source="yfinance", endpoint="info", ticker="AAPL", cache_hit=True, status="ok")
        entries = log.recent()
        assert len(entries) == 2
        summary = log.summary()
        assert summary["total"] == 2
        assert summary["cache_hits"] == 1


class TestNormaliseTicker:
    @pytest.mark.parametrize(
        "eingabe,erwartet",
        [
            ("aapl", "AAPL"),
            ("  msft  ", "MSFT"),
            ("sap.de", "SAP.DE"),
            ("brk-b", "BRK-B"),
            ("7203.T", "7203.T"),
        ],
    )
    def test_gueltige_ticker(self, eingabe, erwartet):
        assert normalise_ticker(eingabe) == erwartet

    @pytest.mark.parametrize("eingabe", ["", "   ", "!!!", "a" * 25, "AA PL;DROP"])
    def test_ungueltige_ticker(self, eingabe):
        assert normalise_ticker(eingabe) is None


class TestWatchlist:
    def test_hinzufuegen_und_entfernen(self, db):
        watchlist = Watchlist(db)
        watchlist.add("aapl")
        assert watchlist.tickers() == ["AAPL"]
        assert watchlist.remove("AAPL")
        assert watchlist.tickers() == []

    def test_doppeltes_hinzufuegen_erzeugt_keinen_zweiten_eintrag(self, db):
        watchlist = Watchlist(db)
        watchlist.add("AAPL")
        watchlist.add("AAPL", display_name="Apple Inc.")
        assert watchlist.tickers() == ["AAPL"]
        assert watchlist.all()[0].display_name == "Apple Inc."

    def test_ungueltiger_ticker_wird_abgelehnt(self, db):
        with pytest.raises(ValueError):
            Watchlist(db).add("!!!")

    def test_gruppen_zuordnung(self, db):
        watchlist = Watchlist(db)
        watchlist.add("AAPL")
        watchlist.assign("AAPL", "Tech")
        watchlist.assign("AAPL", "Dividende")
        assert set(watchlist.all()[0].groups) == {"Tech", "Dividende"}
        assert watchlist.tickers(group="Tech") == ["AAPL"]

    def test_set_groups_ersetzt_die_zuordnung(self, db):
        watchlist = Watchlist(db)
        watchlist.add("AAPL")
        watchlist.set_groups("AAPL", ["Tech", "Dividende"])
        watchlist.set_groups("AAPL", ["Tech"])
        assert watchlist.all()[0].groups == ("Tech",)

    def test_entfernen_loescht_die_gruppenzuordnung(self, db):
        watchlist = Watchlist(db)
        watchlist.add("AAPL")
        watchlist.assign("AAPL", "Tech")
        watchlist.remove("AAPL")
        assert watchlist.tickers(group="Tech") == []


class TestCsvImport:
    def test_import_mit_kopfzeile(self, db):
        watchlist = Watchlist(db)
        accepted, rejected = watchlist.import_csv(
            "ticker,name,gruppe\nAAPL,Apple,Tech\nMSFT,Microsoft,Tech\n"
        )
        assert accepted == ["AAPL", "MSFT"]
        assert rejected == []
        assert watchlist.tickers(group="Tech") == ["AAPL", "MSFT"]

    def test_import_mit_semikolon(self, db):
        accepted, _ = Watchlist(db).import_csv("ticker;name\nSAP.DE;SAP SE\n")
        assert accepted == ["SAP.DE"]

    def test_import_ohne_kopfzeile(self, db):
        accepted, _ = Watchlist(db).import_csv("AAPL\nMSFT\n")
        assert accepted == ["AAPL", "MSFT"]

    def test_ungueltige_zeilen_werden_gemeldet_nicht_verschluckt(self, db):
        accepted, rejected = Watchlist(db).import_csv("ticker\nAAPL\n!!!\n\nMSFT\n")
        assert accepted == ["AAPL", "MSFT"]
        assert rejected == ["!!!"]

    def test_leere_datei(self, db):
        assert Watchlist(db).import_csv("") == ([], [])


class TestSettingsStore:
    def test_speichern_und_lesen(self, db):
        store = SettingsStore(db)
        store.set("weights", {"fundamental": 0.4})
        assert store.get("weights") == {"fundamental": 0.4}

    def test_unbekannter_schluessel_liefert_default(self, db):
        assert SettingsStore(db).get("gibt-es-nicht", "fallback") == "fallback"

    def test_ueberschreiben(self, db):
        store = SettingsStore(db)
        store.set("k", 1)
        store.set("k", 2)
        assert store.get("k") == 2
