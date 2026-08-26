"""Tests der Analysten-Kennzahlen."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aktienmonitor.metrics.analyst import (
    _consensus_from_counts,
    compute_analyst_metrics,
    frame_records,
)
from aktienmonitor.models import Provenance


def _recommendations_payload(strong_buy=10, buy=8, hold=4, sell=1, strong_sell=0):
    return {
        "columns": ["period", "strongBuy", "buy", "hold", "sell", "strongSell"],
        "index": [],
        "rows": {"0": ["0m", strong_buy, buy, hold, sell, strong_sell]},
    }


class TestFrameRecords:
    def test_wandelt_zeilen_in_datensaetze(self):
        records = frame_records(_recommendations_payload())
        assert records[0]["period"] == "0m"
        assert records[0]["strongBuy"] == 10
        assert records[0]["_index"] == "0"

    def test_leeres_payload_ergibt_leere_liste(self):
        assert frame_records(None) == []
        assert frame_records({"rows": {}}) == []


class TestConsensus:
    def test_note_gegen_handrechnung(self):
        # (10*1 + 8*2 + 4*3 + 1*4 + 0*5) / 23 = 42/23 = 1.826
        label, count, mean = _consensus_from_counts(
            {"strongBuy": 10, "buy": 8, "hold": 4, "sell": 1, "strongSell": 0}
        )
        assert count == 23
        assert mean == pytest.approx(1.826, abs=0.01)
        assert label == "positiv"

    def test_ohne_analysten_bleibt_alles_none(self):
        assert _consensus_from_counts({}) == (None, None, None)

    @pytest.mark.parametrize(
        "counts,erwartet",
        [
            ({"strongBuy": 10}, "sehr positiv"),
            ({"buy": 10}, "positiv"),
            ({"hold": 10}, "neutral"),
            ({"sell": 10}, "negativ"),
            ({"strongSell": 10}, "sehr negativ"),
        ],
    )
    def test_einordnung_ist_neutral_formuliert(self, counts, erwartet):
        label, _, _ = _consensus_from_counts(counts)
        assert label == erwartet
        # Bewusst keine Handlungsbegriffe in der Oberflaeche.
        assert "kauf" not in label.lower()
        assert "verkauf" not in label.lower()


class TestComputeAnalystMetrics:
    def test_konsens_aus_zaehlungen(self):
        metrics = compute_analyst_metrics(
            analyst_payload={"recommendations": _recommendations_payload()}
        )
        assert metrics["consensus_rating"].text == "positiv"
        assert metrics["analyst_count"].value == 23
        assert metrics["consensus_score"].value == pytest.approx(1.826, abs=0.01)

    def test_kursziel_abstand_gegen_handrechnung(self):
        metrics = compute_analyst_metrics(
            analyst_payload={"price_targets": {"mean": 120.0}}, current_price=100.0
        )
        assert metrics["target_mean"].value == pytest.approx(120.0)
        assert metrics["target_upside"].value == pytest.approx(20.0)
        assert metrics["target_upside"].is_computed

    def test_kursziel_ohne_kurs_bleibt_ohne_abstand(self):
        metrics = compute_analyst_metrics(
            analyst_payload={"price_targets": {"mean": 120.0}}, current_price=None
        )
        assert metrics["target_mean"].is_available
        assert not metrics["target_upside"].is_available

    def test_revisionssaldo(self):
        payload = {
            "eps_revisions": {
                "columns": ["upLast7days", "upLast30days", "downLast7days", "downLast30days"],
                "index": [],
                "rows": {"0y": [2, 8, 0, 2]},
            }
        }
        metrics = compute_analyst_metrics(analyst_payload=payload)
        assert metrics["revisions_up_30d"].value == 8
        assert metrics["revisions_down_30d"].value == 2
        # (8 - 2) / 10 = 60 %
        assert metrics["revision_balance"].value == pytest.approx(60.0)

    def test_revisionssaldo_ohne_revisionen_bleibt_na(self):
        payload = {
            "eps_revisions": {
                "columns": ["upLast30days", "downLast30days"],
                "index": [],
                "rows": {"0y": [0, 0]},
            }
        }
        metrics = compute_analyst_metrics(analyst_payload=payload)
        # Null Auf- und null Abwaertsrevisionen ergeben keinen Saldo von 0,
        # sondern gar keinen Saldo.
        assert not metrics["revision_balance"].is_available

    def test_earnings_surprises_nur_aus_der_vergangenheit(self):
        past = (datetime.now(UTC) - timedelta(days=30)).replace(tzinfo=None)
        future = (datetime.now(UTC) + timedelta(days=30)).replace(tzinfo=None)
        payload = {
            "earnings_dates": {
                "columns": ["EPS Estimate", "Reported EPS", "Surprise(%)"],
                "index": [],
                "rows": {
                    past.isoformat(): [1.0, 1.1, 10.0],
                    future.isoformat(): [1.2, None, None],
                },
            }
        }
        metrics = compute_analyst_metrics(analyst_payload=payload)
        assert metrics["earnings_surprise_last"].value == pytest.approx(10.0)

    def test_naechster_termin_aus_dem_kalender(self):
        future = (datetime.now(UTC) + timedelta(days=20)).replace(tzinfo=None)
        metrics = compute_analyst_metrics(
            analyst_payload={"calendar": {"Earnings Date": [future.date().isoformat()]}}
        )
        assert metrics["next_earnings_date"].text == future.date().isoformat()

    def test_finnhub_als_rueckfallebene_fuer_kursziel(self):
        metrics = compute_analyst_metrics(
            analyst_payload={}, current_price=100.0, finnhub_price_target={"targetMean": 150.0}
        )
        assert metrics["target_mean"].value == pytest.approx(150.0)
        assert metrics["target_mean"].source is Provenance.FINNHUB

    def test_ohne_daten_ist_alles_na(self):
        metrics = compute_analyst_metrics(analyst_payload=None)
        assert metrics.coverage == 0.0
        assert all(m.missing_reason for m in metrics)
