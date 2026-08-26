"""Tests des Scorings gegen handgerechnete Werte.

Das Scoring ist der Teil, bei dem stille Fehler am teuersten sind: ein falsch
normierter Teilscore faellt in der Oberflaeche nicht auf. Deshalb wird hier
jede Rechnung im Test nachvollzogen.
"""

from __future__ import annotations

import pytest

from aktienmonitor.models import MetricSet, MetricValue, Provenance, SecurityProfile
from aktienmonitor.providers.fetcher import StockSnapshot
from aktienmonitor.scoring.definitions import DEFAULT_WEIGHTS, RULES_BY_CATEGORY
from aktienmonitor.scoring.engine import (
    EXCLUDED_MISSING,
    EXCLUDED_NO_PEERS,
    EXCLUDED_UNKNOWN_CATEGORY,
    normalise_weights,
    score_category,
    score_snapshot,
)
from aktienmonitor.scoring.rules import ScoreMode, ScoreRule, piecewise_score
from aktienmonitor.scoring.sector import SectorStatistics


def metric(key: str, value: float | None = None, text: str | None = None) -> MetricValue:
    if value is None and text is None:
        return MetricValue.missing(key, key)
    return MetricValue(key=key, label=key, value=value, text=text, source=Provenance.YFINANCE)


def metric_set(**werte) -> MetricSet:
    return MetricSet({k: metric(k, v) if not isinstance(v, str) else metric(k, text=v)
                      for k, v in werte.items()})


class TestPiecewiseScore:
    BREAKPOINTS = ((0.0, 0.0), (10.0, 50.0), (20.0, 100.0))

    @pytest.mark.parametrize(
        "wert,erwartet",
        [
            (-5.0, 0.0),    # unterhalb -> auf den unteren Randpunkt begrenzt
            (0.0, 0.0),
            (5.0, 25.0),    # Mitte zwischen 0 und 10 -> Mitte zwischen 0 und 50
            (10.0, 50.0),
            (15.0, 75.0),
            (20.0, 100.0),
            (99.0, 100.0),  # oberhalb -> auf den oberen Randpunkt begrenzt
        ],
    )
    def test_interpolation_und_begrenzung(self, wert, erwartet):
        assert piecewise_score(wert, self.BREAKPOINTS) == pytest.approx(erwartet)

    def test_guenstiger_mittelbereich(self):
        # Nicht monotone Punktefolge: bester Wert liegt in der Mitte.
        breakpoints = ((0.0, 40.0), (50.0, 100.0), (150.0, 0.0))
        assert piecewise_score(50.0, breakpoints) == pytest.approx(100.0)
        assert piecewise_score(100.0, breakpoints) == pytest.approx(50.0)
        assert piecewise_score(0.0, breakpoints) == pytest.approx(40.0)

    def test_unsortierte_stuetzstellen_werden_abgelehnt(self):
        with pytest.raises(ValueError, match="sortiert"):
            piecewise_score(1.0, ((10.0, 0.0), (0.0, 100.0)))

    def test_leere_stuetzstellen_werden_abgelehnt(self):
        with pytest.raises(ValueError):
            piecewise_score(1.0, ())

    def test_punkte_bleiben_im_bereich_0_bis_100(self):
        # Auch wenn eine Regel versehentlich Werte ausserhalb angibt.
        assert piecewise_score(5.0, ((0.0, -50.0), (10.0, 500.0))) <= 100.0
        assert piecewise_score(0.0, ((0.0, -50.0), (10.0, 500.0))) >= 0.0


class TestScoreRule:
    def test_gewicht_muss_positiv_sein(self):
        with pytest.raises(ValueError, match="Gewicht"):
            ScoreRule("x", 0.0, ScoreMode.ABSOLUTE, breakpoints=((0.0, 0.0),))

    def test_absolute_regel_braucht_stuetzstellen(self):
        with pytest.raises(ValueError, match="Stuetzstellen"):
            ScoreRule("x", 1.0, ScoreMode.ABSOLUTE)

    def test_kategoriale_regel_braucht_zuordnungen(self):
        with pytest.raises(ValueError, match="Zuordnungen"):
            ScoreRule("x", 1.0, ScoreMode.CATEGORICAL)

    def test_unbekannte_auspraegung_wird_nicht_geraten(self):
        rule = ScoreRule("x", 1.0, ScoreMode.CATEGORICAL, categories=(("A", 100.0),))
        assert rule.score_categorical("A") == 100.0
        assert rule.score_categorical("Unbekannt") is None


class TestRegelwerk:
    def test_alle_regeln_sind_gueltig(self):
        # Die Konstruktoren pruefen sich selbst - hier wird nur sichergestellt,
        # dass das Regelwerk ueberhaupt geladen werden kann.
        for kategorie, rules in RULES_BY_CATEGORY.items():
            for rule in rules:
                assert rule.weight > 0, f"{kategorie}/{rule.metric_key}"
                assert rule.rationale, f"{kategorie}/{rule.metric_key} ohne Begruendung"

    def test_keine_doppelten_kennzahlen_je_kategorie(self):
        for kategorie, rules in RULES_BY_CATEGORY.items():
            keys = [r.metric_key for r in rules]
            assert len(keys) == len(set(keys)), f"Doppelte Kennzahl in {kategorie}"

    def test_stuetzstellen_sind_sortiert(self):
        for rules in RULES_BY_CATEGORY.values():
            for rule in rules:
                if rule.breakpoints:
                    werte = [b[0] for b in rule.breakpoints]
                    assert werte == sorted(werte), rule.metric_key

    def test_voreingestellte_gewichte_summieren_auf_eins(self):
        assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)


class TestSectorStatistics:
    @pytest.fixture
    def statistik(self):
        werte = (10.0, 20.0, 30.0, 40.0, 50.0)
        return SectorStatistics.from_universe(
            [("Tech", metric_set(pe_trailing=v)) for v in werte]
        )

    def test_niedrigeres_kgv_erhaelt_den_besseren_rang(self, statistik):
        # (schlechtere + 0.5 * gleiche) / 5 * 100
        # KGV 10: vier Titel sind schlechter (hoeher), einer gleich
        # -> (4 + 0.5) / 5 * 100 = 90
        vergleich = statistik.compare("Tech", "pe_trailing", 10.0, higher_is_better=False)
        assert vergleich.percentile == pytest.approx(90.0)
        assert vergleich.median == pytest.approx(30.0)
        assert vergleich.peer_count == 5

    def test_median_erhaelt_rang_50(self, statistik):
        vergleich = statistik.compare("Tech", "pe_trailing", 30.0, higher_is_better=False)
        assert vergleich.percentile == pytest.approx(50.0)

    def test_richtung_kehrt_den_rang_um(self, statistik):
        hoch = statistik.compare("Tech", "pe_trailing", 10.0, higher_is_better=True)
        assert hoch.percentile == pytest.approx(10.0)

    def test_zu_kleine_vergleichsgruppe_liefert_nichts(self):
        statistik = SectorStatistics.from_universe(
            [("Tech", metric_set(pe_trailing=v)) for v in (10.0, 20.0)]
        )
        # Ein Rang aus zwei Titeln waere keine Aussage.
        assert statistik.compare("Tech", "pe_trailing", 10.0, higher_is_better=False) is None

    def test_unbekannte_branche_ist_eigene_gruppe(self):
        statistik = SectorStatistics.from_universe(
            [(None, metric_set(pe_trailing=v)) for v in (10.0, 20.0, 30.0)]
        )
        assert "Ohne Branchenangabe" in statistik.sectors

    def test_fehlende_kennzahlen_gehen_nicht_in_die_verteilung_ein(self):
        eintraege = [("Tech", metric_set(pe_trailing=10.0)), ("Tech", MetricSet({
            "pe_trailing": MetricValue.missing("pe_trailing", "KGV")
        }))]
        statistik = SectorStatistics.from_universe(eintraege)
        assert statistik.peer_count("Tech", "pe_trailing") == 1


class TestScoreCategory:
    def test_gegen_handrechnung(self):
        """Analysten-Score mit allen vier Kennzahlen.

        Regeln und Gewichte: consensus_score 1.0, target_upside 1.0,
        revision_balance 0.8, earnings_surprise_avg_4q 0.6.
        Punkte bei den gewaehlten Werten: 100, 35, 50, 50.
        (100*1.0 + 35*1.0 + 50*0.8 + 50*0.6) / 3.4 = 205 / 3.4 = 60.294
        """
        metrics = metric_set(
            consensus_score=1.0,
            target_upside=0.0,
            revision_balance=0.0,
            earnings_surprise_avg_4q=0.0,
        )
        ergebnis = score_category("analyst", metrics)
        assert ergebnis.score == pytest.approx(60.294, abs=0.01)
        assert ergebnis.used_count == 4
        assert ergebnis.total_count == 4
        assert ergebnis.weight_coverage == pytest.approx(1.0)

    def test_fehlende_kennzahlen_werden_herausnormiert(self):
        """Nur die Konsens-Note vorhanden -> Teilscore ist genau deren Punktzahl."""
        ergebnis = score_category("analyst", metric_set(consensus_score=1.0))
        assert ergebnis.score == pytest.approx(100.0)
        assert ergebnis.used_count == 1
        assert ergebnis.total_count == 4
        # Genutzte Gewichtung: 1.0 von 3.4
        assert ergebnis.weight_coverage == pytest.approx(1.0 / 3.4, abs=0.001)

    def test_fehlende_kennzahl_zaehlt_nicht_als_null_punkte(self):
        """Der wichtigste Fall: fehlende Daten duerfen den Score nicht druecken."""
        nur_gut = score_category("analyst", metric_set(consensus_score=1.0))
        mit_luecken = score_category(
            "analyst", metric_set(consensus_score=1.0, target_upside=None)
        )
        assert nur_gut.score == mit_luecken.score == pytest.approx(100.0)

    def test_null_punkte_zaehlen_als_beitrag(self):
        # 0 Punkte sind ein Ergebnis, kein fehlender Wert.
        ergebnis = score_category("analyst", metric_set(consensus_score=5.0))
        assert ergebnis.score == pytest.approx(0.0)
        assert ergebnis.used_count == 1

    def test_ohne_daten_kein_teilscore(self):
        ergebnis = score_category("analyst", MetricSet({}))
        assert ergebnis.score is None
        assert not ergebnis.is_available
        assert ergebnis.used_count == 0
        assert all(c.excluded_reason == EXCLUDED_MISSING for c in ergebnis.contributions)

    def test_abdeckungstext_nennt_anzahl_und_gewicht(self):
        text = score_category("analyst", metric_set(consensus_score=1.0)).coverage_text
        assert "1 von 4 Kennzahlen" in text
        assert "% der Gewichtung" in text

    def test_kategoriale_kennzahl(self):
        ergebnis = score_category("technical", MetricSet({
            "ma_cross": metric("ma_cross", text="Golden Cross")
        }))
        assert ergebnis.score == pytest.approx(100.0)

    def test_unbekannte_auspraegung_faellt_heraus(self):
        ergebnis = score_category("technical", MetricSet({
            "ma_cross": metric("ma_cross", text="Etwas Neues")
        }))
        assert ergebnis.score is None
        beitrag = next(c for c in ergebnis.contributions if c.rule.metric_key == "ma_cross")
        assert beitrag.excluded_reason == EXCLUDED_UNKNOWN_CATEGORY

    def test_sektorrelative_kennzahl_braucht_vergleichsgruppe(self):
        metrics = metric_set(pe_trailing=15.0)
        ohne = score_category("fundamental", metrics, sector="Tech", statistics=None)
        beitrag = next(c for c in ohne.contributions if c.rule.metric_key == "pe_trailing")
        assert beitrag.excluded_reason == EXCLUDED_NO_PEERS
        assert ohne.score is None

    def test_sektorrelative_kennzahl_mit_vergleichsgruppe(self):
        statistik = SectorStatistics.from_universe(
            [("Tech", metric_set(pe_trailing=v)) for v in (10.0, 20.0, 30.0, 40.0, 50.0)]
        )
        ergebnis = score_category(
            "fundamental", metric_set(pe_trailing=10.0), sector="Tech", statistics=statistik
        )
        # Einzige verfuegbare Kennzahl -> Teilscore ist ihr Perzentilrang.
        assert ergebnis.score == pytest.approx(90.0)
        beitrag = next(c for c in ergebnis.contributions if c.rule.metric_key == "pe_trailing")
        assert beitrag.comparison is not None
        assert beitrag.comparison.peer_count == 5
        assert "Perzentil" in beitrag.comparison.summary

    def test_jeder_beitrag_traegt_seine_begruendung(self):
        ergebnis = score_category("analyst", metric_set(consensus_score=2.0))
        for beitrag in ergebnis.contributions:
            assert beitrag.rule.rationale
            assert beitrag.mode_label


class TestScoreSnapshot:
    def _snapshot(self, **kwargs) -> StockSnapshot:
        profil = kwargs.pop("profile", SecurityProfile(ticker="TEST", sector="Tech"))
        return StockSnapshot(ticker="TEST", profile=profil, **kwargs)

    def test_gewicht_nicht_verfuegbarer_teilscores_wird_umverteilt(self):
        """Sentiment fehlt (Phase 4) -> sein Gewicht geht an die uebrigen.

        Voreinstellung: fundamental 0.40, technical 0.25, analyst 0.25,
        sentiment 0.10. Ohne Fundamental- und Technikdaten bleibt nur
        "analyst" mit 0.25 -> effektives Gewicht 1.0.
        """
        snapshot = self._snapshot(analyst=metric_set(consensus_score=1.0))
        ergebnis = score_snapshot(snapshot)
        assert ergebnis.effective_weights["analyst"] == pytest.approx(1.0)
        assert ergebnis.effective_weights["sentiment"] == pytest.approx(0.0)
        assert ergebnis.total == pytest.approx(100.0)
        assert "Sentiment" in ergebnis.redistributed

    def test_gesamtscore_gegen_handrechnung(self):
        """Zwei verfuegbare Teilscores, Gewichte anteilig hochskaliert.

        analyst-Score = 100 (nur consensus_score = 1.0)
        technical-Score = 100 (nur ma_cross = Golden Cross)
        Gewichte 0.25 und 0.25 -> je 0.5 -> Gesamt = 100.
        """
        snapshot = self._snapshot(
            analyst=metric_set(consensus_score=1.0),
            technical=MetricSet({"ma_cross": metric("ma_cross", text="Golden Cross")}),
        )
        ergebnis = score_snapshot(snapshot)
        assert ergebnis.effective_weights["analyst"] == pytest.approx(0.5)
        assert ergebnis.effective_weights["technical"] == pytest.approx(0.5)
        assert ergebnis.total == pytest.approx(100.0)

    def test_ungleiche_teilscores_werden_korrekt_gewichtet(self):
        """analyst = 100, technical = 0, beide Gewicht 0.25 -> Gesamt 50."""
        snapshot = self._snapshot(
            analyst=metric_set(consensus_score=1.0),
            technical=MetricSet({"ma_cross": metric("ma_cross", text="Death Cross")}),
        )
        assert score_snapshot(snapshot).total == pytest.approx(50.0)

    def test_eigene_gewichtung_wird_beachtet(self):
        snapshot = self._snapshot(
            analyst=metric_set(consensus_score=1.0),
            technical=MetricSet({"ma_cross": metric("ma_cross", text="Death Cross")}),
        )
        # Technik dreimal so stark gewichtet wie Analysten:
        # (100 * 0.25 + 0 * 0.75) = 25
        gewichte = {"fundamental": 0.0, "technical": 0.75, "analyst": 0.25, "sentiment": 0.0}
        assert score_snapshot(snapshot, weights=gewichte).total == pytest.approx(25.0)

    def test_ohne_jede_kennzahl_kein_gesamtscore(self):
        ergebnis = score_snapshot(self._snapshot())
        assert ergebnis.total is None
        assert not ergebnis.is_available

    def test_alle_vier_teilscores_werden_ausgewiesen(self):
        ergebnis = score_snapshot(self._snapshot())
        assert set(ergebnis.categories) == {"fundamental", "technical", "analyst", "sentiment"}
        assert ergebnis.categories["sentiment"].total_count == 0

    def test_score_liegt_immer_zwischen_0_und_100(self):
        for note in (1.0, 2.5, 5.0):
            snapshot = self._snapshot(analyst=metric_set(consensus_score=note))
            assert 0.0 <= score_snapshot(snapshot).total <= 100.0


class TestNormaliseWeights:
    def test_skaliert_auf_summe_eins(self):
        ergebnis = normalise_weights({"a": 2.0, "b": 2.0})
        assert ergebnis == {"a": 0.5, "b": 0.5}

    def test_negative_gewichte_werden_auf_null_gesetzt(self):
        ergebnis = normalise_weights({"a": 1.0, "b": -5.0})
        assert ergebnis["a"] == pytest.approx(1.0)
        assert ergebnis["b"] == pytest.approx(0.0)

    def test_summe_null_bleibt_null(self):
        assert normalise_weights({"a": 0.0, "b": 0.0}) == {"a": 0.0, "b": 0.0}
