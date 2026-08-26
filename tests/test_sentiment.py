"""Tests der Sentiment-Einordnung - ohne jeden Netzzugriff.

Der API-Client wird durch ein Doppel ersetzt, das aufgezeichnete Antworten
liefert. So sind auch die unangenehmen Faelle pruefbar: unvollstaendige
Antworten, ungueltiges JSON, Ablehnungen und der Betrieb ohne Schluessel.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from aktienmonitor.models import NewsItem
from aktienmonitor.sentiment.classifier import (
    BATCH_SIZE,
    SentimentClassifier,
    SentimentLabel,
    SentimentUnavailable,
    headline_key,
)
from aktienmonitor.sentiment.metrics import (
    MIN_CLASSIFIED,
    MISSING_NO_NEWS,
    MISSING_NOT_CLASSIFIED,
    compute_sentiment_metrics,
)
from aktienmonitor.storage.cache import Cache
from aktienmonitor.storage.db import Database

# --- Test-Doppel des API-Clients --------------------------------------------

@dataclass
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeResponse:
    content: list
    stop_reason: str = "end_turn"


class FakeMessages:
    def __init__(self, antworten: list, aufrufe: list) -> None:
        self._antworten = antworten
        self.aufrufe = aufrufe

    def create(self, **kwargs):
        self.aufrufe.append(kwargs)
        if not self._antworten:
            raise AssertionError("Mehr Aufrufe als vorbereitete Antworten")
        antwort = self._antworten.pop(0)
        if isinstance(antwort, Exception):
            raise antwort
        return antwort


class FakeClient:
    """Minimaler Ersatz fuer anthropic.Anthropic."""

    def __init__(self, *antworten) -> None:
        self.aufrufe: list = []
        self.messages = FakeMessages(list(antworten), self.aufrufe)


def verdict_response(*paare, stop_reason: str = "end_turn") -> FakeResponse:
    """Baut eine Modellantwort aus (index, label)-Paaren."""
    daten = {
        "verdicts": [
            {"index": i, "label": label, "rationale": f"Begruendung {i}"} for i, label in paare
        ]
    }
    return FakeResponse(content=[FakeTextBlock(json.dumps(daten))], stop_reason=stop_reason)


def news(anzahl: int = 3, *, tage_alt: int = 1) -> list[NewsItem]:
    return [
        NewsItem(
            headline=f"Schlagzeile {i}",
            url=f"https://example.com/{i}",
            source_name="Testquelle",
            published_at=datetime.now(UTC) - timedelta(days=tage_alt),
        )
        for i in range(anzahl)
    ]


@pytest.fixture
def cache(tmp_path):
    return Cache(Database(tmp_path / "sentiment.db"))


class TestHeadlineKey:
    def test_gleiche_schlagzeile_gleicher_schluessel(self):
        a, b = news(1)[0], news(1)[0]
        assert headline_key(a) == headline_key(b)

    def test_andere_schlagzeile_anderer_schluessel(self):
        a, b = news(2)
        assert headline_key(a) != headline_key(b)


class TestClassify:
    def test_ordnet_alle_meldungen_ein(self, cache):
        client = FakeClient(verdict_response((0, "positive"), (1, "neutral"), (2, "negative")))
        classifier = SentimentClassifier(None, cache, client=client)
        ergebnis = classifier.classify(news(3))

        assert [i.sentiment for i in ergebnis] == [
            SentimentLabel.POSITIVE, SentimentLabel.NEUTRAL, SentimentLabel.NEGATIVE
        ]
        assert all(i.sentiment_rationale for i in ergebnis)

    def test_originalquelle_bleibt_erhalten(self, cache):
        client = FakeClient(verdict_response((0, "positive")))
        ergebnis = SentimentClassifier(None, cache, client=client).classify(news(1))
        assert ergebnis[0].url == "https://example.com/0"
        assert ergebnis[0].source_name == "Testquelle"

    def test_fehlende_urteile_bleiben_unbewertet(self, cache):
        """Das Modell liefert nur zu einer von drei Meldungen ein Urteil."""
        client = FakeClient(verdict_response((1, "positive")))
        ergebnis = SentimentClassifier(None, cache, client=client).classify(news(3))
        # Kein stillschweigendes "neutral" fuer die uebrigen.
        assert [i.sentiment for i in ergebnis] == [None, SentimentLabel.POSITIVE, None]

    def test_ungueltiges_json_laesst_alles_unbewertet(self, cache):
        client = FakeClient(FakeResponse(content=[FakeTextBlock("kein JSON")]))
        ergebnis = SentimentClassifier(None, cache, client=client).classify(news(2))
        assert all(i.sentiment is None for i in ergebnis)

    def test_ablehnung_wird_abgefangen(self, cache):
        client = FakeClient(verdict_response((0, "positive"), stop_reason="refusal"))
        ergebnis = SentimentClassifier(None, cache, client=client).classify(news(1))
        assert ergebnis[0].sentiment is None

    def test_api_fehler_kippt_den_lauf_nicht(self, cache):
        client = FakeClient(RuntimeError("Netzwerkfehler"))
        ergebnis = SentimentClassifier(None, cache, client=client).classify(news(2))
        assert all(i.sentiment is None for i in ergebnis)

    def test_unbekanntes_label_wird_verworfen(self, cache):
        antwort = FakeResponse(content=[FakeTextBlock(json.dumps(
            {"verdicts": [{"index": 0, "label": "euphorisch", "rationale": "x"}]}
        ))])
        ergebnis = SentimentClassifier(None, cache, client=FakeClient(antwort)).classify(news(1))
        assert ergebnis[0].sentiment is None

    def test_index_ausserhalb_des_buendels_wird_verworfen(self, cache):
        client = FakeClient(verdict_response((99, "positive")))
        ergebnis = SentimentClassifier(None, cache, client=client).classify(news(1))
        assert ergebnis[0].sentiment is None

    def test_leere_liste(self, cache):
        assert SentimentClassifier(None, cache, client=FakeClient()).classify([]) == []

    def test_grosse_mengen_werden_gebuendelt(self, cache):
        anzahl = BATCH_SIZE + 5
        client = FakeClient(
            verdict_response(*[(i, "neutral") for i in range(BATCH_SIZE)]),
            verdict_response(*[(i, "positive") for i in range(5)]),
        )
        ergebnis = SentimentClassifier(None, cache, client=client).classify(news(anzahl))
        assert len(client.aufrufe) == 2
        assert all(i.sentiment is not None for i in ergebnis)

    def test_effort_und_schema_werden_gesetzt(self, cache):
        client = FakeClient(verdict_response((0, "neutral")))
        SentimentClassifier(None, cache, client=client).classify(news(1))
        aufruf = client.aufrufe[0]
        assert aufruf["output_config"]["effort"] == "low"
        assert aufruf["output_config"]["format"]["type"] == "json_schema"
        assert aufruf["model"] == "claude-opus-5"


class TestCaching:
    def test_zweiter_lauf_ohne_api_aufruf(self, cache):
        meldungen = news(2)
        client = FakeClient(verdict_response((0, "positive"), (1, "negative")))
        classifier = SentimentClassifier(None, cache, client=client)

        erster = classifier.classify(meldungen)
        assert len(client.aufrufe) == 1

        # Zweiter Lauf: alles aus dem Cache, kein weiterer Aufruf noetig.
        zweiter = SentimentClassifier(None, cache, client=FakeClient()).classify(meldungen)
        assert [i.sentiment for i in zweiter] == [i.sentiment for i in erster]

    def test_nur_neue_meldungen_werden_angefragt(self, cache):
        alt = news(2)
        SentimentClassifier(None, cache, client=FakeClient(
            verdict_response((0, "positive"), (1, "neutral"))
        )).classify(alt)

        neu = alt + [NewsItem("Ganz neu", "https://example.com/neu", "Q",
                              datetime.now(UTC))]
        client = FakeClient(verdict_response((0, "negative")))
        ergebnis = SentimentClassifier(None, cache, client=client).classify(neu)

        # Nur die eine neue Schlagzeile geht an das Modell.
        assert len(client.aufrufe) == 1
        assert "Ganz neu" in client.aufrufe[0]["messages"][0]["content"]
        assert ergebnis[2].sentiment == SentimentLabel.NEGATIVE

    def test_cache_only_fragt_nie_an(self, cache):
        client = FakeClient()  # keine Antworten vorbereitet
        ergebnis = SentimentClassifier("schluessel", cache, client=client).classify(
            news(3), cache_only=True
        )
        assert client.aufrufe == []
        assert all(i.sentiment is None for i in ergebnis)


class TestFehlendesPaket:
    """Regressionstest: Schluessel gesetzt, aber das SDK fehlt.

    Dieser Fall trat beim Durchspielen der Setup-Anleitung auf und liess die
    Detailansicht abstuerzen. Er darf nie wieder zu einer Ausnahme fuehren.
    """

    def test_ohne_paket_gilt_die_einordnung_als_nicht_verfuegbar(self, cache, monkeypatch):
        monkeypatch.setattr(
            "aktienmonitor.sentiment.classifier._anthropic_installed", lambda: False
        )
        classifier = SentimentClassifier("sk-ant-beispiel", cache)
        assert not classifier.available
        assert "anthropic" in classifier.unavailable_reason

    def test_ohne_paket_kein_absturz(self, cache, monkeypatch):
        monkeypatch.setattr(
            "aktienmonitor.sentiment.classifier._anthropic_installed", lambda: False
        )
        ergebnis = SentimentClassifier("sk-ant-beispiel", cache).classify(news(3))
        assert all(i.sentiment is None for i in ergebnis)

    def test_grund_erscheint_in_den_kennzahlen(self, cache, monkeypatch):
        monkeypatch.setattr(
            "aktienmonitor.sentiment.classifier._anthropic_installed", lambda: False
        )
        classifier = SentimentClassifier("sk-ant-beispiel", cache)
        metrics = compute_sentiment_metrics(
            news(5),
            key_available=classifier.available,
            unavailable_reason=classifier.unavailable_reason,
        )
        assert "anthropic" in metrics["sentiment_balance"].missing_reason


class TestOhneSchluessel:
    def test_ohne_schluessel_bleibt_alles_unbewertet(self, cache):
        classifier = SentimentClassifier(None, cache)
        assert not classifier.available
        ergebnis = classifier.classify(news(3))
        assert all(i.sentiment is None for i in ergebnis)

    def test_direkter_aufruf_ohne_schluessel_meldet_das(self, cache):
        with pytest.raises(SentimentUnavailable, match="ANTHROPIC_API_KEY"):
            SentimentClassifier(None, cache)._get_client()


class TestSentimentMetrics:
    def _eingeordnet(self, labels: list[str], *, tage_alt: int = 1) -> list[NewsItem]:
        return [
            NewsItem(
                headline=f"H{i}", url=f"https://example.com/{i}", source_name="Q",
                published_at=datetime.now(UTC) - timedelta(days=tage_alt),
                sentiment=label,
            )
            for i, label in enumerate(labels)
        ]

    def test_saldo_gegen_handrechnung(self):
        # 3 positiv, 1 negativ, 1 neutral -> (3 - 1) / 5 * 100 = 40
        meldungen = self._eingeordnet(["positiv", "positiv", "positiv", "negativ", "neutral"])
        metrics = compute_sentiment_metrics(meldungen)
        assert metrics["sentiment_balance"].value == pytest.approx(40.0)
        # Anteil positiver Meldungen: 3 / 5 = 60 %
        assert metrics["sentiment_positive_share"].value == pytest.approx(60.0)

    def test_nur_negative_meldungen(self):
        metrics = compute_sentiment_metrics(self._eingeordnet(["negativ"] * 4))
        assert metrics["sentiment_balance"].value == pytest.approx(-100.0)

    def test_zu_wenige_meldungen_ergeben_keinen_saldo(self):
        """Ein Saldo aus zwei Meldungen waere Rauschen."""
        metrics = compute_sentiment_metrics(self._eingeordnet(["positiv", "positiv"]))
        assert not metrics["sentiment_balance"].is_available
        assert str(MIN_CLASSIFIED) in metrics["sentiment_balance"].missing_reason

    def test_ohne_meldungen(self):
        metrics = compute_sentiment_metrics([])
        assert metrics["news_count"].value == 0
        assert metrics["sentiment_balance"].missing_reason == MISSING_NO_NEWS

    def test_ohne_schluessel_wird_der_grund_genannt(self):
        meldungen = news(5)  # vorhanden, aber nicht eingeordnet
        metrics = compute_sentiment_metrics(meldungen, key_available=False)
        assert metrics["news_count"].value == 5
        assert metrics["sentiment_classified_count"].value == 0
        assert metrics["sentiment_balance"].missing_reason == MISSING_NOT_CLASSIFIED

    def test_unbewertete_meldungen_zaehlen_nicht_mit(self):
        gemischt = self._eingeordnet(["positiv", "positiv", "positiv"]) + news(5)
        metrics = compute_sentiment_metrics(gemischt)
        assert metrics["news_count"].value == 8
        assert metrics["sentiment_classified_count"].value == 3
        # Saldo nur ueber die drei eingeordneten: (3 - 0) / 3 = 100
        assert metrics["sentiment_balance"].value == pytest.approx(100.0)

    def test_aktueller_saldo_beruecksichtigt_nur_die_letzten_tage(self):
        alt = self._eingeordnet(["negativ"] * 4, tage_alt=30)
        neu = self._eingeordnet(["positiv"] * 3, tage_alt=2)
        metrics = compute_sentiment_metrics(alt + neu)
        # Gesamt: (3 - 4) / 7 = -14.3 ; letzte 7 Tage: (3 - 0) / 3 = 100
        assert metrics["sentiment_balance"].value == pytest.approx(-14.29, abs=0.1)
        assert metrics["sentiment_balance_7d"].value == pytest.approx(100.0)

    def test_zu_wenige_aktuelle_meldungen(self):
        metrics = compute_sentiment_metrics(self._eingeordnet(["positiv"] * 5, tage_alt=30))
        assert metrics["sentiment_balance"].is_available
        assert not metrics["sentiment_balance_7d"].is_available

    def test_alle_kennzahlen_sind_als_berechnet_markiert(self):
        metrics = compute_sentiment_metrics(self._eingeordnet(["positiv"] * 4))
        assert all(m.is_computed for m in metrics)
