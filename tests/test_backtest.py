"""Tests des Backtest-Moduls fuer den technischen Teilscore.

Alle Erwartungswerte sind von Hand nachgerechnet; die Herleitung steht jeweils
am Test. Der wichtigste Test ist der auf fehlenden Lookahead - ohne ihn waere
ein Backtest wertlos, weil er dem heutigen Wissen Zukunftsdaten unterschieben
wuerde.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from aktienmonitor.backtest.technical import (
    LIMITATIONS,
    WalkForwardPoint,
    bucket_by_score,
    pearson_correlation,
    walk_forward,
)


def _flat_bar(day: date, close: float) -> dict:
    """Kerze ohne Intraday-Spanne - vereinfacht ATR/True-Range auf |Delta Close|."""
    return {"date": day.isoformat(), "open": close, "high": close, "low": close,
            "close": close, "volume": 1_000_000}


def _linear_bars(n: int, *, start: date = date(2024, 1, 1), start_price: float = 100.0,
                  step: float = 1.0) -> list[dict]:
    return [_flat_bar(start + timedelta(days=i), start_price + step * i) for i in range(n)]


class TestWalkForwardMechanics:
    def test_zu_wenig_historie_liefert_leere_liste(self):
        bars = _linear_bars(30)
        assert walk_forward(bars, horizon_days=5, min_history_days=40) == []

    def test_stichtage_liegen_im_erwarteten_abstand(self):
        """70 Kerzen, min_history_days=40, step=10, horizon=5 -> Stichtage bei 40 und 50 und 60.

        i muss i+horizon_days < 70 erfuellen: 40+5=45<70 ok, 50+5=55<70 ok,
        60+5=65<70 ok, 70+5=75<70 nicht mehr erreicht (Schleife stoppt vorher).
        """
        bars = _linear_bars(70)
        punkte = walk_forward(bars, horizon_days=5, step_days=10, min_history_days=40)
        erwartete_daten = [date(2024, 1, 1) + timedelta(days=i) for i in (40, 50, 60)]
        assert [p.date for p in punkte] == erwartete_daten

    def test_forward_return_exakte_rechnung(self):
        """Linearer Kurs 100+i: bei i=40 -> 140, bei i=45 -> 145.

        (145 / 140 - 1) * 100 = 3,571428... %
        """
        bars = _linear_bars(70)
        punkte = walk_forward(bars, horizon_days=5, step_days=10, min_history_days=40)
        erster = punkte[0]
        assert erster.date == date(2024, 1, 1) + timedelta(days=40)
        assert erster.forward_return == pytest.approx(3.571428, abs=1e-4)

    def test_technischer_score_ist_verfuegbar_ab_genug_historie(self):
        bars = _linear_bars(70)
        punkte = walk_forward(bars, horizon_days=5, step_days=10, min_history_days=40)
        for punkt in punkte:
            assert punkt.technical_score is not None
            assert 0.0 <= punkt.technical_score <= 100.0
            assert 0.0 <= punkt.weight_coverage <= 1.0

    def test_benchmark_folgerendite_wird_ueber_denselben_zeitraum_berechnet(self):
        """Referenz waechst doppelt so schnell (step=2 statt 1) - Vorsprung negativ."""
        bars = _linear_bars(70, step=1.0)
        benchmark = _linear_bars(70, step=2.0)
        punkte = walk_forward(
            bars, horizon_days=5, step_days=10, min_history_days=40, benchmark_bars=benchmark
        )
        erster = punkte[0]
        assert erster.benchmark_forward_return is not None
        assert erster.excess_return is not None
        assert erster.excess_return < 0


class TestKeinLookahead:
    def test_score_und_rendite_bleiben_gleich_wenn_zukunft_sich_aendert(self):
        """Kernvoraussetzung eines Backtests: ein Stichtag darf nicht sehen,
        was danach passiert. Wir haengen an dieselbe Basisreihe einen massiven
        Kursschock (Faktor 100) ab Tag 70 an und vergleichen die Stichtage, die
        in beiden Reihen komplett vor dem Schock ausgewertet werden (i<=64,
        siehe Herleitung oben) - sie muessen identisch sein.
        """
        basis = _linear_bars(70)
        schock = [
            _flat_bar(date(2024, 1, 1) + timedelta(days=i), (100.0 + i) * 100.0)
            for i in range(70, 100)
        ]
        verlaengert = basis + schock

        punkte_basis = walk_forward(basis, horizon_days=5, step_days=10, min_history_days=40)
        punkte_verlaengert = walk_forward(
            verlaengert, horizon_days=5, step_days=10, min_history_days=40
        )

        by_date_basis = {p.date: p for p in punkte_basis}
        by_date_verlaengert = {p.date: p for p in punkte_verlaengert}

        # Alle Stichtage aus der Basisreihe muessen unveraendert wiederkehren.
        assert set(by_date_basis) <= set(by_date_verlaengert)
        for stichtag, original in by_date_basis.items():
            nachgerechnet = by_date_verlaengert[stichtag]
            assert nachgerechnet.technical_score == pytest.approx(original.technical_score)
            assert nachgerechnet.weight_coverage == pytest.approx(original.weight_coverage)
            assert nachgerechnet.forward_return == pytest.approx(original.forward_return)

        # Die verlaengerte Reihe hat zusaetzliche, spaetere Stichtage.
        assert len(punkte_verlaengert) > len(punkte_basis)


class TestScoreBucket:
    def _punkt(self, score: float, forward: float, benchmark: float | None = None) -> WalkForwardPoint:
        return WalkForwardPoint(
            date=date(2024, 1, 1), technical_score=score, weight_coverage=1.0,
            forward_return=forward, benchmark_forward_return=benchmark,
        )

    def test_terzile_gleich_gross_bei_teilbarer_menge(self):
        """9 Punkte, Scores 10..90 in 10er-Schritten -> je 3 pro Terzil."""
        punkte = [self._punkt(score, forward=score / 10.0) for score in range(10, 100, 10)]
        gruppen = bucket_by_score(punkte, buckets=3)
        assert [g.n for g in gruppen] == [3, 3, 3]
        assert gruppen[0].label == "Unteres Drittel"
        assert gruppen[2].label == "Oberes Drittel"

    def test_mittlere_folgerendite_und_win_rate(self):
        """Oberes Terzil: Renditen 7,8,9 -> Mittel 8. Alle mit Vorsprung > 0."""
        punkte = [self._punkt(score, forward=score / 10.0, benchmark=0.0) for score in range(10, 100, 10)]
        gruppen = bucket_by_score(punkte, buckets=3)
        oberes = gruppen[2]
        assert oberes.mean_forward_return == pytest.approx(8.0)
        assert oberes.mean_benchmark_return == pytest.approx(0.0)
        assert oberes.win_rate == pytest.approx(100.0)

    def test_ohne_score_keine_gruppen(self):
        punkte = [
            WalkForwardPoint(date=date(2024, 1, 1), technical_score=None, weight_coverage=0.0,
                              forward_return=1.0, benchmark_forward_return=None)
        ]
        assert bucket_by_score(punkte) == []

    def test_leere_liste(self):
        assert bucket_by_score([]) == []


class TestPearsonCorrelation:
    def _punkt(self, score: float, forward: float) -> WalkForwardPoint:
        return WalkForwardPoint(
            date=date(2024, 1, 1), technical_score=score, weight_coverage=1.0,
            forward_return=forward, benchmark_forward_return=None,
        )

    def test_perfekte_positive_korrelation(self):
        punkte = [self._punkt(score=x, forward=2.0 * x + 1.0) for x in range(1, 10)]
        assert pearson_correlation(punkte) == pytest.approx(1.0)

    def test_perfekte_negative_korrelation(self):
        punkte = [self._punkt(score=x, forward=-3.0 * x) for x in range(1, 10)]
        assert pearson_correlation(punkte) == pytest.approx(-1.0)

    def test_zu_wenig_beobachtungen(self):
        punkte = [self._punkt(score=x, forward=x) for x in range(1, 4)]
        assert pearson_correlation(punkte) is None

    def test_konstante_werte_ohne_varianz(self):
        punkte = [self._punkt(score=50.0, forward=1.0) for _ in range(6)]
        assert pearson_correlation(punkte) is None


def test_limitations_sind_dokumentiert():
    assert len(LIMITATIONS) >= 3
    assert all(isinstance(text, str) and text for text in LIMITATIONS)
