"""Tests der Uebersichtstabelle: Zeilenaufbau, Filter, CSV-Export, Vergleich."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aktienmonitor.models import MetricSet, MetricValue, Provenance, SecurityProfile
from aktienmonitor.providers.fetcher import DataFreshness, StockSnapshot
from aktienmonitor.scoring.engine import score_snapshot
from aktienmonitor.ui.table import (
    COLUMNS,
    FilterResult,
    OverviewFilter,
    apply_filters,
    build_comparison_matrix,
    build_row,
    build_rows,
    rows_to_csv,
)


def snapshot(
    ticker: str = "TEST",
    *,
    sector: str = "Technology",
    price: float | None = 100.0,
    previous: float | None = 100.0,
    market_cap: float | None = 5e9,
    dividend: float | None = 2.5,
    pe: float | None = 18.0,
    consensus: float | None = 2.0,
    quote_type: str = "EQUITY",
    age_hours: float | None = 1.0,
    errors: list[str] | None = None,
) -> StockSnapshot:
    fundamental = {}
    for key, label, value in (
        ("market_cap", "Marktkapitalisierung", market_cap),
        ("dividend_yield", "Dividendenrendite", dividend),
        ("pe_trailing", "KGV (aktuell)", pe),
    ):
        fundamental[key] = (
            MetricValue(key=key, label=label, value=value, source=Provenance.YFINANCE)
            if value is not None
            else MetricValue.missing(key, label)
        )
    analyst = {}
    if consensus is not None:
        analyst["consensus_score"] = MetricValue(
            key="consensus_score", label="Konsens-Note", value=consensus,
            source=Provenance.YFINANCE,
        )
    frische = (
        [DataFreshness("Kurs", Provenance.YFINANCE,
                       datetime.now(UTC) - timedelta(hours=age_hours), True)]
        if age_hours is not None
        else []
    )
    return StockSnapshot(
        ticker=ticker,
        profile=SecurityProfile(ticker=ticker, name=f"{ticker} AG", sector=sector,
                                quote_type=quote_type),
        price=price,
        previous_close=previous,
        fundamental=MetricSet(fundamental),
        analyst=MetricSet(analyst),
        freshness=frische,
        errors=errors or [],
    )


def row_for(snap: StockSnapshot) -> dict:
    return build_row(snap, score_snapshot(snap))


class TestBuildRow:
    def test_grundfelder(self):
        zeile = row_for(snapshot("AAPL", price=110.0, previous=100.0))
        assert zeile["ticker"] == "AAPL"
        assert zeile["name"] == "AAPL AG"
        assert zeile["sector"] == "Technology"
        assert zeile["price"] == pytest.approx(110.0)
        assert zeile["change_percent"] == pytest.approx(10.0)

    def test_zahlen_bleiben_zahlen(self):
        """Fuer korrekte Sortierung und Filter duerfen es keine Textwerte sein."""
        zeile = row_for(snapshot())
        for feld in ("price", "score_total", "market_cap", "dividend_yield", "pe_trailing"):
            assert zeile[feld] is None or isinstance(zeile[feld], float)

    def test_fehlende_werte_bleiben_none(self):
        zeile = row_for(snapshot(market_cap=None, dividend=None, pe=None))
        assert zeile["market_cap"] is None
        assert zeile["dividend_yield"] is None
        assert zeile["pe_trailing"] is None

    def test_datenstand_wird_lesbar_ausgewiesen(self):
        assert "Std." in row_for(snapshot(age_hours=5.0))["data_age_text"]
        assert "Tg." in row_for(snapshot(age_hours=72.0))["data_age_text"]
        assert row_for(snapshot(age_hours=None))["data_age_text"] == "nicht abgerufen"

    def test_hinweis_bei_fehlenden_daten(self):
        leer = StockSnapshot(ticker="X", profile=SecurityProfile(ticker="X"))
        assert build_row(leer, score_snapshot(leer))["note"] == "Keine Daten abrufbar"

    def test_hinweis_bei_teilfehlern(self):
        zeile = row_for(snapshot(errors=["Analysten: Zeitueberschreitung"]))
        assert "unvollstaendig" in zeile["note"]

    def test_etf_wird_gekennzeichnet(self):
        assert row_for(snapshot(quote_type="ETF"))["is_fund"] is True


class TestBuildRows:
    def test_sortierung_nach_gesamtscore(self):
        snaps = {
            "GUT": snapshot("GUT", consensus=1.0),
            "MITTE": snapshot("MITTE", consensus=3.0),
            "SCHLECHT": snapshot("SCHLECHT", consensus=5.0),
        }
        scores = {t: score_snapshot(s) for t, s in snaps.items()}
        zeilen = build_rows(snaps, scores)
        assert [z["ticker"] for z in zeilen] == ["GUT", "MITTE", "SCHLECHT"]

    def test_titel_ohne_score_stehen_am_ende(self):
        """Unbewertbar ist nicht dasselbe wie schlecht bewertet.

        "OHNE" hat ueberhaupt keine bewertbare Kennzahl - anders als ein Titel
        mit schlechten Werten, der einen niedrigen Score bekommt.
        """
        snaps = {
            "OHNE": snapshot("OHNE", consensus=None, dividend=None, pe=None,
                             market_cap=None, price=None),
            "SCHLECHT": snapshot("SCHLECHT", consensus=5.0, dividend=0.0),
        }
        scores = {t: score_snapshot(s) for t, s in snaps.items()}
        zeilen = build_rows(snaps, scores)
        assert zeilen[-1]["ticker"] == "OHNE"
        assert zeilen[-1]["score_total"] is None


class TestApplyFilters:
    @pytest.fixture
    def zeilen(self):
        snaps = {
            "HOCH": snapshot("HOCH", consensus=1.0, dividend=4.0, market_cap=50e9, pe=15.0),
            "MITTE": snapshot("MITTE", consensus=3.0, dividend=2.0, market_cap=5e9, pe=25.0),
            "NIEDRIG": snapshot("NIEDRIG", consensus=5.0, dividend=0.5, market_cap=5e8, pe=40.0),
            "BANK": snapshot("BANK", sector="Financial Services", consensus=2.0,
                             dividend=6.0, market_cap=20e9, pe=9.0),
        }
        return build_rows(snaps, {t: score_snapshot(s) for t, s in snaps.items()})

    def test_ohne_kriterien_bleibt_alles(self, zeilen):
        ergebnis = apply_filters(zeilen, OverviewFilter())
        assert len(ergebnis.rows) == 4
        assert ergebnis.total_excluded == 0

    def test_score_schwelle(self, zeilen):
        ergebnis = apply_filters(zeilen, OverviewFilter(min_score=60.0))
        assert all(z["score_total"] >= 60.0 for z in ergebnis.rows)
        assert ergebnis.excluded_by_value > 0

    def test_sektorfilter(self, zeilen):
        ergebnis = apply_filters(zeilen, OverviewFilter(sectors=["Financial Services"]))
        assert [z["ticker"] for z in ergebnis.rows] == ["BANK"]

    def test_marktkapitalisierung_spanne(self, zeilen):
        ergebnis = apply_filters(
            zeilen, OverviewFilter(min_market_cap=1e9, max_market_cap=30e9)
        )
        assert {z["ticker"] for z in ergebnis.rows} == {"MITTE", "BANK"}

    def test_dividendenrendite(self, zeilen):
        ergebnis = apply_filters(zeilen, OverviewFilter(min_dividend_yield=3.0))
        assert {z["ticker"] for z in ergebnis.rows} == {"HOCH", "BANK"}

    def test_kgv_obergrenze(self, zeilen):
        ergebnis = apply_filters(zeilen, OverviewFilter(max_pe=20.0))
        assert {z["ticker"] for z in ergebnis.rows} == {"HOCH", "BANK"}

    def test_fehlende_werte_werden_getrennt_gezaehlt(self):
        """Kernpunkt: fehlende Daten sind kein Verfehlen der Schwelle."""
        snaps = {
            "MITWERT": snapshot("MITWERT", dividend=1.0),
            "OHNEWERT": snapshot("OHNEWERT", dividend=None),
        }
        zeilen = build_rows(snaps, {t: score_snapshot(s) for t, s in snaps.items()})
        ergebnis = apply_filters(zeilen, OverviewFilter(min_dividend_yield=3.0))
        assert ergebnis.rows == []
        assert ergebnis.excluded_by_value == 1      # MITWERT verfehlt die Schwelle
        assert ergebnis.excluded_by_missing == 1    # OHNEWERT ist nicht pruefbar
        assert ergebnis.missing_tickers == ["OHNEWERT"]

    def test_fonds_koennen_ausgeblendet_werden(self):
        snaps = {"ETF": snapshot("ETF", quote_type="ETF"), "AKTIE": snapshot("AKTIE")}
        zeilen = build_rows(snaps, {t: score_snapshot(s) for t, s in snaps.items()})
        ergebnis = apply_filters(zeilen, OverviewFilter(include_funds=False))
        assert [z["ticker"] for z in ergebnis.rows] == ["AKTIE"]

    def test_mehrere_kriterien_gleichzeitig(self, zeilen):
        ergebnis = apply_filters(
            zeilen, OverviewFilter(min_score=50.0, min_dividend_yield=3.0, max_pe=20.0)
        )
        assert {z["ticker"] for z in ergebnis.rows} == {"HOCH", "BANK"}

    def test_is_active_erkennt_gesetzte_kriterien(self):
        assert not OverviewFilter().is_active
        assert OverviewFilter(min_score=10.0).is_active
        assert OverviewFilter(sectors=["Tech"]).is_active
        assert OverviewFilter(include_funds=False).is_active


class TestRowsToCsv:
    def test_kopfzeile_entspricht_den_spalten(self):
        csv_text = rows_to_csv([row_for(snapshot())])
        kopf = csv_text.splitlines()[0]
        assert kopf == ";".join(label for _, label in COLUMNS)

    def test_deutsches_format(self):
        csv_text = rows_to_csv([row_for(snapshot(price=110.5, previous=100.0))])
        datenzeile = csv_text.splitlines()[1]
        assert ";" in datenzeile
        assert "110,5" in datenzeile

    def test_englisches_format(self):
        csv_text = rows_to_csv([row_for(snapshot(price=110.5))], german=False)
        assert "110.5" in csv_text.splitlines()[1]
        assert "," in csv_text.splitlines()[0]

    def test_fehlende_werte_bleiben_leer_statt_null(self):
        """Eine 0 im Export waere eine erfundene Zahl."""
        csv_text = rows_to_csv([row_for(snapshot(dividend=None, pe=None))])
        felder = csv_text.splitlines()[1].split(";")
        kopf = csv_text.splitlines()[0].split(";")
        assert felder[kopf.index("Dividendenrendite")] == ""
        assert felder[kopf.index("KGV")] == ""

    def test_leere_liste_ergibt_nur_die_kopfzeile(self):
        assert len(rows_to_csv([]).splitlines()) == 1


class TestComparisonMatrix:
    def test_titel_stehen_nebeneinander(self):
        snaps = {"A": snapshot("A", pe=15.0), "B": snapshot("B", pe=25.0)}
        ticker, zeilen = build_comparison_matrix(snaps, "fundamental")
        assert ticker == ["A", "B"]
        kgv = next(z for z in zeilen if z["key"] == "pe_trailing")
        assert kgv["A"].value == pytest.approx(15.0)
        assert kgv["B"].value == pytest.approx(25.0)
        assert kgv["label"] == "KGV (aktuell)"

    def test_fehlende_kennzahl_bleibt_als_zeile_erhalten(self):
        snaps = {"A": snapshot("A", pe=15.0), "B": snapshot("B", pe=None)}
        _, zeilen = build_comparison_matrix(snaps, "fundamental")
        kgv = next(z for z in zeilen if z["key"] == "pe_trailing")
        assert kgv["A"].is_available
        assert not kgv["B"].is_available

    def test_leere_auswahl(self):
        assert build_comparison_matrix({}, "fundamental") == ([], [])


class TestFilterResult:
    def test_summe_der_ausschluesse(self):
        ergebnis = FilterResult(rows=[], excluded_by_value=3, excluded_by_missing=2)
        assert ergebnis.total_excluded == 5
