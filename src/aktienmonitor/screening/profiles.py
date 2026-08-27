"""Suchprofile fuer die marktweite Vorauswahl.

Die Profile stehen als Daten und nicht als Code: so lassen sie sich in der
Oberflaeche anzeigen, veraendern und einzeln pruefen - ohne yfinance zu
importieren. Die Uebersetzung in die Abfragesprache des Anbieters passiert im
Provider.

**Wichtiger Vorbehalt zu den Einheiten:** Welche Einheit ein Yahoo-Screenerfeld
erwartet (Prozent oder Anteil, absolut oder in Millionen), ist nicht
dokumentiert und liess sich in der Entwicklungsumgebung nicht pruefen - dort
gab es keinen Netzzugang. Die hinterlegten Werte sind begruendete Annahmen.
Die Oberflaeche zeigt deshalb die Trefferzahl an: null Treffer oder das
Maximum von 250 deuten auf eine falsche Einheit hin, nicht auf den Markt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# Obergrenze der Marktabfrage je Lauf (Vorgabe des Anbieters).
MAX_RESULTS = 250

# Regionscodes des Yahoo-Screeners mit deutscher Anzeigebezeichnung - von
# mehreren Oberflaechenseiten genutzt, deshalb hier statt in einer View.
REGIONS: dict[str, str] = {
    "de": "Deutschland", "at": "Oesterreich", "ch": "Schweiz", "fr": "Frankreich",
    "nl": "Niederlande", "gb": "Grossbritannien", "us": "USA", "ca": "Kanada",
    "se": "Schweden", "dk": "Daenemark", "fi": "Finnland", "it": "Italien",
    "es": "Spanien", "jp": "Japan",
}


class Comparison(StrEnum):
    GREATER = "gt"
    LESS = "lt"
    BETWEEN = "btwn"
    EQUALS = "eq"


@dataclass(frozen=True)
class Criterion:
    """Eine einzelne Filterbedingung."""

    field_name: str
    comparison: Comparison
    value: float | str | tuple[float, float]
    label: str
    # Wofuer die Bedingung steht - wird in der Oberflaeche angezeigt.
    rationale: str = ""

    def describe(self) -> str:
        if self.comparison is Comparison.BETWEEN and isinstance(self.value, tuple):
            return f"{self.label} zwischen {self.value[0]:g} und {self.value[1]:g}"
        if self.comparison is Comparison.GREATER:
            return f"{self.label} ueber {self.value:g}"
        if self.comparison is Comparison.LESS:
            return f"{self.label} unter {self.value:g}"
        return f"{self.label} = {self.value}"


@dataclass(frozen=True)
class SearchProfile:
    """Ein benanntes Buendel von Filterkriterien."""

    key: str
    name: str
    description: str
    criteria: tuple[Criterion, ...]
    # Feld, nach dem der Anbieter sortieren soll.
    sort_field: str = "intradaymarketcap"
    sort_ascending: bool = False

    def describe(self) -> list[str]:
        return [c.describe() for c in self.criteria]


# --- Feldnamen des Yahoo-Screeners ------------------------------------------
# Ausgelesen aus yfinance.const.EQUITY_SCREENER_FIELDS.
FIELD_MARKET_CAP = "intradaymarketcap"
FIELD_PE = "peratio.lasttwelvemonths"
FIELD_PB = "pricebookratio.quarterly"
FIELD_PEG = "pegratio_5y"
FIELD_ROE = "returnonequity.lasttwelvemonths"
FIELD_GROSS_MARGIN = "grossprofitmargin.lasttwelvemonths"
FIELD_NET_MARGIN = "netincomemargin.lasttwelvemonths"
FIELD_REVENUE_GROWTH = "totalrevenues1yrgrowth.lasttwelvemonths"
FIELD_DEBT_EBITDA = "totaldebtebitda.lasttwelvemonths"
FIELD_CURRENT_RATIO = "currentratio.lasttwelvemonths"
FIELD_DIVIDEND_YIELD = "dividendyield"
FIELD_DIVIDEND_STREAK = "consecutive_years_of_dividend_growth_count"
FIELD_REGION = "region"
FIELD_SECTOR = "sector"


PROFILES: tuple[SearchProfile, ...] = (
    SearchProfile(
        key="dividende",
        name="Solide Dividende",
        description=(
            "Titel mit auskoemmlicher Ausschuettung, die sie seit Jahren steigern und "
            "deren Bilanz das traegt. Die Verschuldungsgrenze soll ausschliessen, dass "
            "die Dividende aus der Substanz kommt."
        ),
        criteria=(
            Criterion(FIELD_DIVIDEND_YIELD, Comparison.BETWEEN, (2.0, 8.0),
                      "Dividendenrendite",
                      "Untergrenze fuer Auskoemmlichkeit, Obergrenze weil sehr hohe "
                      "Renditen meist aus gefallenen Kursen stammen"),
            Criterion(FIELD_DIVIDEND_STREAK, Comparison.GREATER, 4,
                      "Jahre in Folge steigende Dividende",
                      "Zeigt, dass die Ausschuettung mehrere Zyklen ueberstanden hat"),
            Criterion(FIELD_DEBT_EBITDA, Comparison.LESS, 3.0,
                      "Verschuldung / EBITDA",
                      "Begrenzt, wie stark die Bilanz die Ausschuettung stuetzen muss"),
            Criterion(FIELD_CURRENT_RATIO, Comparison.GREATER, 1.0,
                      "Current Ratio",
                      "Kurzfristige Zahlungsfaehigkeit gegeben"),
        ),
        sort_field=FIELD_DIVIDEND_YIELD,
    ),
    SearchProfile(
        key="guenstig",
        name="Guenstig bewertet",
        description=(
            "Niedrige Bewertung bei ordentlicher Rentabilitaet. Die Rentabilitaetshuerde "
            "soll verhindern, dass nur Titel gefunden werden, die aus gutem Grund "
            "billig sind."
        ),
        criteria=(
            Criterion(FIELD_PE, Comparison.BETWEEN, (0.0, 15.0), "KGV",
                      "Untergrenze null schliesst Verlustfirmen aus"),
            Criterion(FIELD_PB, Comparison.LESS, 2.5, "KBV", "Niedriger Buchwertaufschlag"),
            Criterion(FIELD_ROE, Comparison.GREATER, 10.0, "Eigenkapitalrendite",
                      "Mindestrentabilitaet - sonst ist billig nur billig"),
        ),
        sort_field=FIELD_PE,
        sort_ascending=True,
    ),
    SearchProfile(
        key="qualitaet",
        name="Qualitaet",
        description=(
            "Hohe Rentabilitaet, gute Marge, wenig Schulden - ohne Ruecksicht auf die "
            "Bewertung. Solche Titel sind selten guenstig; das Profil sucht nicht danach."
        ),
        criteria=(
            Criterion(FIELD_ROE, Comparison.GREATER, 15.0, "Eigenkapitalrendite",
                      "Deutlich ueber ueblichen Kapitalkosten"),
            Criterion(FIELD_GROSS_MARGIN, Comparison.GREATER, 35.0, "Bruttomarge",
                      "Hinweis auf Preissetzungsmacht"),
            Criterion(FIELD_DEBT_EBITDA, Comparison.LESS, 2.5, "Verschuldung / EBITDA",
                      "Bilanz traegt auch schwaechere Jahre"),
        ),
        sort_field=FIELD_ROE,
    ),
    SearchProfile(
        key="wachstum",
        name="Wachstum zu vernuenftigem Preis",
        description=(
            "Wachsende Umsaetze, die nicht bereits vollstaendig bezahlt sind. Die "
            "Margenhuerde schliesst Wachstum ohne Ertrag aus."
        ),
        criteria=(
            Criterion(FIELD_REVENUE_GROWTH, Comparison.GREATER, 10.0, "Umsatzwachstum",
                      "Spuerbares Wachstum im letzten Geschaeftsjahr"),
            Criterion(FIELD_PEG, Comparison.BETWEEN, (0.0, 2.0), "PEG",
                      "Bewertung im Verhaeltnis zum Wachstum"),
            Criterion(FIELD_NET_MARGIN, Comparison.GREATER, 5.0, "Nettomarge",
                      "Wachstum muss beim Ergebnis ankommen"),
        ),
        sort_field=FIELD_REVENUE_GROWTH,
    ),
)

PROFILES_BY_KEY = {profile.key: profile for profile in PROFILES}


@dataclass(frozen=True)
class ScreenRequest:
    """Ein konkreter Suchauftrag: Profil plus Eingrenzung durch den Nutzer."""

    profile: SearchProfile
    regions: tuple[str, ...] = ("de",)
    sectors: tuple[str, ...] = ()
    min_market_cap: float = 1_000_000_000.0
    limit: int = 50

    def all_criteria(self) -> list[Criterion]:
        """Profilkriterien plus die Eingrenzungen des Nutzers."""
        criteria = list(self.profile.criteria)
        criteria.append(
            Criterion(
                FIELD_MARKET_CAP, Comparison.GREATER, self.min_market_cap,
                "Marktkapitalisierung",
                "Untergrenze haelt sehr kleine und marktenge Titel heraus",
            )
        )
        return criteria

    def describe(self) -> list[str]:
        zeilen = self.profile.describe()
        zeilen.append(f"Marktkapitalisierung ueber {self.min_market_cap:,.0f}".replace(",", "."))
        if self.regions:
            zeilen.append("Region: " + ", ".join(r.upper() for r in self.regions))
        if self.sectors:
            zeilen.append("Branche: " + ", ".join(self.sectors))
        return zeilen


@dataclass(frozen=True)
class ScreenHit:
    """Ein Treffer der Marktabfrage - bewusst sparsam.

    Die Marktabfrage liefert nur eine Vorauswahl. Die eigentliche Bewertung
    entsteht danach aus dem vollstaendigen Kennzahlensatz, nicht aus diesen
    Feldern.
    """

    ticker: str
    name: str | None = None
    sector: str | None = None
    exchange: str | None = None
    market_cap: float | None = None
    raw: dict = field(default_factory=dict)


def parse_hits(payload: object) -> list[ScreenHit]:
    """Liest die Trefferliste aus der Antwort der Marktabfrage.

    Defensiv gehalten: verlaesslich ist allein das Symbol. Alle uebrigen Felder
    dienen nur der Anzeige und duerfen fehlen.
    """
    if not isinstance(payload, dict):
        return []
    quotes = payload.get("quotes")
    if not isinstance(quotes, list):
        return []

    hits: list[ScreenHit] = []
    for quote in quotes:
        if not isinstance(quote, dict):
            continue
        symbol = str(quote.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        market_cap = quote.get("marketCap")
        hits.append(
            ScreenHit(
                ticker=symbol,
                name=(quote.get("longName") or quote.get("shortName") or None),
                sector=quote.get("sector") or None,
                exchange=quote.get("fullExchangeName") or quote.get("exchange") or None,
                market_cap=float(market_cap)
                if isinstance(market_cap, int | float) and not isinstance(market_cap, bool)
                else None,
                raw=quote,
            )
        )
    return hits


def diagnose_result_count(count: int, limit: int) -> str | None:
    """Weist auf Trefferzahlen hin, die eher auf einen Fehler als auf den Markt deuten.

    Die Einheiten der Screenerfelder sind nicht dokumentiert. Null Treffer oder
    ein Anschlagen an der Obergrenze sind das erwartbare Symptom einer falsch
    angenommenen Einheit.
    """
    if count == 0:
        return (
            "Kein Treffer. Das kann am Markt liegen - haeufiger liegt es daran, dass "
            "ein Schwellenwert in der falschen Einheit angegeben ist (Prozent statt "
            "Anteil oder umgekehrt). Bitte die Kriterien schrittweise lockern."
        )
    if count >= min(limit, MAX_RESULTS):
        return (
            f"Die Obergrenze von {count} Treffern wurde erreicht - es gibt also mehr. "
            "Die Auswahl ist damit vom Sortierfeld abhaengig und nicht vollstaendig. "
            "Fuer ein belastbares Ergebnis die Kriterien verschaerfen."
        )
    return None
