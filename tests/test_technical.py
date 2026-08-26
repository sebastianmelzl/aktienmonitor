"""Tests der technischen Indikatoren gegen handgerechnete Werte."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from aktienmonitor.metrics.technical import (
    annualised_volatility,
    atr,
    bars_to_frame,
    bollinger,
    compute_technical_metrics,
    cross_signal,
    distance_to_extreme,
    macd,
    momentum,
    rsi,
    sma,
    volume_trend,
    wilder_smooth,
)

from .conftest import WILDER_CLOSES, make_bars


class TestSma:
    def test_mittelwert_der_letzten_werte(self):
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        # Mittel der letzten drei: (3+4+5)/3 = 4
        assert sma(series, 3) == pytest.approx(4.0)

    def test_zu_kurze_reihe_liefert_none(self):
        assert sma(pd.Series([1.0, 2.0]), 3) is None


class TestWilderSmoothing:
    def test_saat_ist_einfacher_mittelwert(self):
        series = pd.Series([2.0, 4.0, 6.0, 8.0])
        smoothed = wilder_smooth(series, 2)
        # Erste beiden Werte: Mittel = 3.0
        assert smoothed.iloc[1] == pytest.approx(3.0)
        # Danach rekursiv: (3.0 * 1 + 6.0) / 2 = 4.5
        assert smoothed.iloc[2] == pytest.approx(4.5)
        # (4.5 * 1 + 8.0) / 2 = 6.25
        assert smoothed.iloc[3] == pytest.approx(6.25)

    def test_zu_kurze_reihe_liefert_none(self):
        assert wilder_smooth(pd.Series([1.0]), 5) is None


class TestRsi:
    def test_gegen_handrechnung(self):
        """Nachgerechnet auf Wilders Kursreihe (14 Veraenderungen).

        Summe der Gewinne 3.34 -> Schnitt 0.238571
        Summe der Verluste 1.40 -> Schnitt 0.100000
        RS = 2.385714 -> RSI = 100 - 100/3.385714 = 70.4641
        """
        assert rsi(pd.Series(WILDER_CLOSES), 14) == pytest.approx(70.4641, abs=1e-3)

    def test_reine_aufwaertsbewegung_ergibt_100(self):
        assert rsi(pd.Series([float(i) for i in range(1, 30)]), 14) == pytest.approx(100.0)

    def test_reine_abwaertsbewegung_ergibt_0(self):
        assert rsi(pd.Series([float(i) for i in range(30, 1, -1)]), 14) == pytest.approx(0.0)

    def test_konstante_reihe_ergibt_50(self):
        # Weder Gewinne noch Verluste: neutraler Wert statt Division durch null.
        assert rsi(pd.Series([10.0] * 30), 14) == pytest.approx(50.0)

    def test_zu_kurze_reihe_liefert_none(self):
        assert rsi(pd.Series([1.0] * 10), 14) is None


class TestMacd:
    def test_linie_ist_differenz_der_ema(self):
        closes = pd.Series([float(100 + i) for i in range(60)])
        result = macd(closes)
        fast = closes.ewm(span=12, adjust=False).mean().iloc[-1]
        slow = closes.ewm(span=26, adjust=False).mean().iloc[-1]
        assert result.macd == pytest.approx(fast - slow)
        assert result.histogram == pytest.approx(result.macd - result.signal)

    def test_steigender_trend_ergibt_positiven_macd(self):
        result = macd(pd.Series([float(100 + i) for i in range(60)]))
        assert result.macd > 0

    def test_zu_kurze_reihe_liefert_none(self):
        assert macd(pd.Series([1.0] * 20)) is None


class TestBollinger:
    def test_gegen_handrechnung(self):
        # Konstante Reihe: Standardabweichung null, alle Baender fallen zusammen.
        result = bollinger(pd.Series([10.0] * 25), window=20)
        assert result.middle == pytest.approx(10.0)
        assert result.upper == pytest.approx(10.0)
        assert result.lower == pytest.approx(10.0)
        # Ohne Bandbreite ist %B nicht definiert - und wird nicht geraten.
        assert result.percent_b is None

    def test_percent_b_in_der_bandmitte(self):
        values = [float(i) for i in range(1, 21)]
        result = bollinger(pd.Series(values), window=20)
        assert 0.0 <= result.percent_b <= 1.0

    def test_standardabweichung_als_populationsgroesse(self):
        values = pd.Series([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
        result = bollinger(values, window=8, num_std=1.0)
        # Populationsstandardabweichung dieser Reihe ist exakt 2.0
        assert result.upper - result.middle == pytest.approx(2.0)


class TestAtr:
    def test_konstante_spanne(self):
        # Hoch/Tief liegen konstant +-1 um den Schlusskurs -> True Range = 2.0
        frame = bars_to_frame(make_bars([10.0] * 30))
        assert atr(frame, 14) == pytest.approx(2.0)

    def test_zu_kurze_reihe_liefert_none(self):
        assert atr(bars_to_frame(make_bars([10.0] * 5)), 14) is None


class TestVolatility:
    def test_konstante_kurse_ergeben_null(self):
        assert annualised_volatility(pd.Series([50.0] * 60)) == pytest.approx(0.0)

    def test_zu_kurze_reihe_liefert_none(self):
        assert annualised_volatility(pd.Series([50.0] * 10)) is None


class TestMomentum:
    def test_gegen_handrechnung(self):
        # 22 Werte: Index -22 ist der Ausgangspunkt fuer einen Monat (21 Tage).
        closes = pd.Series([100.0] * 21 + [110.0])
        assert momentum(closes, 1) == pytest.approx(10.0)

    def test_zu_kurze_reihe_liefert_none(self):
        assert momentum(pd.Series([100.0] * 10), 3) is None


class TestDistanceToExtreme:
    def test_abstand_zum_hoch_ist_negativ(self):
        closes = pd.Series([100.0, 120.0, 90.0])
        # 90 liegt 25 % unter dem Hoch von 120
        assert distance_to_extreme(closes, high=True) == pytest.approx(-25.0)

    def test_abstand_zum_tief_ist_positiv(self):
        closes = pd.Series([100.0, 120.0, 90.0])
        # 90 ist das Tief selbst -> 0 %
        assert distance_to_extreme(closes, high=False) == pytest.approx(0.0)


class TestVolumeTrend:
    def test_gleichbleibendes_volumen_ergibt_null(self):
        assert volume_trend(pd.Series([1000.0] * 60)) == pytest.approx(0.0)

    def test_anstieg_wird_positiv_ausgewiesen(self):
        # 40 Tage mit 1000, danach 20 Tage mit 2000.
        volumes = pd.Series([1000.0] * 40 + [2000.0] * 20)
        # kurz = 2000, lang = (40*1000 + 20*2000)/60 = 1333.33 -> +50 %
        assert volume_trend(volumes) == pytest.approx(50.0, abs=0.1)

    def test_zu_kurze_reihe_liefert_none(self):
        assert volume_trend(pd.Series([1000.0] * 30)) is None


class TestCrossSignal:
    def test_golden_cross_bei_drehendem_trend(self):
        # Lange fallend, dann kraeftig steigend: SMA50 kreuzt SMA200 nach oben.
        closes = pd.Series([float(300 - i) for i in range(230)] + [float(70 + 4 * i) for i in range(60)])
        assert cross_signal(closes) == "Golden Cross"

    def test_lage_ohne_kreuzung(self):
        closes = pd.Series([float(100 + i) for i in range(300)])
        assert cross_signal(closes) == "SMA50 ueber SMA200"

    def test_zu_kurze_reihe_liefert_none(self):
        assert cross_signal(pd.Series([100.0] * 100)) is None


class TestComputeTechnicalMetrics:
    def test_leere_historie_liefert_alles_als_fehlend(self):
        metrics = compute_technical_metrics([])
        assert len(metrics) == 25
        assert metrics.coverage == 0.0
        assert all(not m.is_available for m in metrics)
        assert all(m.missing_reason for m in metrics)

    def test_kurze_historie_fuellt_nur_kurze_fenster(self):
        metrics = compute_technical_metrics(make_bars([float(100 + i) for i in range(30)]))
        assert metrics["rsi_14"].is_available
        # SMA 200 braucht 200 Tage - hier bewusst n/a statt verkuerztem Fenster.
        assert not metrics["sma_200"].is_available
        assert metrics["sma_200"].missing_reason

    def test_alle_werte_sind_als_berechnet_markiert(self):
        metrics = compute_technical_metrics(make_bars([float(100 + i) for i in range(300)]))
        assert all(m.is_computed for m in metrics)
        assert all("berechnet" in m.source_label for m in metrics.available)

    def test_kurs_entspricht_letztem_schlusskurs(self):
        metrics = compute_technical_metrics(make_bars([100.0, 105.0, 110.0]))
        assert metrics["price"].value == pytest.approx(110.0)

    def test_keine_nan_werte_in_den_kennzahlen(self):
        metrics = compute_technical_metrics(make_bars([float(100 + i) for i in range(300)]))
        for metric in metrics.available:
            if metric.value is not None:
                assert math.isfinite(metric.value)
