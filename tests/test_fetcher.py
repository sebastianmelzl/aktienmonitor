"""Tests der Datenzusammenfuehrung (ohne Netzwerkzugriff)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aktienmonitor.models import Provenance, SecurityProfile
from aktienmonitor.providers.fetcher import (
    DataFreshness,
    StockSnapshot,
    _as_float,
    _parse_finnhub_news,
    _parse_yfinance_news,
)


class TestAsFloat:
    @pytest.mark.parametrize("wert,erwartet", [(1, 1.0), (2.5, 2.5), (0, 0.0)])
    def test_zahlen(self, wert, erwartet):
        assert _as_float(wert) == erwartet

    @pytest.mark.parametrize("wert", [None, "12", True, False, [], {}])
    def test_nicht_zahlen_liefern_none(self, wert):
        # True ist in Python ein int - darf aber nie als Kurs durchgehen.
        assert _as_float(wert) is None


class TestFinnhubNews:
    def test_meldung_wird_gelesen(self):
        stamp = int(datetime(2026, 5, 1, 12, 0, tzinfo=UTC).timestamp())
        items = _parse_finnhub_news(
            [
                {
                    "headline": "Quartalszahlen vorgelegt",
                    "url": "https://example.com/a",
                    "source": "Reuters",
                    "datetime": stamp,
                    "summary": "Zusammenfassung",
                }
            ]
        )
        assert len(items) == 1
        assert items[0].headline == "Quartalszahlen vorgelegt"
        assert items[0].source_name == "Reuters"
        assert items[0].url == "https://example.com/a"
        # Ohne Einordnung bleibt das Sentiment leer - es wird nichts geraten.
        assert items[0].sentiment is None

    @pytest.mark.parametrize(
        "eintrag",
        [
            {"url": "https://example.com/a", "datetime": 1},  # keine Schlagzeile
            {"headline": "Titel", "datetime": 1},  # kein Link
            {"headline": "Titel", "url": "https://example.com/a"},  # kein Datum
            {"headline": "Titel", "url": "https://example.com/a", "datetime": "kaputt"},
        ],
    )
    def test_unvollstaendige_meldungen_werden_verworfen(self, eintrag):
        # Eine Meldung ohne Quelle oder Datum waere nicht nachpruefbar.
        assert _parse_finnhub_news([eintrag]) == []


class TestYfinanceNews:
    def test_neues_format_mit_content(self):
        items = _parse_yfinance_news(
            [
                {
                    "content": {
                        "title": "Neue Produktlinie",
                        "pubDate": "2026-05-01T12:00:00Z",
                        "provider": {"displayName": "Handelsblatt"},
                        "canonicalUrl": {"url": "https://example.com/b"},
                        "summary": "Kurzfassung",
                    }
                }
            ]
        )
        assert len(items) == 1
        assert items[0].source_name == "Handelsblatt"
        assert items[0].url == "https://example.com/b"

    def test_altes_flaches_format(self):
        items = _parse_yfinance_news(
            [
                {
                    "title": "Alte Meldung",
                    "link": "https://example.com/c",
                    "publisher": "Yahoo",
                    "providerPublishTime": int(datetime(2026, 4, 1, tzinfo=UTC).timestamp()),
                }
            ]
        )
        assert len(items) == 1
        assert items[0].url == "https://example.com/c"

    def test_meldung_ohne_link_wird_verworfen(self):
        assert _parse_yfinance_news([{"content": {"title": "Ohne Link"}}]) == []


class TestDataFreshness:
    @pytest.mark.parametrize(
        "alter,erwartet",
        [
            (timedelta(seconds=10), "gerade eben"),
            (timedelta(minutes=30), "vor 30 Min."),
            (timedelta(hours=5), "vor 5 Std."),
            (timedelta(days=3), "vor 3 Tg."),
        ],
    )
    def test_altersanzeige(self, alter, erwartet):
        item = DataFreshness("Kurs", Provenance.YFINANCE, datetime.now(UTC) - alter, True)
        assert item.age_text == erwartet

    def test_nicht_abgerufen(self):
        assert DataFreshness("Kurs", Provenance.YFINANCE, None, False).age_text == "nicht abgerufen"


class TestStockSnapshot:
    def _snapshot(self, **kwargs) -> StockSnapshot:
        return StockSnapshot(ticker="TEST", profile=SecurityProfile(ticker="TEST"), **kwargs)

    def test_veraenderung_gegen_handrechnung(self):
        snapshot = self._snapshot(price=110.0, previous_close=100.0)
        assert snapshot.change_percent == pytest.approx(10.0)

    @pytest.mark.parametrize(
        "kurs,vortag", [(None, 100.0), (110.0, None), (110.0, 0.0)]
    )
    def test_veraenderung_ohne_basis_bleibt_none(self, kurs, vortag):
        assert self._snapshot(price=kurs, previous_close=vortag).change_percent is None

    def test_leerer_snapshot_hat_keine_daten(self):
        assert not self._snapshot().has_any_data

    def test_snapshot_mit_kurs_hat_daten(self):
        assert self._snapshot(price=100.0).has_any_data

    def test_aeltester_abruf_wird_ermittelt(self):
        jetzt = datetime.now(UTC)
        snapshot = self._snapshot(
            freshness=[
                DataFreshness("Kurs", Provenance.YFINANCE, jetzt, False),
                DataFreshness("Abschluesse", Provenance.YFINANCE, jetzt - timedelta(days=2), True),
                DataFreshness("Analysten", Provenance.YFINANCE, None, False),
            ]
        )
        assert snapshot.oldest_fetch == jetzt - timedelta(days=2)

    def test_ohne_zeitstempel_kein_aeltester_abruf(self):
        assert self._snapshot().oldest_fetch is None
