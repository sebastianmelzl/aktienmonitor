"""Tests des Entscheidungstagebuchs."""

from __future__ import annotations

from datetime import date

import pytest

from aktienmonitor.storage.db import Database
from aktienmonitor.storage.journal import ACTION_BUY, ACTION_SELL, DecisionJournal, JournalEntry


@pytest.fixture
def journal(tmp_path):
    return DecisionJournal(Database(tmp_path / "journal.db"))


def test_leeres_tagebuch(journal):
    assert journal.all() == []
    assert journal.count() == 0
    assert journal.tickers() == []


def test_eintrag_anlegen_und_lesen(journal):
    eintrag = JournalEntry(
        ticker="test",
        action=ACTION_BUY,
        decided_at=date(2024, 3, 1),
        price=42.5,
        amount=500.0,
        shares=11.0,
        score_at_decision=72.0,
        rationale="Golden Cross plus guenstige Bewertung im Sektorvergleich.",
    )
    neue_id = journal.add(eintrag)
    assert neue_id > 0

    alle = journal.all()
    assert len(alle) == 1
    gelesen = alle[0]
    # Ticker wird normalisiert gross geschrieben, wie ueberall sonst im Projekt.
    assert gelesen.ticker == "TEST"
    assert gelesen.action == ACTION_BUY
    assert gelesen.decided_at == date(2024, 3, 1)
    assert gelesen.price == pytest.approx(42.5)
    assert gelesen.amount == pytest.approx(500.0)
    assert gelesen.shares == pytest.approx(11.0)
    assert gelesen.score_at_decision == pytest.approx(72.0)
    assert gelesen.rationale == "Golden Cross plus guenstige Bewertung im Sektorvergleich."
    assert gelesen.id == neue_id
    assert gelesen.created_at is not None


def test_unbekannte_aktion_wird_abgelehnt(journal):
    eintrag = JournalEntry(ticker="TEST", action="Halten", decided_at=date(2024, 1, 1))
    with pytest.raises(ValueError, match="Unbekannte Aktion"):
        journal.add(eintrag)


def test_reihenfolge_juengste_zuerst(journal):
    journal.add(JournalEntry(ticker="TEST", action=ACTION_BUY, decided_at=date(2024, 1, 1)))
    journal.add(JournalEntry(ticker="TEST", action=ACTION_SELL, decided_at=date(2024, 6, 1)))
    journal.add(JournalEntry(ticker="TEST", action=ACTION_BUY, decided_at=date(2024, 3, 1)))

    daten = [e.decided_at for e in journal.all()]
    assert daten == [date(2024, 6, 1), date(2024, 3, 1), date(2024, 1, 1)]


def test_filter_nach_ticker(journal):
    journal.add(JournalEntry(ticker="AAA", action=ACTION_BUY, decided_at=date(2024, 1, 1)))
    journal.add(JournalEntry(ticker="BBB", action=ACTION_BUY, decided_at=date(2024, 1, 1)))

    nur_aaa = journal.all(ticker="aaa")
    assert len(nur_aaa) == 1
    assert nur_aaa[0].ticker == "AAA"
    assert journal.tickers() == ["AAA", "BBB"]
    assert journal.count() == 2


def test_eintrag_loeschen(journal):
    neue_id = journal.add(JournalEntry(ticker="TEST", action=ACTION_BUY, decided_at=date(2024, 1, 1)))
    journal.delete(neue_id)
    assert journal.all() == []
    assert journal.count() == 0


def test_optionale_felder_bleiben_none(journal):
    """Nur Pflichtfelder gesetzt - Preis, Betrag, Stueckzahl, Score, Notiz fehlen."""
    journal.add(JournalEntry(ticker="TEST", action=ACTION_SELL, decided_at=date(2024, 1, 1)))
    gelesen = journal.all()[0]
    assert gelesen.price is None
    assert gelesen.amount is None
    assert gelesen.shares is None
    assert gelesen.score_at_decision is None
    assert gelesen.rationale is None
