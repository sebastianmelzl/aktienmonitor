"""Tests des Benchmark-Vergleichs.

Alle Erwartungswerte sind von Hand nachgerechnet; die Herleitung steht jeweils
am Test. Kurse liegen bewusst an aufeinanderfolgenden Kalendertagen, damit sich
Handelstage direkt als Listenindizes lesen lassen.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from aktienmonitor.benchmark.compare import (
    BenchmarkComparison,
    PeriodComparison,
    annualised,
    closes_by_date,
    compare,
    period_start,
    return_between,
    since_date_comparison,
    total_return,
    trading_days_between,
)


def _bars(closes: list[float], *, start: date = date(2024, 1, 1)) -> list[dict]:
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "close": close}
        for i, close in enumerate(closes)
    ]


class TestClosesByDate:
    def test_sortiert_aufsteigend(self):
        rohdaten = [
            {"date": "2024-01-03", "close": 12.0},
            {"date": "2024-01-01", "close": 10.0},
            {"date": "2024-01-02", "close": 11.0},
        ]
        reihe = closes_by_date(rohdaten)
        assert [d for d, _ in reihe] == [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
        assert [c for _, c in reihe] == [10.0, 11.0, 12.0]

    def test_ungueltige_kerzen_werden_uebersprungen(self):
        rohdaten = [
            {"date": "2024-01-01", "close": 10.0},
            {"date": "2024-01-02", "close": None},
            {"date": "2024-01-03", "close": 0.0},
            {"date": "2024-01-04", "close": -5.0},
            {"date": None, "close": 20.0},
        ]
        reihe = closes_by_date(rohdaten)
        assert reihe == [(date(2024, 1, 1), 10.0)]

    def test_leere_liste(self):
        assert closes_by_date([]) == []
        assert closes_by_date(None) == []


class TestTotalReturn:
    def test_verdopplung_ueber_zwei_handelstage(self):
        """3 Kurse (Index 0,1,2), 2 Handelstage zurueck: 100 -> 200 = 100 %."""
        bars = _bars([100.0, 150.0, 200.0])
        assert total_return(bars, trading_days=2) == pytest.approx(100.0)

    def test_verlust(self):
        """100 -> 80 ueber 2 Handelstage zurueck: -20 %."""
        bars = _bars([100.0, 90.0, 80.0])
        assert total_return(bars, trading_days=2) == pytest.approx(-20.0)

    def test_zu_wenig_historie(self):
        bars = _bars([100.0, 110.0])
        assert total_return(bars, trading_days=5) is None

    def test_leere_bars(self):
        assert total_return([], trading_days=1) is None


class TestReturnBetween:
    def test_stichtag_ohne_handel_nutzt_letzten_kurs_davor(self):
        """Kein Kurs am 3.1. (Wochenende simuliert) - der vom 2.1. gilt."""
        bars = [
            {"date": "2024-01-01", "close": 100.0},
            {"date": "2024-01-02", "close": 110.0},
            {"date": "2024-01-05", "close": 120.0},
        ]
        # Stichtag 2024-01-03 -> letzter Kurs bis dahin ist der vom 2.1. (110)
        ergebnis = return_between(bars, date(2024, 1, 1), date(2024, 1, 3))
        assert ergebnis == pytest.approx(10.0)

    def test_ohne_ende_nutzt_letzten_kurs(self):
        bars = _bars([100.0, 120.0, 150.0])
        assert return_between(bars, date(2024, 1, 1)) == pytest.approx(50.0)

    def test_start_nach_letztem_kurs_nutzt_letzten_kurs_fuer_beide_seiten(self):
        """Liegt der Stichtag hinter der Historie, gilt fuer ihn wie fuers Ende
        derselbe letzte Kurs - die Rendite ist dann 0, nicht 'fehlend'."""
        bars = _bars([100.0, 110.0])
        assert return_between(bars, date(2024, 6, 1)) == pytest.approx(0.0)

    def test_leere_bars(self):
        assert return_between([], date(2024, 1, 1)) is None


class TestPeriodComparison:
    def test_vorsprung_und_sieg(self):
        vergleich = PeriodComparison(label="1 Jahr", trading_days=252, subject=15.0, benchmark=10.0)
        assert vergleich.excess == pytest.approx(5.0)
        assert vergleich.beats_benchmark is True

    def test_rueckstand(self):
        vergleich = PeriodComparison(label="1 Jahr", trading_days=252, subject=5.0, benchmark=10.0)
        assert vergleich.excess == pytest.approx(-5.0)
        assert vergleich.beats_benchmark is False

    def test_fehlender_wert_ergibt_kein_urteil(self):
        vergleich = PeriodComparison(label="1 Jahr", trading_days=252, subject=None, benchmark=10.0)
        assert vergleich.excess is None
        assert vergleich.beats_benchmark is None


class TestBenchmarkComparison:
    def test_zusammenfassung_zaehlt_nur_verfuegbare_zeitraeume(self):
        periods = [
            PeriodComparison(label="1 Monat", trading_days=21, subject=2.0, benchmark=1.0),
            PeriodComparison(label="1 Jahr", trading_days=252, subject=None, benchmark=10.0),
            PeriodComparison(label="3 Jahre", trading_days=756, subject=8.0, benchmark=20.0),
        ]
        vergleich = BenchmarkComparison(
            ticker="TESTAG", benchmark_ticker="EUNL.DE", periods=periods
        )
        # Nur 2 von 3 Zeitraeumen haben beide Seiten; davon gewinnt einer (1 Monat).
        assert vergleich.available == [periods[0], periods[2]]
        assert vergleich.wins == 1
        assert vergleich.summary == "In 1 von 2 Zeitraeumen besser als EUNL.DE"

    def test_ohne_gemeinsame_historie(self):
        vergleich = BenchmarkComparison(ticker="TESTAG", benchmark_ticker="EUNL.DE", periods=[])
        assert vergleich.wins == 0
        assert "Kein Vergleich" in vergleich.summary


class TestCompare:
    def test_baut_alle_zeitraeume(self):
        bars = _bars([100.0] * 10 + [120.0])
        benchmark_bars = _bars([100.0] * 10 + [110.0])
        ergebnis = compare(
            "TESTAG", bars, "EUNL.DE", benchmark_bars,
            periods=(("1 Handelstag", 1), ("5 Handelstage", 5)),
        )
        assert isinstance(ergebnis, BenchmarkComparison)
        assert len(ergebnis.periods) == 2
        eintag = ergebnis.periods[0]
        assert eintag.subject == pytest.approx(20.0)
        assert eintag.benchmark == pytest.approx(10.0)
        assert eintag.beats_benchmark is True


class TestAnnualised:
    def test_ein_jahr_bleibt_gleich(self):
        assert annualised(10.0, 365) == pytest.approx(10.0, abs=0.1)

    def test_zwei_jahre_verdopplung_wird_geometrisch_umgerechnet(self):
        """Verdopplung (100 %) ueber 2 Jahre entspricht rund 41,4 % p.a.

        sqrt(2) - 1 = 0,41421...
        """
        ergebnis = annualised(100.0, 730)
        assert ergebnis == pytest.approx(41.42, abs=0.1)

    def test_totalverlust_hat_keine_annualisierte_rendite(self):
        assert annualised(-100.0, 365) is None

    def test_ohne_zeitraum(self):
        assert annualised(10.0, 0) is None


class TestSinceDateComparison:
    def test_vorsprung_wird_berechnet(self):
        bars = _bars([100.0, 130.0])
        benchmark_bars = _bars([100.0, 110.0])
        titel, referenz, vorsprung = since_date_comparison(bars, benchmark_bars, date(2024, 1, 1))
        assert titel == pytest.approx(30.0)
        assert referenz == pytest.approx(10.0)
        assert vorsprung == pytest.approx(20.0)

    def test_fehlende_referenz_ergibt_keinen_vorsprung(self):
        bars = _bars([100.0, 130.0])
        titel, referenz, vorsprung = since_date_comparison(bars, [], date(2024, 1, 1))
        assert titel == pytest.approx(30.0)
        assert referenz is None
        assert vorsprung is None


class TestHandelstage:
    def test_trading_days_between(self):
        """365 Kalendertage * 252/365,25 ~ 251,8 -> 251 (abgerundet)."""
        tage = trading_days_between(date(2023, 1, 1), date(2024, 1, 1))
        assert tage == 251

    def test_negative_spanne_wird_auf_null_begrenzt(self):
        assert trading_days_between(date(2024, 1, 1), date(2023, 1, 1)) == 0

    def test_period_start_rundtrip(self):
        heute = date(2024, 6, 15)
        start = period_start(21, today=heute)
        # 21 Handelstage entsprechen rund 30,4 Kalendertagen (21 * 365,25/252)
        assert (heute - start).days == 30
