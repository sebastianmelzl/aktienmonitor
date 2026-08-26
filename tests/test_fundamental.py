"""Tests der fundamentalen Kennzahlen gegen handgerechnete Werte."""

from __future__ import annotations

import pytest

from aktienmonitor.metrics.fundamental import (
    _dividend_history,
    _first,
    _pick,
    cagr,
    compute_fundamental_metrics,
    safe_div,
)
from aktienmonitor.metrics.statements import Statements
from aktienmonitor.models import (
    MISSING_NOT_APPLICABLE,
    Provenance,
    SecurityProfile,
)


class TestSafeDiv:
    def test_normale_division(self):
        assert safe_div(10.0, 4.0) == pytest.approx(2.5)

    @pytest.mark.parametrize("numerator,denominator", [(None, 2.0), (2.0, None), (2.0, 0.0)])
    def test_undefinierte_faelle_liefern_none(self, numerator, denominator):
        assert safe_div(numerator, denominator) is None


class TestPickUndFirst:
    def test_null_ist_ein_wert_kein_fehlen(self):
        # Der haeufigste stille Fehler: 0.0 per "or" als fehlend behandeln.
        value, source = _pick((0.0, Provenance.YFINANCE), (42.0, Provenance.FINNHUB))
        assert value == 0.0
        assert source is Provenance.YFINANCE

    def test_faellt_auf_zweite_quelle_zurueck(self):
        value, source = _pick((None, Provenance.YFINANCE), (42.0, Provenance.FINNHUB))
        assert value == 42.0
        assert source is Provenance.FINNHUB

    def test_first_ueberspringt_nur_none(self):
        assert _first(None, 0.0, 5.0) == 0.0


class TestCagr:
    def test_gegen_handrechnung(self, income_statement):
        series = Statements({"income_annual": income_statement}).income.series("Total Revenue")
        # Umsatz waechst konstruktionsgemaess mit exakt 10 % pro Jahr.
        assert cagr(series, 1) == pytest.approx(10.0, abs=0.01)
        assert cagr(series, 3) == pytest.approx(10.0, abs=0.01)
        assert cagr(series, 5) == pytest.approx(10.0, abs=0.01)

    def test_negativer_ausgangswert_ist_nicht_definiert(self, income_statement):
        payload = dict(income_statement)
        payload["rows"] = dict(income_statement["rows"])
        payload["rows"]["Net Income"] = [100.0, -50.0, 80.0, -20.0, 60.0, 40.0]
        series = Statements({"income_annual": payload}).income.series("Net Income")
        # Aus einem Verlust heraus ist eine Wachstumsrate mathematisch sinnlos.
        assert cagr(series, 5) is None

    def test_fehlendes_vergleichsjahr_liefert_none(self, income_statement):
        series = Statements({"income_annual": income_statement}).income.series("Total Revenue")
        # Es gibt nur sechs Jahre Historie - zehn Jahre sind nicht abgedeckt.
        assert cagr(series, 10) is None

    def test_zu_kurze_reihe_liefert_none(self):
        assert cagr([], 1) is None


class TestDividendHistory:
    def test_zaehlt_jahre_und_steigerungsserie(self):
        dividends = {
            "2020-03-01T00:00:00": 1.00,
            "2021-03-01T00:00:00": 1.10,
            "2022-03-01T00:00:00": 1.20,
            "2023-03-01T00:00:00": 1.15,
            "2024-03-01T00:00:00": 1.30,
        }
        years, streak = _dividend_history(dividends)
        assert years == 5
        # 2023 war ein Rueckgang, danach nur noch ein Anstieg (2023 -> 2024).
        assert streak == 1

    def test_ohne_dividenden_bleibt_alles_none(self):
        assert _dividend_history({}) == (None, None)


class TestComputeFundamentalMetrics:
    @pytest.fixture
    def info(self):
        return {
            "marketCap": 20_000.0,
            "sharesOutstanding": 95.0,
            "trailingPE": 18.0,
            "forwardPE": 15.0,
            "priceToBook": 3.0,
            "currentRatio": 1.5,
            "dividendYield": 2.5,
            "payoutRatio": 0.4,
            "quoteType": "EQUITY",
        }

    def test_margen_werden_aus_der_guv_berechnet(self, statements_payload):
        metrics = compute_fundamental_metrics(info={}, statements_payload=statements_payload)
        # Bruttomarge 644.204 / 1610.51 = 40 %
        assert metrics["gross_margin"].value == pytest.approx(40.0, abs=0.01)
        # Operative Marge 322.102 / 1610.51 = 20 %
        assert metrics["operating_margin"].value == pytest.approx(20.0, abs=0.01)
        # Nettomarge 241.58 / 1610.51 = 15 %
        assert metrics["net_margin"].value == pytest.approx(15.0, abs=0.01)
        assert metrics["gross_margin"].is_computed

    def test_gelieferte_marge_hat_vorrang_und_gilt_als_nicht_berechnet(self, statements_payload):
        metrics = compute_fundamental_metrics(
            info={"grossMargins": 0.55}, statements_payload=statements_payload
        )
        assert metrics["gross_margin"].value == pytest.approx(55.0)
        assert not metrics["gross_margin"].is_computed
        assert metrics["gross_margin"].source is Provenance.YFINANCE

    def test_eigenkapitalquote(self, statements_payload):
        metrics = compute_fundamental_metrics(info={}, statements_payload=statements_payload)
        # 2000 / 5000 = 40 %
        assert metrics["equity_ratio"].value == pytest.approx(40.0)
        assert metrics["equity_ratio"].is_computed

    def test_current_ratio_aus_der_bilanz(self, statements_payload):
        metrics = compute_fundamental_metrics(info={}, statements_payload=statements_payload)
        # 1800 / 1200 = 1.5
        assert metrics["current_ratio"].value == pytest.approx(1.5)

    def test_free_cashflow_aus_operativem_cashflow_und_investitionen(self, statements_payload):
        metrics = compute_fundamental_metrics(info={}, statements_payload=statements_payload)
        # 400 + (-150) = 250
        assert metrics["free_cash_flow"].value == pytest.approx(250.0)
        assert metrics["free_cash_flow"].is_computed
        # FCF-Marge 250 / 1610.51 = 15.52 %
        assert metrics["fcf_margin"].value == pytest.approx(15.52, abs=0.01)

    def test_netto_verschuldung_zu_ebitda(self, statements_payload):
        metrics = compute_fundamental_metrics(info={}, statements_payload=statements_payload)
        # (1500 - 500) / 402.6 = 2.484
        assert metrics["net_debt_ebitda"].value == pytest.approx(2.484, abs=0.01)

    def test_roic_gegen_handrechnung(self, statements_payload):
        metrics = compute_fundamental_metrics(info={}, statements_payload=statements_payload)
        # Steuerquote 75/300 = 25 %; NOPAT = 322.102 * 0.75 = 241.58
        # ROIC = 241.58 / 3500 = 6.902 %
        assert metrics["roic"].value == pytest.approx(6.902, abs=0.01)
        assert metrics["roic"].is_computed
        assert "berechnet" in metrics["roic"].source_label

    def test_aktienzahl_sinkt_bei_rueckkaeufen(self, statements_payload):
        metrics = compute_fundamental_metrics(info={}, statements_payload=statements_payload)
        # 95 / 97 - 1 = -2.06 %
        assert metrics["share_count_change_1y"].value == pytest.approx(-2.062, abs=0.01)

    def test_wachstumsraten(self, statements_payload):
        metrics = compute_fundamental_metrics(info={}, statements_payload=statements_payload)
        for key in ("revenue_growth_1y", "revenue_growth_3y", "revenue_growth_5y"):
            assert metrics[key].value == pytest.approx(10.0, abs=0.05)

    def test_peg_wird_aus_kgv_und_wachstum_berechnet(self):
        metrics = compute_fundamental_metrics(
            info={"trailingPE": 20.0, "earningsGrowth": 0.10}, statements_payload=None
        )
        # 20 / 10 = 2.0
        assert metrics["peg"].value == pytest.approx(2.0)
        assert metrics["peg"].is_computed

    def test_peg_bei_negativem_wachstum_ist_nicht_definiert(self):
        metrics = compute_fundamental_metrics(
            info={"trailingPE": 20.0, "earningsGrowth": -0.05}, statements_payload=None
        )
        assert not metrics["peg"].is_available
        assert metrics["peg"].missing_reason

    def test_fehlende_daten_liefern_nie_ersatzwerte(self):
        metrics = compute_fundamental_metrics(info={}, statements_payload=None)
        assert metrics.coverage == 0.0
        for metric in metrics:
            assert metric.value is None
            assert metric.missing_reason is not None

    def test_etf_kennzahlen_gelten_als_nicht_anwendbar(self):
        profile = SecurityProfile(ticker="SPY", quote_type="ETF")
        metrics = compute_fundamental_metrics(
            info={"quoteType": "ETF"}, statements_payload=None, profile=profile
        )
        assert metrics["roe"].missing_reason == MISSING_NOT_APPLICABLE
        assert metrics["gross_margin"].missing_reason == MISSING_NOT_APPLICABLE

    def test_abdeckung_wird_korrekt_gezaehlt(self, info, statements_payload):
        metrics = compute_fundamental_metrics(info=info, statements_payload=statements_payload)
        assert 0.0 < metrics.coverage <= 1.0
        assert len(metrics.available) + len(metrics.missing) == len(metrics)

    def test_finnhub_dient_als_rueckfallebene(self):
        metrics = compute_fundamental_metrics(
            info={}, statements_payload=None, finnhub_metric={"peTTM": 22.5}
        )
        assert metrics["pe_trailing"].value == pytest.approx(22.5)
        assert metrics["pe_trailing"].source is Provenance.FINNHUB
