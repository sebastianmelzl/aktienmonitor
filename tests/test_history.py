"""Tests des Score-Verlaufs und der Veraenderungserkennung."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aktienmonitor.models import MetricSet, MetricValue, Provenance, SecurityProfile
from aktienmonitor.providers.fetcher import StockSnapshot
from aktienmonitor.scoring.changes import (
    CATEGORY_DELTA_MIN,
    SCORE_DELTA_MIN,
    ChangeKind,
    detect_changes,
    rank_by_relevance,
)
from aktienmonitor.scoring.engine import score_snapshot
from aktienmonitor.storage.db import Database
from aktienmonitor.storage.history import HistoryEntry, ScoreHistory, entry_from


@pytest.fixture
def history(tmp_path):
    return ScoreHistory(Database(tmp_path / "history.db"))


def metric(key: str, value: float | None = None, text: str | None = None) -> MetricValue:
    if value is None and text is None:
        return MetricValue.missing(key, key)
    return MetricValue(key=key, label=key, value=value, text=text, source=Provenance.YFINANCE)


def snapshot(
    ticker: str = "TEST",
    *,
    consensus: float | None = 2.0,
    price: float | None = 100.0,
    ma_cross: str | None = None,
    revision_balance: float | None = None,
    dividend_yield: float | None = None,
) -> StockSnapshot:
    fundamental = {}
    if dividend_yield is not None:
        fundamental["dividend_yield"] = metric("dividend_yield", dividend_yield)
    technical = {}
    if ma_cross is not None:
        technical["ma_cross"] = metric("ma_cross", text=ma_cross)
    analyst = {}
    if consensus is not None:
        analyst["consensus_score"] = metric("consensus_score", consensus)
    if revision_balance is not None:
        analyst["revision_balance"] = metric("revision_balance", revision_balance)
    return StockSnapshot(
        ticker=ticker,
        profile=SecurityProfile(ticker=ticker, sector="Technology"),
        price=price,
        fundamental=MetricSet(fundamental),
        technical=MetricSet(technical),
        analyst=MetricSet(analyst),
    )


class TestScoreHistory:
    def test_schreiben_und_lesen(self, history):
        history.record(HistoryEntry("TESTA", datetime.now(UTC), total=70.0))
        assert history.count() == 1
        assert history.latest("TESTA").total == pytest.approx(70.0)

    def test_ticker_wird_normalisiert(self, history):
        history.record(HistoryEntry("testa", datetime.now(UTC), total=70.0))
        assert history.latest("TESTA") is not None
        assert history.tickers() == ["TESTA"]

    def test_ohne_eintrag_kein_ergebnis(self, history):
        assert history.latest("GIBTESNICHT") is None
        assert history.previous("GIBTESNICHT") is None

    def test_vorstand_beachtet_mindestabstand(self, history):
        """Zwei Laeufe kurz hintereinander duerfen keinen Vergleich ergeben.

        Sonst waere der 'Vorstand' minutenalt und es gaebe nie eine
        Veraenderung zu sehen.
        """
        jetzt = datetime.now(UTC)
        history.record(HistoryEntry("TESTA", jetzt - timedelta(minutes=10), total=60.0))
        history.record(HistoryEntry("TESTA", jetzt, total=72.0))
        assert history.previous("TESTA", min_gap_hours=6.0) is None

    def test_vorstand_bei_ausreichendem_abstand(self, history):
        jetzt = datetime.now(UTC)
        history.record(HistoryEntry("TESTA", jetzt - timedelta(days=7), total=60.0))
        history.record(HistoryEntry("TESTA", jetzt, total=72.0))
        vorher = history.previous("TESTA")
        assert vorher is not None
        assert vorher.total == pytest.approx(60.0)

    def test_verlauf_ist_aufsteigend(self, history):
        jetzt = datetime.now(UTC)
        for tage, wert in ((3, 60.0), (1, 65.0), (2, 62.0)):
            history.record(HistoryEntry("TESTA", jetzt - timedelta(days=tage), total=wert))
        werte = [e.total for e in history.series("TESTA")]
        assert werte == [60.0, 62.0, 65.0]

    def test_alte_eintraege_entfernen(self, history):
        jetzt = datetime.now(UTC)
        history.record(HistoryEntry("TESTA", jetzt - timedelta(days=400), total=50.0))
        history.record(HistoryEntry("TESTA", jetzt, total=70.0))
        assert history.purge_older_than(365) == 1
        assert history.count() == 1

    def test_eintrag_aus_snapshot_und_bewertung(self):
        snap = snapshot("TESTA", consensus=1.0, ma_cross="Golden Cross", revision_balance=40.0)
        eintrag = entry_from(snap, score_snapshot(snap))
        assert eintrag.ticker == "TESTA"
        assert eintrag.total is not None
        assert eintrag.ma_cross == "Golden Cross"
        assert eintrag.revision_balance == pytest.approx(40.0)
        assert eintrag.price == pytest.approx(100.0)

    def test_fehlende_werte_bleiben_none(self):
        leer = StockSnapshot(ticker="X", profile=SecurityProfile(ticker="X"))
        eintrag = entry_from(leer, score_snapshot(leer))
        assert eintrag.total is None
        assert eintrag.ma_cross is None


class TestDetectChanges:
    def _previous(self, **kwargs) -> HistoryEntry:
        basis = {
            "ticker": "TEST",
            "recorded_at": datetime.now(UTC) - timedelta(days=7),
            "total": 60.0,
            "fundamental": 60.0,
            "technical": 60.0,
            "analyst": 60.0,
            "sentiment": None,
            "coverage_fundamental": 80.0,
            "price": 100.0,
        }
        basis.update(kwargs)
        return HistoryEntry(**basis)

    def test_ohne_vorstand_nur_ereignisse_ohne_vergleich(self):
        snap = snapshot(ma_cross="Golden Cross")
        changes = detect_changes(snap, score_snapshot(snap), None)
        assert [e.kind for e in changes.events] == [ChangeKind.GOLDEN_CROSS]
        assert changes.previous is None
        assert changes.reference_text == "kein Vergleichsstand"

    def test_score_sprung_nach_oben(self):
        snap = snapshot(consensus=1.0)  # ergibt einen hohen Score
        scored = score_snapshot(snap)
        changes = detect_changes(snap, scored, self._previous(total=40.0))
        arten = [e.kind for e in changes.events]
        assert ChangeKind.SCORE_UP in arten
        assert changes.score_delta > SCORE_DELTA_MIN

    def test_kleine_bewegung_ist_kein_ereignis(self):
        snap = snapshot(consensus=1.0)
        scored = score_snapshot(snap)
        # Vorstand nur knapp darunter -> keine Meldung
        vorher = self._previous(total=(scored.total or 0) - 2.0)
        changes = detect_changes(snap, scored, vorher)
        assert ChangeKind.SCORE_UP not in [e.kind for e in changes.events]

    def test_schwellenuebertritt(self):
        snap = snapshot(consensus=1.0)
        scored = score_snapshot(snap)
        changes = detect_changes(snap, scored, self._previous(total=65.0), threshold=70.0)
        assert ChangeKind.THRESHOLD_UP in [e.kind for e in changes.events]

    def test_schwelle_unterschritten(self):
        snap = snapshot(consensus=5.0)  # niedriger Score
        scored = score_snapshot(snap)
        changes = detect_changes(snap, scored, self._previous(total=75.0), threshold=70.0)
        assert ChangeKind.THRESHOLD_DOWN in [e.kind for e in changes.events]

    def test_teilscore_sprung(self):
        snap = snapshot(consensus=1.0)
        scored = score_snapshot(snap)
        vorher = self._previous(analyst=(scored.categories["analyst"].score or 0) - CATEGORY_DELTA_MIN - 5)
        changes = detect_changes(snap, scored, vorher)
        assert ChangeKind.CATEGORY_UP in [e.kind for e in changes.events]

    def test_revisionssaldo_dreht_ins_positive(self):
        snap = snapshot(revision_balance=30.0)
        changes = detect_changes(
            snap, score_snapshot(snap), self._previous(revision_balance=-40.0)
        )
        assert ChangeKind.REVISIONS_POSITIVE in [e.kind for e in changes.events]

    def test_revisionssaldo_dreht_ins_negative(self):
        snap = snapshot(revision_balance=-30.0)
        changes = detect_changes(
            snap, score_snapshot(snap), self._previous(revision_balance=20.0)
        )
        assert ChangeKind.REVISIONS_NEGATIVE in [e.kind for e in changes.events]

    def test_kursrueckgang_bei_stabilen_fundamentaldaten(self):
        """Der interessanteste Fall: Kurs faellt, Zahlen bleiben gleich."""
        snap = snapshot(price=80.0, dividend_yield=3.0)  # -20 % gegenueber 100
        scored = score_snapshot(snap)
        vorher = self._previous(
            price=100.0, fundamental=scored.categories["fundamental"].score
        )
        changes = detect_changes(snap, scored, vorher)
        assert ChangeKind.PRICE_DROP_STABLE in [e.kind for e in changes.events]

    def test_kursrueckgang_mit_schlechteren_zahlen_meldet_nicht(self):
        snap = snapshot(price=80.0, dividend_yield=3.0)
        scored = score_snapshot(snap)
        aktuell = scored.categories["fundamental"].score
        vorher = self._previous(
            price=100.0, fundamental=(aktuell + 30.0) if aktuell is not None else 90.0
        )
        changes = detect_changes(snap, scored, vorher)
        # Der Kursrueckgang ist durch die schlechteren Zahlen erklaert.
        assert ChangeKind.PRICE_DROP_STABLE not in [e.kind for e in changes.events]

    def test_ohne_fundamentaldaten_keine_stabilitaetsaussage(self):
        """Ohne Fundamental-Teilscore laesst sich 'Zahlen stabil' nicht belegen."""
        snap = snapshot(price=80.0)  # keine Fundamentalkennzahlen
        changes = detect_changes(snap, score_snapshot(snap), self._previous(price=100.0))
        assert ChangeKind.PRICE_DROP_STABLE not in [e.kind for e in changes.events]

    def test_verbesserte_datenlage(self):
        snap = snapshot(consensus=1.0)
        changes = detect_changes(
            snap, score_snapshot(snap), self._previous(coverage_fundamental=0.0)
        )
        # Ohne Fundamentaldaten im Snapshot bleibt die Abdeckung bei 0 -
        # es darf also gerade kein Ereignis geben.
        assert ChangeKind.COVERAGE_UP not in [e.kind for e in changes.events]

    def test_fehlende_werte_erzeugen_keine_ereignisse(self):
        leer = StockSnapshot(ticker="X", profile=SecurityProfile(ticker="X"))
        changes = detect_changes(leer, score_snapshot(leer), self._previous(total=None))
        assert changes.events == []

    def test_bezugstext_nennt_den_abstand(self):
        snap = snapshot()
        changes = detect_changes(snap, score_snapshot(snap), self._previous())
        assert "Tagen" in changes.reference_text


class TestRankByRelevance:
    def test_auffaelligste_zuerst_ohne_ereignisse_raus(self):
        stark = snapshot("STARK", consensus=1.0)
        schwach = snapshot("SCHWACH", consensus=2.0)
        ohne = snapshot("OHNE", consensus=2.0)

        eintrag = HistoryEntry(
            "X", datetime.now(UTC) - timedelta(days=7), total=20.0,
            fundamental=60.0, technical=60.0, analyst=60.0,
            coverage_fundamental=80.0, price=100.0,
        )
        changes = [
            detect_changes(schwach, score_snapshot(schwach), eintrag),
            detect_changes(stark, score_snapshot(stark), eintrag),
            detect_changes(ohne, score_snapshot(ohne), None),
        ]
        rangliste = rank_by_relevance(changes)
        assert all(c.has_events for c in rangliste)
        assert rangliste == sorted(rangliste, key=lambda c: (-c.relevance, c.ticker))
