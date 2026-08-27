"""Tests des Kosten- und Steuermodells.

Alle Erwartungswerte sind von Hand nachgerechnet; die Herleitung steht jeweils
am Test.
"""

from __future__ import annotations

import pytest

from aktienmonitor.costs.model import (
    ALLOWANCE_JOINT,
    ALLOWANCE_SINGLE,
    EQUITY_FUND_EXEMPTION,
    KEST_RATE,
    SOLI_RATE,
    BrokerCosts,
    TaxSettings,
    break_even_return,
    cost_warning,
    tax_on_gain,
)


class TestBrokerCosts:
    def test_ordergebuehr_und_spanne(self):
        """1 EUR Pauschale plus halbe Spanne von 10 Basispunkten auf 1.000 EUR.

        1.000 * 0,0010 / 2 = 0,50 -> zusammen 1,50
        """
        costs = BrokerCosts(order_fee=1.0, spread_bps=10.0)
        assert costs.order_cost(1_000.0) == pytest.approx(1.50)

    def test_sparplan_ohne_gebuehr(self):
        costs = BrokerCosts(order_fee=1.0, spread_bps=10.0, savings_plan_fee=0.0)
        # Nur die halbe Spanne bleibt
        assert costs.order_cost(1_000.0, savings_plan=True) == pytest.approx(0.50)

    def test_ohne_betrag_keine_kosten(self):
        assert BrokerCosts().order_cost(0.0) == 0.0
        assert BrokerCosts().order_cost(-5.0) == 0.0

    def test_mehrere_positionen(self):
        """Je Position faellt eine Order an - das ist der Kern des Problems."""
        costs = BrokerCosts(order_fee=1.0, spread_bps=0.0)
        assert costs.total_cost([500.0] * 10) == pytest.approx(10.0)

    def test_kostenanteil_in_prozent(self):
        """10 Positionen zu je 250 EUR: 10 EUR Gebuehr auf 2.500 EUR = 0,4 %."""
        costs = BrokerCosts(order_fee=1.0, spread_bps=0.0)
        assert costs.cost_share([250.0] * 10) == pytest.approx(0.4)

    def test_kostenanteil_ohne_betrag(self):
        assert BrokerCosts().cost_share([]) is None
        assert BrokerCosts().cost_share([0.0]) is None

    def test_kleine_positionen_sind_teuer(self):
        """Der Punkt, auf den es fuer Einsteiger ankommt."""
        costs = BrokerCosts(order_fee=1.0, spread_bps=0.0)
        gross = costs.cost_share([1_000.0])
        klein = costs.cost_share([50.0] * 20)
        assert klein > gross * 10


class TestBreakEven:
    def test_hin_und_rueckweg_zaehlen(self):
        """100 EUR Position, 1 EUR je Order: Kauf und Verkauf = 2 EUR = 2 %."""
        costs = BrokerCosts(order_fee=1.0, spread_bps=0.0)
        assert break_even_return(100.0, costs) == pytest.approx(2.0)

    def test_grosse_position_braucht_weniger(self):
        costs = BrokerCosts(order_fee=1.0, spread_bps=0.0)
        assert break_even_return(10_000.0, costs) == pytest.approx(0.02)

    def test_ohne_betrag_kein_ergebnis(self):
        assert break_even_return(0.0, BrokerCosts()) is None


class TestSteuer:
    def test_effektiver_satz_ohne_kirchensteuer(self):
        """25 % * 1,055 = 26,375 %."""
        assert TaxSettings().effective_rate == pytest.approx(0.26375)

    def test_effektiver_satz_mit_kirchensteuer(self):
        """25 % * (1 + 0,055 + 0,09) = 28,625 %."""
        assert TaxSettings(church_tax_rate=0.09).effective_rate == pytest.approx(0.28625)

    def test_freibetrag_einzeln_und_gemeinsam(self):
        assert TaxSettings().allowance == ALLOWANCE_SINGLE
        assert TaxSettings(joint_assessment=True).allowance == ALLOWANCE_JOINT

    def test_gewinn_unter_freibetrag_bleibt_steuerfrei(self):
        result = tax_on_gain(800.0)
        assert result.tax == pytest.approx(0.0)
        assert result.covered_by_allowance == pytest.approx(800.0)
        assert result.net_gain == pytest.approx(800.0)

    def test_gewinn_ueber_freibetrag(self):
        """1.500 EUR Gewinn, 1.000 EUR frei -> 500 EUR * 26,375 % = 131,88."""
        result = tax_on_gain(1_500.0)
        assert result.taxable == pytest.approx(500.0)
        assert result.tax == pytest.approx(131.875)
        assert result.net_gain == pytest.approx(1_368.125)

    def test_bereits_verbrauchter_freibetrag(self):
        """600 EUR verbraucht -> nur noch 400 EUR frei von 1.000 EUR Gewinn."""
        result = tax_on_gain(1_000.0, TaxSettings(allowance_used=600.0))
        assert result.covered_by_allowance == pytest.approx(400.0)
        assert result.taxable == pytest.approx(600.0)

    def test_teilfreistellung_bei_aktienfonds(self):
        """1.000 EUR Gewinn, 30 % steuerfrei -> 700 EUR, davon 1.000 frei -> keine Steuer."""
        result = tax_on_gain(1_000.0, TaxSettings(equity_fund=True))
        assert result.exempt_by_fund_rule == pytest.approx(300.0)
        assert result.tax == pytest.approx(0.0)

    def test_teilfreistellung_wirkt_auch_ueber_dem_freibetrag(self):
        """5.000 EUR Gewinn im ETF: 30 % frei -> 3.500; minus 1.000 Freibetrag
        -> 2.500 steuerpflichtig * 26,375 % = 659,375."""
        result = tax_on_gain(5_000.0, TaxSettings(equity_fund=True))
        assert result.exempt_by_fund_rule == pytest.approx(1_500.0)
        assert result.taxable == pytest.approx(2_500.0)
        assert result.tax == pytest.approx(659.375)

    def test_einzelaktie_ohne_teilfreistellung(self):
        """Dieselbe Summe in einer Einzelaktie wird hoeher besteuert."""
        etf = tax_on_gain(5_000.0, TaxSettings(equity_fund=True))
        aktie = tax_on_gain(5_000.0, TaxSettings(equity_fund=False))
        assert aktie.tax > etf.tax
        assert etf.exempt_by_fund_rule == pytest.approx(5_000.0 * EQUITY_FUND_EXEMPTION)

    def test_verlust_wird_nicht_besteuert(self):
        result = tax_on_gain(-500.0)
        assert result.tax == 0.0
        assert result.net_gain == pytest.approx(-500.0)

    def test_belastung_in_prozent(self):
        result = tax_on_gain(2_000.0)
        # 1.000 steuerpflichtig * 26,375 % = 263,75 auf 2.000 Gewinn = 13,19 %
        assert result.effective_burden == pytest.approx(13.1875, abs=0.01)

    def test_ohne_gewinn_keine_belastungsquote(self):
        assert tax_on_gain(0.0).effective_burden is None

    def test_gesetzliche_saetze_sind_hinterlegt(self):
        assert KEST_RATE == 0.25
        assert SOLI_RATE == 0.055
        assert EQUITY_FUND_EXEMPTION == 0.30


class TestKostenwarnung:
    def test_viele_kleine_positionen_werden_gemeldet(self):
        """500 EUR auf 10 Positionen: 10 EUR Gebuehr = 2 % - das muss auffallen."""
        meldung = cost_warning(500.0, 10, BrokerCosts(order_fee=1.0, spread_bps=0.0))
        assert meldung is not None
        assert "2,00 %" in meldung or "2.00 %" in meldung

    def test_grosser_betrag_ohne_meldung(self):
        assert cost_warning(50_000.0, 10, BrokerCosts(order_fee=1.0, spread_bps=0.0)) is None

    def test_randfaelle(self):
        assert cost_warning(0.0, 5, BrokerCosts()) is None
        assert cost_warning(1_000.0, 0, BrokerCosts()) is None
