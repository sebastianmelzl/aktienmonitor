"""Tests des Datenmodells - hier wird die Regel "keine erfundenen Daten" durchgesetzt."""

from __future__ import annotations

from aktienmonitor.models import (
    MISSING_NOT_PROVIDED,
    MetricSet,
    MetricValue,
    Provenance,
    SecurityProfile,
)


class TestMetricValue:
    def test_nan_wird_zu_fehlend(self):
        metric = MetricValue(key="x", label="X", value=float("nan"))
        assert metric.value is None
        assert not metric.is_available
        assert metric.missing_reason

    def test_unendlich_wird_zu_fehlend(self):
        assert MetricValue(key="x", label="X", value=float("inf")).value is None

    def test_null_bleibt_ein_gueltiger_wert(self):
        metric = MetricValue(key="x", label="X", value=0.0)
        assert metric.is_available
        assert metric.value == 0.0
        assert metric.missing_reason is None

    def test_fehlender_wert_bekommt_immer_eine_begruendung(self):
        assert MetricValue(key="x", label="X").missing_reason == MISSING_NOT_PROVIDED

    def test_berechnete_kennzahl_wird_gekennzeichnet(self):
        metric = MetricValue(
            key="x", label="X", value=1.0, source=Provenance.YFINANCE, is_computed=True
        )
        assert metric.source_label == "berechnet (aus yfinance)"

    def test_uebernommene_kennzahl_nennt_die_quelle(self):
        metric = MetricValue(key="x", label="X", value=1.0, source=Provenance.FINNHUB)
        assert metric.source_label == "Finnhub"

    def test_fehlende_kennzahl_zeigt_keinen_quellenhinweis(self):
        assert MetricValue.missing("x", "X").source_label == "-"

    def test_textkennzahl_gilt_als_vorhanden(self):
        assert MetricValue(key="x", label="X", text="Golden Cross").is_available


class TestMetricSet:
    def test_abdeckung_gegen_handrechnung(self):
        metrics = MetricSet(
            {
                "a": MetricValue(key="a", label="A", value=1.0),
                "b": MetricValue(key="b", label="B", value=2.0),
                "c": MetricValue.missing("c", "C"),
                "d": MetricValue.missing("d", "D"),
            }
        )
        assert metrics.coverage == 0.5
        assert len(metrics.available) == 2
        assert len(metrics.missing) == 2

    def test_leeres_set_hat_abdeckung_null(self):
        assert MetricSet({}).coverage == 0.0

    def test_value_of_liefert_nie_einen_ersatzwert(self):
        metrics = MetricSet({"a": MetricValue.missing("a", "A")})
        assert metrics.value_of("a") is None
        assert metrics.value_of("gibt-es-nicht") is None


class TestSecurityProfile:
    def test_etf_wird_erkannt(self):
        assert SecurityProfile(ticker="SPY", quote_type="ETF").is_fund
        assert SecurityProfile(ticker="X", quote_type="mutualfund").is_fund

    def test_aktie_ist_kein_fonds(self):
        assert not SecurityProfile(ticker="AAPL", quote_type="EQUITY").is_fund
        assert not SecurityProfile(ticker="AAPL").is_fund
