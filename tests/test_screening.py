"""Tests der marktweiten Vorauswahl - ohne Netzzugriff.

Die Abfrage selbst laesst sich hier nicht ausfuehren; geprueft wird, dass sie
korrekt gebaut wird, dass die Antwort defensiv gelesen wird und dass
verdaechtige Trefferzahlen benannt werden.
"""

from __future__ import annotations

import pytest

from aktienmonitor.providers.screener import build_query, cache_signature
from aktienmonitor.screening.profiles import (
    FIELD_MARKET_CAP,
    MAX_RESULTS,
    PROFILES,
    PROFILES_BY_KEY,
    Comparison,
    Criterion,
    ScreenRequest,
    diagnose_result_count,
    parse_hits,
)


class TestProfile:
    def test_alle_profile_sind_vollstaendig(self):
        for profile in PROFILES:
            assert profile.key and profile.name
            assert profile.description, f"{profile.key} ohne Beschreibung"
            assert profile.criteria, f"{profile.key} ohne Kriterien"
            for criterion in profile.criteria:
                assert criterion.label, f"{profile.key}/{criterion.field_name} ohne Label"
                assert criterion.rationale, f"{profile.key}/{criterion.field_name} ohne Begruendung"

    def test_schluessel_sind_eindeutig(self):
        keys = [p.key for p in PROFILES]
        assert len(keys) == len(set(keys))

    def test_jedes_profil_hat_eine_qualitaetshuerde(self):
        """Kein Profil darf allein nach Guenstigkeit oder Wachstum suchen.

        Ohne Mindestanforderung an die Qualitaet findet eine marktweite Suche
        vor allem Titel, die aus gutem Grund billig sind.
        """
        qualitaet = {
            "returnonequity.lasttwelvemonths",
            "grossprofitmargin.lasttwelvemonths",
            "netincomemargin.lasttwelvemonths",
            "totaldebtebitda.lasttwelvemonths",
            "currentratio.lasttwelvemonths",
        }
        for profile in PROFILES:
            felder = {c.field_name for c in profile.criteria}
            assert felder & qualitaet, f"{profile.key} ohne Qualitaetskriterium"

    def test_beschreibung_ist_lesbar(self):
        beschreibung = PROFILES_BY_KEY["guenstig"].describe()
        assert any("KGV" in z for z in beschreibung)
        assert any("zwischen" in z for z in beschreibung)


class TestScreenRequest:
    def test_marktkapitalisierung_wird_ergaenzt(self):
        request = ScreenRequest(PROFILES_BY_KEY["qualitaet"], min_market_cap=5e8)
        felder = [c.field_name for c in request.all_criteria()]
        assert FIELD_MARKET_CAP in felder

    def test_beschreibung_nennt_region_und_branche(self):
        request = ScreenRequest(
            PROFILES_BY_KEY["qualitaet"], regions=("de", "us"), sectors=("Technology",)
        )
        text = " ".join(request.describe())
        assert "DE" in text and "US" in text
        assert "Technology" in text


class TestBuildQuery:
    def test_erzeugt_und_verknuepfung(self):
        request = ScreenRequest(PROFILES_BY_KEY["dividende"], regions=("de",))
        payload = build_query(request).to_dict()
        assert payload["operator"] == "AND"
        assert len(payload["operands"]) >= 5

    def test_between_wird_uebersetzt(self):
        request = ScreenRequest(PROFILES_BY_KEY["guenstig"], regions=("us",))
        payload = build_query(request).to_dict()
        btwn = [o for o in payload["operands"] if o.get("operator") == "BTWN"]
        assert btwn, "Das KGV-Kriterium muss als BTWN erscheinen"
        assert btwn[0]["operands"][0] == "peratio.lasttwelvemonths"

    def test_mehrere_regionen_werden_verodert(self):
        request = ScreenRequest(PROFILES_BY_KEY["qualitaet"], regions=("de", "at", "ch"))
        payload = build_query(request).to_dict()
        oder = [o for o in payload["operands"] if o.get("operator") == "OR"]
        assert oder, "Mehrere Regionen muessen als OR erscheinen"

    def test_einzelne_region_wird_gleichgesetzt(self):
        request = ScreenRequest(PROFILES_BY_KEY["qualitaet"], regions=("de",))
        payload = build_query(request).to_dict()
        eq = [
            o for o in payload["operands"]
            if o.get("operator") == "EQ" and o["operands"][0] == "region"
        ]
        assert eq and eq[0]["operands"][1] == "de"

    def test_ungueltiges_feld_wird_vom_anbieter_abgelehnt(self):
        """Die Feldnamen werden von yfinance geprueft - Tippfehler fallen auf."""
        kaputt = ScreenRequest(
            PROFILES_BY_KEY["qualitaet"].__class__(
                key="x", name="X", description="X",
                criteria=(Criterion("gibtesnicht", Comparison.GREATER, 1.0, "X", "X"),),
            )
        )
        with pytest.raises(ValueError):
            build_query(kaputt)


class TestCacheSignature:
    def test_gleiche_anfrage_gleiche_signatur(self):
        a = ScreenRequest(PROFILES_BY_KEY["dividende"], regions=("de", "at"))
        b = ScreenRequest(PROFILES_BY_KEY["dividende"], regions=("at", "de"))
        assert cache_signature(a) == cache_signature(b)

    def test_andere_anfrage_andere_signatur(self):
        a = ScreenRequest(PROFILES_BY_KEY["dividende"], min_market_cap=1e9)
        b = ScreenRequest(PROFILES_BY_KEY["dividende"], min_market_cap=5e9)
        assert cache_signature(a) != cache_signature(b)


class TestParseHits:
    def test_liest_treffer(self):
        payload = {
            "quotes": [
                {"symbol": "sap.de", "longName": "SAP SE", "sector": "Technology",
                 "marketCap": 2.0e11},
                {"symbol": "ALV.DE", "shortName": "Allianz"},
            ]
        }
        hits = parse_hits(payload)
        assert [h.ticker for h in hits] == ["SAP.DE", "ALV.DE"]
        assert hits[0].name == "SAP SE"
        assert hits[0].market_cap == pytest.approx(2.0e11)
        # Fehlende Felder bleiben leer, statt erfunden zu werden.
        assert hits[1].sector is None
        assert hits[1].market_cap is None

    @pytest.mark.parametrize(
        "payload",
        [None, {}, {"quotes": None}, {"quotes": "kaputt"}, {"quotes": [None, 5]},
         {"quotes": [{"kein": "symbol"}]}, {"quotes": [{"symbol": "   "}]}],
    )
    def test_unbrauchbare_antworten_ergeben_leere_liste(self, payload):
        assert parse_hits(payload) == []

    def test_rohdaten_bleiben_erhalten(self):
        hits = parse_hits({"quotes": [{"symbol": "AAPL", "irgendwas": 1}]})
        assert hits[0].raw["irgendwas"] == 1


class TestDiagnose:
    def test_null_treffer_wird_erklaert(self):
        meldung = diagnose_result_count(0, 50)
        assert meldung and "Einheit" in meldung

    def test_obergrenze_wird_gemeldet(self):
        meldung = diagnose_result_count(50, 50)
        assert meldung and "Obergrenze" in meldung

    def test_obergrenze_des_anbieters(self):
        meldung = diagnose_result_count(MAX_RESULTS, 999)
        assert meldung and "Obergrenze" in meldung

    def test_normale_trefferzahl_ohne_hinweis(self):
        assert diagnose_result_count(17, 50) is None
