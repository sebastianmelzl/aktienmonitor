"""Tests des Aufteilungsrechners.

Schwerpunkt liegt auf den Grenzen: Positions- und Branchendeckel, Mindestgroesse,
Datenabdeckung und ganze Stueckzahlen. Ein Vorschlag, der stillschweigend
Titel weglaesst oder Klumpen bildet, waere schlimmer als keiner.
"""

from __future__ import annotations

import pytest

from aktienmonitor.models import MetricSet, MetricValue, Provenance, SecurityProfile
from aktienmonitor.providers.fetcher import StockSnapshot
from aktienmonitor.scoring.allocation import (
    AllocationConstraints,
    AllocationMethod,
    allocate,
)
from aktienmonitor.scoring.engine import score_snapshot


def snapshot(
    ticker: str,
    *,
    sector: str = "Technology",
    price: float | None = 100.0,
    consensus: float = 2.0,
    currency: str = "EUR",
    coverage_metrics: int = 11,
) -> StockSnapshot:
    """Baut einen Titel mit steuerbarer Datenabdeckung und Score.

    Die elf Kennzahlen entsprechen genau den absolut bewertbaren Regeln des
    Fundamental-Regelwerks - mehr ist ohne Sektor-Vergleichsgruppe nicht
    erreichbar.
    """
    fundamental: dict[str, MetricValue] = {}
    verfuegbar = [
        ("dividend_yield", 3.0), ("payout_ratio", 45.0), ("equity_ratio", 45.0),
        ("current_ratio", 1.8), ("roic", 14.0), ("fcf_margin", 12.0),
        ("net_debt_ebitda", 1.2), ("revenue_growth_3y", 9.0),
        ("earnings_growth_3y", 8.0), ("peg", 1.2),
        ("share_count_change_1y", -1.0),
    ]
    for index, (key, value) in enumerate(verfuegbar):
        if index < coverage_metrics:
            fundamental[key] = MetricValue(
                key=key, label=key, value=value, source=Provenance.YFINANCE
            )
        else:
            fundamental[key] = MetricValue.missing(key, key)
    return StockSnapshot(
        ticker=ticker,
        profile=SecurityProfile(ticker=ticker, name=f"{ticker} AG", sector=sector),
        price=price,
        currency=currency,
        fundamental=MetricSet(fundamental),
        analyst=MetricSet(
            {
                "consensus_score": MetricValue(
                    key="consensus_score", label="Konsens", value=consensus,
                    source=Provenance.YFINANCE,
                )
            }
        ),
    )


def kandidaten(*snapshots) -> list[tuple]:
    return [(s, score_snapshot(s)) for s in snapshots]


class TestGrundfall:
    def test_gleichgewichtet_verteilt_gleichmaessig(self):
        result = allocate(
            kandidaten(snapshot("A"), snapshot("B"), snapshot("C"), snapshot("D")),
            10_000.0,
            method=AllocationMethod.EQUAL,
            constraints=AllocationConstraints(max_sector_share=1.0, max_position_share=1.0),
        )
        assert len(result.items) == 4
        for item in result.items:
            assert item.weight == pytest.approx(0.25)

    def test_ganze_stueckzahlen_und_restbetrag(self):
        # 10.000 auf 4 Titel zu je 2.500, Kurs 300 -> 8 Stueck = 2.400
        result = allocate(
            kandidaten(*[snapshot(t, price=300.0) for t in "ABCD"]),
            10_000.0,
            constraints=AllocationConstraints(max_sector_share=1.0, max_position_share=1.0),
        )
        for item in result.items:
            assert item.shares == 8
            assert item.invested_amount == pytest.approx(2400.0)
        assert result.invested == pytest.approx(9600.0)
        assert result.cash_left == pytest.approx(400.0)

    def test_score_gewichtung_bevorzugt_hohe_scores(self):
        gut = snapshot("GUT", consensus=1.0)
        schlecht = snapshot("SCHLECHT", consensus=5.0)
        result = allocate(
            kandidaten(gut, schlecht), 10_000.0,
            method=AllocationMethod.SCORE_WEIGHTED,
            constraints=AllocationConstraints(max_sector_share=1.0, max_position_share=1.0),
        )
        gewichte = {i.ticker: i.weight for i in result.items}
        assert gewichte["GUT"] > gewichte["SCHLECHT"]

    def test_summe_der_gewichte_ist_eins(self):
        result = allocate(
            kandidaten(*[snapshot(t) for t in "ABCDE"]), 20_000.0,
            constraints=AllocationConstraints(max_sector_share=1.0),
        )
        assert sum(i.weight for i in result.items) == pytest.approx(1.0, abs=1e-6)


class TestGrenzen:
    def test_positionsdeckel_wird_eingehalten(self):
        result = allocate(
            kandidaten(*[snapshot(t) for t in "ABCDE"]), 10_000.0,
            method=AllocationMethod.SCORE_WEIGHTED,
            constraints=AllocationConstraints(
                max_position_share=0.25, max_sector_share=1.0, min_position_amount=0.0
            ),
        )
        for item in result.items:
            assert item.weight <= 0.25 + 1e-6

    def test_branchendeckel_wird_eingehalten(self):
        """Vier Technologiewerte und zwei aus anderen Branchen."""
        snaps = [snapshot(t, sector="Technology") for t in "ABCD"]
        snaps += [snapshot("BANK", sector="Financial Services"),
                  snapshot("PHARMA", sector="Healthcare")]
        result = allocate(
            kandidaten(*snaps), 60_000.0,
            constraints=AllocationConstraints(
                max_sector_share=0.40, max_position_share=0.5, min_position_amount=0.0
            ),
        )
        tech = sum(i.weight for i in result.items if i.sector == "Technology")
        assert tech <= 0.40 + 1e-6

    def test_unerfuellbare_deckel_werden_benannt(self):
        """Vier Titel einer Branche plus zwei andere: 40 % Branchendeckel laesst
        60 % fuer zwei Titel, also je 30 % - der 25 %-Positionsdeckel kann dann
        nicht zugleich gelten. Das muss dastehen, nicht still aufgeloest werden.
        """
        snaps = [snapshot(t, sector="Technology") for t in "ABCD"]
        snaps += [snapshot("BANK", sector="Financial Services"),
                  snapshot("PHARMA", sector="Healthcare")]
        result = allocate(
            kandidaten(*snaps), 10_000.0,
            constraints=AllocationConstraints(
                max_position_share=0.25, max_sector_share=0.40, min_position_amount=0.0
            ),
        )
        assert any("nicht gleichzeitig erfuellbar" in w for w in result.warnings)
        assert any("nicht einhalten" in w for w in result.warnings)

    def test_erfuellbare_deckel_melden_nichts(self):
        snaps = [snapshot("A", sector="Technology"), snapshot("B", sector="Healthcare"),
                 snapshot("C", sector="Financial Services"),
                 snapshot("D", sector="Industrials"), snapshot("E", sector="Energy")]
        result = allocate(
            kandidaten(*snaps), 50_000.0,
            constraints=AllocationConstraints(
                max_position_share=0.25, max_sector_share=0.40, min_position_amount=0.0
            ),
        )
        assert not any("nicht gleichzeitig erfuellbar" in w for w in result.warnings)
        assert not any("nicht einhalten" in w for w in result.warnings)

    def test_einzige_branche_wird_als_klumpen_gemeldet(self):
        result = allocate(
            kandidaten(*[snapshot(t, sector="Technology") for t in "ABCD"]), 10_000.0
        )
        assert any("einzige Branche" in w or "einer einzigen Branche" in w
                   for w in result.warnings)

    def test_zu_kleine_positionen_fliegen_raus(self):
        result = allocate(
            kandidaten(*[snapshot(t) for t in "ABCDEFGH"]), 1_000.0,
            constraints=AllocationConstraints(
                min_position_amount=300.0, max_sector_share=1.0, max_position_share=1.0
            ),
        )
        assert len(result.items) <= 3
        assert any("weniger als" in grund for _, grund in result.excluded)

    def test_hoechstzahl_der_positionen(self):
        result = allocate(
            kandidaten(*[snapshot(f"T{i}") for i in range(15)]), 100_000.0,
            constraints=AllocationConstraints(
                max_positions=5, max_sector_share=1.0, max_position_share=1.0
            ),
        )
        assert len(result.items) == 5
        assert any("besten 5" in grund for _, grund in result.excluded)


class TestAusschluesse:
    def test_ohne_score_ausgeschlossen(self):
        leer = StockSnapshot(ticker="LEER", profile=SecurityProfile(ticker="LEER"))
        result = allocate([(leer, score_snapshot(leer))], 10_000.0)
        assert result.items == []
        assert ("LEER", "Kein Gesamtscore berechenbar") in result.excluded

    def test_duenne_datenlage_ausgeschlossen(self):
        """Ein Score aus einer von elf Kennzahlen taugt nicht als Grundlage."""
        duenn = snapshot("DUENN", coverage_metrics=1)
        result = allocate(kandidaten(duenn), 10_000.0,
                          constraints=AllocationConstraints(min_coverage=35.0))
        assert result.items == []
        assert any("Datenabdeckung" in grund for _, grund in result.excluded)

    def test_ohne_kurs_ausgeschlossen(self):
        result = allocate(kandidaten(snapshot("OHNEKURS", price=None)), 10_000.0)
        assert result.items == []
        assert any("Kein Kurs" in grund for _, grund in result.excluded)

    def test_mindestscore(self):
        result = allocate(
            kandidaten(snapshot("SCHWACH", consensus=5.0)), 10_000.0,
            constraints=AllocationConstraints(min_score=70.0),
        )
        assert result.items == []
        assert any("unter 70" in grund for _, grund in result.excluded)

    def test_kurs_ueber_zielbetrag(self):
        # Ein Stueck kostet mehr als der gesamte Zielbetrag der Position
        result = allocate(
            kandidaten(snapshot("TEUER", price=5_000.0), snapshot("B", price=10.0)),
            2_000.0,
            constraints=AllocationConstraints(max_sector_share=1.0, max_position_share=1.0,
                                              min_position_amount=0.0),
        )
        assert any("ganzes Stueck" in grund for _, grund in result.excluded)

    def test_maximale_abdeckung_ohne_vergleichsgruppe(self):
        """Ohne Sektor-Vergleichsgruppe sind hoechstens rund 53 % erreichbar.

        Haelt fest, warum die Mindestabdeckung nicht hoeher gesetzt werden darf.
        """
        snap = snapshot("VOLL", coverage_metrics=11)
        abdeckung = score_snapshot(snap).categories["fundamental"].weight_coverage * 100.0
        assert 50.0 < abdeckung < 56.0

    def test_ausschluesse_werden_immer_begruendet(self):
        result = allocate(
            kandidaten(snapshot("A", coverage_metrics=1), snapshot("B", price=None)),
            10_000.0,
        )
        for ticker, grund in result.excluded:
            assert ticker and grund


class TestHinweise:
    def test_verschiedene_waehrungen_werden_gemeldet(self):
        """Betraege werden nicht umgerechnet - das muss dastehen."""
        result = allocate(
            kandidaten(
                snapshot("EUR1", currency="EUR", sector="Technology"),
                snapshot("USD1", currency="USD", sector="Healthcare"),
                snapshot("EUR2", currency="EUR", sector="Financial Services"),
            ),
            30_000.0,
        )
        assert any("NICHT umgerechnet" in w for w in result.warnings)

    def test_grosser_restbetrag_wird_gemeldet(self):
        result = allocate(
            kandidaten(snapshot("A", price=900.0), snapshot("B", price=900.0),
                       snapshot("C", price=900.0)),
            3_000.0,
            constraints=AllocationConstraints(max_sector_share=1.0, max_position_share=1.0,
                                              min_position_amount=0.0),
        )
        assert any("bleiben uebrig" in w for w in result.warnings)

    def test_wenige_positionen_werden_gemeldet(self):
        result = allocate(kandidaten(snapshot("A"), snapshot("B")), 10_000.0,
                          constraints=AllocationConstraints(max_sector_share=1.0,
                                                            max_position_share=1.0))
        assert any("streut kaum" in w for w in result.warnings)


class TestRandfaelle:
    def test_betrag_null(self):
        result = allocate(kandidaten(snapshot("A")), 0.0)
        assert result.items == []
        assert any("Kein Betrag" in w for w in result.warnings)

    def test_leere_auswahl(self):
        result = allocate([], 10_000.0)
        assert result.items == []
        assert any("Kein Titel" in w for w in result.warnings)

    def test_regeln_werden_im_klartext_beschrieben(self):
        beschreibung = AllocationConstraints().describe()
        assert any("Branche" in z for z in beschreibung)
        assert any("Datenabdeckung" in z for z in beschreibung)

    def test_branchenanteile_nach_rundung(self):
        result = allocate(
            kandidaten(snapshot("A", sector="Technology"),
                       snapshot("B", sector="Healthcare")),
            10_000.0,
            constraints=AllocationConstraints(max_sector_share=1.0, max_position_share=1.0),
        )
        assert sum(result.sector_shares.values()) == pytest.approx(100.0, abs=0.01)
