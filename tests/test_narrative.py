"""Tests der Kandidaten-Begruendung - ohne Netzzugriff.

Der wichtigste Nachweis: das Faktenblatt enthaelt genau die Zahlen, auf die
sich der Text stuetzen darf, und ohne Schluessel entsteht gar kein Text statt
eines erfundenen.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from aktienmonitor.models import MetricSet, MetricValue, Provenance, SecurityProfile
from aktienmonitor.narrative.briefing import build_briefing
from aktienmonitor.narrative.generator import (
    SYSTEM_PROMPT,
    Narrative,
    NarrativeGenerator,
    briefing_key,
)
from aktienmonitor.providers.fetcher import StockSnapshot
from aktienmonitor.scoring.changes import detect_changes
from aktienmonitor.scoring.engine import score_snapshot
from aktienmonitor.scoring.sector import SectorStatistics
from aktienmonitor.storage.cache import Cache
from aktienmonitor.storage.db import Database
from aktienmonitor.storage.history import HistoryEntry


class _Block:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _Response:
    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.content = [_Block(text)]
        self.stop_reason = stop_reason


class _Messages:
    def __init__(self, responses: list, calls: list) -> None:
        self._responses = responses
        self.calls = calls

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("Mehr Aufrufe als vorbereitete Antworten")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, *responses) -> None:
        self.calls: list = []
        self.messages = _Messages(list(responses), self.calls)


def narrative_response(**overrides) -> _Response:
    payload = {
        "einordnung": "Der Titel erreicht 76 von 100 Punkten.",
        "dafuer": ["KGV 14,0 liegt im 90. Perzentil der Branche"],
        "dagegen": ["RSI 72 erzeugt nur 55 Punkte"],
        "datenluecken": [],
    }
    payload.update(overrides)
    return _Response(json.dumps(payload))


def metric(key: str, label: str, value: float | None = None, text: str | None = None):
    if value is None and text is None:
        return MetricValue.missing(key, label)
    return MetricValue(key=key, label=label, value=value, text=text, source=Provenance.YFINANCE)


def snapshot(ticker: str = "TESTA", *, pe: float | None = 14.0) -> StockSnapshot:
    return StockSnapshot(
        ticker=ticker,
        profile=SecurityProfile(ticker=ticker, name=f"{ticker} AG", sector="Technology"),
        price=120.0,
        previous_close=118.0,
        fundamental=MetricSet(
            {
                "pe_trailing": metric("pe_trailing", "KGV (aktuell)", pe),
                "dividend_yield": metric("dividend_yield", "Dividendenrendite", 3.0),
                "roic": metric("roic", "Kapitalrendite (ROIC)"),
            }
        ),
        analyst=MetricSet({"consensus_score": metric("consensus_score", "Konsens-Note", 1.5)}),
    )


@pytest.fixture
def cache(tmp_path):
    return Cache(Database(tmp_path / "narrative.db"))


class TestBriefing:
    def test_enthaelt_stammdaten_und_scores(self):
        snap = snapshot()
        text = build_briefing(snap, score_snapshot(snap))
        assert "TESTA" in text
        assert "TESTA AG" in text
        assert "Technology" in text
        assert "Gesamtscore" in text
        assert "Fundamental" in text

    def test_nennt_beitraege_mit_werten_und_punkten(self):
        snap = snapshot()
        text = build_briefing(snap, score_snapshot(snap))
        assert "Dividendenrendite" in text
        assert "Punkten" in text

    def test_nennt_nicht_bewertete_kennzahlen_mit_grund(self):
        snap = snapshot()
        text = build_briefing(snap, score_snapshot(snap))
        assert "Nicht in die Bewertung eingegangen" in text
        assert "Kapitalrendite (ROIC)" in text

    def test_sektorvergleich_wird_ausgewiesen(self):
        snaps = [snapshot(f"T{i}", pe=10.0 + i * 5) for i in range(4)]
        statistics = SectorStatistics.from_universe(
            [(s.profile.sector, s.fundamental) for s in snaps]
        )
        text = build_briefing(snaps[0], score_snapshot(snaps[0], statistics=statistics))
        assert "Perzentil" in text
        assert "Vergleichstitel" in text

    def test_veraenderungen_werden_aufgenommen(self):
        snap = snapshot()
        scored = score_snapshot(snap)
        previous = HistoryEntry(
            "TESTA", datetime.now(UTC) - timedelta(days=7), total=30.0,
            fundamental=30.0, technical=None, analyst=30.0,
            coverage_fundamental=50.0, price=100.0,
        )
        text = build_briefing(snap, scored, detect_changes(snap, scored, previous))
        assert "Veraenderungen" in text

    def test_ohne_veraenderungen_kein_abschnitt(self):
        snap = snapshot()
        text = build_briefing(snap, score_snapshot(snap), None)
        assert "Veraenderungen" not in text

    def test_fonds_werden_gekennzeichnet(self):
        snap = StockSnapshot(
            ticker="ETF", profile=SecurityProfile(ticker="ETF", quote_type="ETF")
        )
        text = build_briefing(snap, score_snapshot(snap))
        assert "Fonds oder ETF" in text


class TestSystemPrompt:
    """Die Anweisung muss die Grenzen ausdruecklich setzen."""

    @pytest.mark.parametrize(
        "vorgabe",
        ["AUSSCHLIESSLICH", "Kursprognose", "kaufen", "Konvention", "Deutsch"],
    )
    def test_anweisung_nennt_die_grenzen(self, vorgabe):
        assert vorgabe in SYSTEM_PROMPT


class TestGenerator:
    def test_erzeugt_text_aus_faktenblatt(self, cache):
        client = FakeClient(narrative_response())
        generator = NarrativeGenerator(None, cache, client=client)
        result = generator.generate("TESTA", "Faktenblatt mit Zahlen")
        assert result is not None
        assert "76" in result.einordnung
        assert result.dafuer

    def test_faktenblatt_wird_uebergeben(self, cache):
        client = FakeClient(narrative_response())
        NarrativeGenerator(None, cache, client=client).generate("TESTA", "MEIN FAKTENBLATT")
        assert "MEIN FAKTENBLATT" in client.calls[0]["messages"][0]["content"]
        assert client.calls[0]["output_config"]["format"]["type"] == "json_schema"

    def test_zweiter_aufruf_kommt_aus_dem_cache(self, cache):
        client = FakeClient(narrative_response())
        generator = NarrativeGenerator(None, cache, client=client)
        first = generator.generate("TESTA", "Faktenblatt")
        second = NarrativeGenerator(None, cache, client=FakeClient()).generate(
            "TESTA", "Faktenblatt"
        )
        assert second == first
        assert len(client.calls) == 1

    def test_geaenderte_zahlen_erzeugen_neuen_text(self, cache):
        assert briefing_key("TESTA", "Stand A") != briefing_key("TESTA", "Stand B")

    def test_cache_only_ruft_nie_an(self, cache):
        client = FakeClient()
        result = NarrativeGenerator("key", cache, client=client).generate(
            "TESTA", "Faktenblatt", cache_only=True
        )
        assert result is None
        assert client.calls == []

    def test_ohne_schluessel_kein_text(self, cache):
        generator = NarrativeGenerator(None, cache)
        assert not generator.available
        assert generator.generate("TESTA", "Faktenblatt") is None

    def test_ungueltiges_json_ergibt_keinen_text(self, cache):
        client = FakeClient(_Response("kein JSON"))
        assert NarrativeGenerator(None, cache, client=client).generate("T", "F") is None

    def test_ablehnung_ergibt_keinen_text(self, cache):
        client = FakeClient(narrative_response(), )
        client.messages._responses[0].stop_reason = "refusal"
        assert NarrativeGenerator(None, cache, client=client).generate("T", "F") is None

    def test_api_fehler_ergibt_keinen_text(self, cache):
        client = FakeClient(RuntimeError("Netzfehler"))
        assert NarrativeGenerator(None, cache, client=client).generate("T", "F") is None

    def test_leere_einordnung_wird_verworfen(self, cache):
        client = FakeClient(narrative_response(einordnung="   "))
        assert NarrativeGenerator(None, cache, client=client).generate("T", "F") is None

    def test_leeres_faktenblatt_ruft_nicht_an(self, cache):
        client = FakeClient()
        assert NarrativeGenerator(None, cache, client=client).generate("T", "  ") is None
        assert client.calls == []

    def test_narrative_erkennt_leeren_text(self):
        assert Narrative(einordnung="  ").is_empty
        assert not Narrative(einordnung="Etwas").is_empty
