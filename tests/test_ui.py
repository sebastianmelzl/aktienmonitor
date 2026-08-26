"""Tests der Anzeigelogik.

Geprueft wird vor allem, dass fehlende Werte auf keinem Weg als Zahl in der
Oberflaeche landen koennen.
"""

from __future__ import annotations

import pytest

from aktienmonitor.metrics.fundamental import compute_fundamental_metrics
from aktienmonitor.metrics.technical import compute_technical_metrics
from aktienmonitor.models import (
    UNIT_COUNT,
    UNIT_CURRENCY,
    UNIT_DATE,
    UNIT_PERCENT,
    UNIT_TEXT,
    MetricSet,
    MetricValue,
    Provenance,
)
from aktienmonitor.ui.charts import price_chart
from aktienmonitor.ui.common import coverage_caption, metrics_table
from aktienmonitor.ui.format import (
    NOT_AVAILABLE,
    compact_currency,
    format_change,
    format_metric,
    german_number,
)

from .conftest import make_bars


class TestGermanNumber:
    @pytest.mark.parametrize(
        "wert,nachkommastellen,erwartet",
        [
            (1234567.891, 2, "1.234.567,89"),
            (0.5, 2, "0,50"),
            (-42.126, 2, "-42,13"),
            (1000.0, 0, "1.000"),
        ],
    )
    def test_deutsches_zahlenformat(self, wert, nachkommastellen, erwartet):
        assert german_number(wert, nachkommastellen) == erwartet

    def test_gleichstand_rundet_zur_geraden_ziffer(self):
        """Python rundet bei exaktem Gleichstand kaufmaennisch zur geraden Ziffer.

        Festgehalten, damit die Darstellung nicht unbemerkt kippt, falls jemand
        spaeter auf ein anderes Rundungsverfahren umstellt.
        """
        assert german_number(42.125, 2) == "42,12"
        assert german_number(42.135, 2) == "42,13"


class TestCompactCurrency:
    @pytest.mark.parametrize(
        "wert,erwartet",
        [
            (3.21e12, "3,21 Bio."),
            (2.5e9, "2,50 Mrd."),
            (7.4e6, "7,40 Mio."),
            (1500.0, "1,50 Tsd."),
            (42.0, "42,00"),
        ],
    )
    def test_grosse_betraege_werden_gekuerzt(self, wert, erwartet):
        assert compact_currency(wert) == erwartet

    def test_waehrung_wird_angehaengt(self):
        assert compact_currency(2.5e9, "EUR") == "2,50 Mrd. EUR"


class TestFormatMetric:
    def test_fehlender_wert_wird_immer_zu_na(self):
        assert format_metric(MetricValue.missing("x", "X")) == NOT_AVAILABLE

    def test_nan_wird_zu_na(self):
        assert format_metric(MetricValue(key="x", label="X", value=float("nan"))) == NOT_AVAILABLE

    def test_null_wird_als_zahl_dargestellt(self):
        # 0.0 ist ein Wert und darf nicht als n/a erscheinen.
        assert format_metric(MetricValue(key="x", label="X", value=0.0)) == "0,00"

    @pytest.mark.parametrize(
        "einheit,wert,erwartet",
        [
            (UNIT_PERCENT, 12.345, "12,35 %"),
            (UNIT_COUNT, 23.0, "23"),
            (UNIT_CURRENCY, 2.5e9, "2,50 Mrd."),
        ],
    )
    def test_einheiten(self, einheit, wert, erwartet):
        assert format_metric(MetricValue(key="x", label="X", value=wert, unit=einheit)) == erwartet

    def test_textkennzahl(self):
        metric = MetricValue(key="x", label="X", text="Golden Cross", unit=UNIT_TEXT)
        assert format_metric(metric) == "Golden Cross"

    def test_datumskennzahl(self):
        metric = MetricValue(key="x", label="X", text="2026-11-04", unit=UNIT_DATE)
        assert format_metric(metric) == "2026-11-04"


class TestFormatChange:
    def test_vorzeichen_wird_gesetzt(self):
        assert format_change(3.5) == "+3,50 %"
        assert format_change(-3.5) == "-3,50 %"

    def test_fehlender_wert(self):
        assert format_change(None) == NOT_AVAILABLE


class TestMetricsTable:
    def test_spalten_und_zeilen(self, statements_payload):
        metrics = compute_fundamental_metrics(info={}, statements_payload=statements_payload)
        tabelle = metrics_table(metrics)
        assert list(tabelle.columns) == ["Kennzahl", "Wert", "Quelle", "Hinweis"]
        assert len(tabelle) == len(metrics)

    def test_fehlende_zeilen_zeigen_na_und_begruendung(self):
        metrics = MetricSet({"a": MetricValue.missing("a", "Testkennzahl")})
        zeile = metrics_table(metrics).iloc[0]
        assert zeile["Wert"] == NOT_AVAILABLE
        assert zeile["Quelle"] == "-"
        assert zeile["Hinweis"]

    def test_berechnete_zeilen_sind_gekennzeichnet(self):
        metrics = MetricSet(
            {
                "a": MetricValue(
                    key="a", label="A", value=1.0, source=Provenance.YFINANCE, is_computed=True
                )
            }
        )
        assert "berechnet" in metrics_table(metrics).iloc[0]["Quelle"]

    def test_keine_kennzahl_ohne_wert_zeigt_eine_zahl(self, statements_payload):
        """Kernregel: was fehlt, erscheint als n/a - nie als Zahl."""
        metrics = compute_fundamental_metrics(info={}, statements_payload=None)
        tabelle = metrics_table(metrics)
        assert (tabelle["Wert"] == NOT_AVAILABLE).all()


class TestCoverageCaption:
    def test_text_nennt_anzahl_und_prozent(self):
        metrics = MetricSet(
            {
                "a": MetricValue(key="a", label="A", value=1.0),
                "b": MetricValue.missing("b", "B"),
            }
        )
        text = coverage_caption(metrics, "Fundamentaldaten")
        assert "1 von 2" in text
        assert "50 %" in text


class TestPriceChart:
    def test_ohne_historie_kein_chart(self):
        assert price_chart([]) is None

    def test_chart_enthaelt_die_gewaehlten_indikatoren(self):
        bars = make_bars([float(100 + i % 13 + i * 0.1) for i in range(320)])
        figur = price_chart(
            bars,
            indicators=("SMA 50", "SMA 200", "Bollinger-Baender", "Volumen", "RSI (14)", "MACD"),
        )
        namen = {trace.name for trace in figur.data}
        assert {"SMA 50", "SMA 200", "Volumen", "RSI (14)", "MACD", "Signal"} <= namen

    def test_kurze_historie_blendet_lange_durchschnitte_aus(self):
        figur = price_chart(make_bars([100.0] * 30), indicators=("SMA 50", "SMA 200"))
        namen = {trace.name for trace in figur.data}
        # Ohne ausreichende Historie wird die Linie gar nicht erst gezeichnet.
        assert "SMA 50" not in namen
        assert "SMA 200" not in namen

    def test_liniendarstellung_statt_kerzen(self):
        figur = price_chart(make_bars([100.0] * 30), candlestick=False, indicators=())
        assert figur.data[0].name == "Schlusskurs"

    def test_chart_rsi_stimmt_mit_der_kennzahl_ueberein(self):
        """Chart und Kennzahlentabelle muessen denselben RSI zeigen."""
        from aktienmonitor.metrics.technical import bars_to_frame, rsi
        from aktienmonitor.ui.charts import _rsi_series

        bars = make_bars([float(100 + i % 17 - (i % 5) * 0.6 + i * 0.15) for i in range(320)])
        frame = bars_to_frame(bars)
        aus_chart = float(_rsi_series(frame["close"]).iloc[-1])
        aus_kennzahl = compute_technical_metrics(bars)["rsi_14"].value
        assert aus_chart == pytest.approx(aus_kennzahl, abs=1e-9)
        assert aus_kennzahl == pytest.approx(rsi(frame["close"]), abs=1e-9)
