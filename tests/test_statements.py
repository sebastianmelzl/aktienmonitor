"""Tests des Abschluss-Lesers."""

from __future__ import annotations

import pytest

from aktienmonitor.metrics.statements import Statement, Statements


class TestStatement:
    def test_perioden_werden_aufsteigend_sortiert(self, income_statement):
        statement = Statement(income_statement)
        years = [p.year for p in statement.periods]
        assert years == sorted(years)
        assert years == [2019, 2020, 2021, 2022, 2023, 2024]

    def test_reihe_folgt_der_sortierung(self, income_statement):
        statement = Statement(income_statement)
        series = statement.series("Total Revenue")
        assert [round(v) for _, v in series] == [1000, 1100, 1210, 1331, 1464, 1611]

    def test_latest_liefert_juengsten_wert(self, income_statement):
        assert Statement(income_statement).latest("Total Revenue") == pytest.approx(1610.51)

    def test_alias_wird_gefunden(self, income_statement):
        # "EBIT" ist ein Alias fuer "Operating Income".
        statement = Statement(income_statement)
        assert statement.latest("Operating Income") == pytest.approx(322.102)

    def test_unbekannte_position_liefert_none(self, income_statement):
        assert Statement(income_statement).latest("Gibt Es Nicht") is None

    def test_luecken_werden_uebersprungen_nicht_genullt(self):
        payload = {
            "columns": ["2023-12-31T00:00:00", "2024-12-31T00:00:00"],
            "index": [],
            "rows": {"Total Revenue": [100.0, None]},
        }
        statement = Statement(payload)
        # Der fehlende Wert wird nicht zu 0.0 - er faellt aus der Reihe heraus.
        assert statement.series("Total Revenue") == [(statement.periods[0], 100.0)]
        assert statement.latest("Total Revenue") == pytest.approx(100.0)

    def test_leeres_payload_ist_leer(self):
        assert Statement(None).is_empty
        assert Statement({}).is_empty


class TestStatements:
    def test_buendel_wird_vollstaendig_gelesen(self, statements_payload):
        statements = Statements(statements_payload)
        assert not statements.is_empty
        assert statements.income.period_count == 6
        assert statements.balance.period_count == 2
        assert len(statements.dividends) == 5

    def test_fehlendes_payload_ergibt_leeres_buendel(self):
        assert Statements(None).is_empty
