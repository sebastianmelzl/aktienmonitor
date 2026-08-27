"""Kostenmodell und Besteuerung fuer deutsche Privatanleger.

Reine Rechenlogik, ohne Netz und ohne Oberflaeche.

**Quellen und Stand der Voreinstellungen**

- Trade Republic: keine Depotgebuehr, keine Ordergebuehr, 1 EUR
  Fremdkostenpauschale je Order; Ausfuehrung eines Sparplans kostenlos;
  2 EUR bei eigener Wahl des Handelsplatzes.
- Abgeltungsteuer: 25 % Kapitalertragsteuer zuzueglich 5,5 % Solidaritaets-
  zuschlag darauf (zusammen 26,375 %), zuzueglich Kirchensteuer von 8 % oder
  9 % auf die Kapitalertragsteuer, sofern kirchensteuerpflichtig.
- Sparerpauschbetrag: 1.000 EUR je Person und Jahr, 2.000 EUR bei
  Zusammenveranlagung.
- Teilfreistellung nach § 20 InvStG: bei Fonds mit dauerhaft mehr als 50 %
  Kapitalbeteiligungen sind 30 % der Ertraege steuerfrei.

Diese Angaben aendern sich mit der Gesetzeslage und den Konditionen des
Brokers. Sie sind deshalb Vorgabewerte, keine feste Wahrheit.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Voreinstellungen --------------------------------------------------------

TR_ORDER_FEE = 1.00
TR_ORDER_FEE_CHOSEN_VENUE = 2.00
TR_SAVINGS_PLAN_FEE = 0.00

KEST_RATE = 0.25
SOLI_RATE = 0.055
CHURCH_TAX_RATES = {"keine": 0.0, "8 % (BY, BW)": 0.08, "9 % (uebrige Laender)": 0.09}

ALLOWANCE_SINGLE = 1_000.0
ALLOWANCE_JOINT = 2_000.0

EQUITY_FUND_EXEMPTION = 0.30

# Handelsspanne als Anteil des Kurses. Innerhalb der Haupthandelszeiten sind
# liquide Werte eng; ausserhalb weitet sich die Spanne deutlich. Der Vorgabewert
# ist eine vorsichtige Annahme fuer liquide Titel zur Handelszeit.
DEFAULT_SPREAD_BPS = 10.0


@dataclass(frozen=True)
class BrokerCosts:
    """Handelskosten eines Brokers."""

    order_fee: float = TR_ORDER_FEE
    # Halbe Spanne, denn beim Kauf zahlt man ueblicherweise den Briefkurs.
    spread_bps: float = DEFAULT_SPREAD_BPS
    savings_plan_fee: float = TR_SAVINGS_PLAN_FEE
    name: str = "Trade Republic"

    def order_cost(self, amount: float, *, savings_plan: bool = False) -> float:
        """Kosten einer einzelnen Order ueber ``amount``."""
        if amount <= 0:
            return 0.0
        gebuehr = self.savings_plan_fee if savings_plan else self.order_fee
        spanne = amount * (self.spread_bps / 10_000.0) / 2.0
        return gebuehr + spanne

    def total_cost(
        self, amounts: list[float], *, savings_plan: bool = False
    ) -> float:
        """Kosten fuer mehrere Positionen - je Position faellt eine Order an."""
        return sum(self.order_cost(a, savings_plan=savings_plan) for a in amounts)

    def cost_share(self, amounts: list[float], *, savings_plan: bool = False) -> float | None:
        """Kosten als Anteil des eingesetzten Betrags, in Prozent."""
        gesamt = sum(a for a in amounts if a > 0)
        if gesamt <= 0:
            return None
        return self.total_cost(amounts, savings_plan=savings_plan) / gesamt * 100.0


@dataclass(frozen=True)
class TaxSettings:
    """Besteuerung von Kapitalertraegen."""

    church_tax_rate: float = 0.0
    joint_assessment: bool = False
    # Wie viel des Sparerpauschbetrags in diesem Jahr bereits verbraucht ist.
    allowance_used: float = 0.0
    # Greift bei Aktienfonds und Aktien-ETFs, nicht bei Einzelaktien.
    equity_fund: bool = False

    @property
    def allowance(self) -> float:
        return ALLOWANCE_JOINT if self.joint_assessment else ALLOWANCE_SINGLE

    @property
    def allowance_left(self) -> float:
        return max(0.0, self.allowance - max(0.0, self.allowance_used))

    @property
    def effective_rate(self) -> float:
        """Gesamtsteuersatz auf steuerpflichtige Ertraege.

        Solidaritaetszuschlag und Kirchensteuer bemessen sich an der
        Kapitalertragsteuer, nicht am Ertrag.
        """
        return KEST_RATE * (1.0 + SOLI_RATE + self.church_tax_rate)

    def taxable_share(self) -> float:
        """Anteil des Ertrags, der ueberhaupt steuerpflichtig ist."""
        return (1.0 - EQUITY_FUND_EXEMPTION) if self.equity_fund else 1.0


@dataclass(frozen=True)
class TaxResult:
    """Aufschluesselung der Steuer auf einen Gewinn."""

    gross_gain: float
    exempt_by_fund_rule: float
    covered_by_allowance: float
    taxable: float
    tax: float

    @property
    def net_gain(self) -> float:
        return self.gross_gain - self.tax

    @property
    def effective_burden(self) -> float | None:
        """Tatsaechliche Belastung des Bruttogewinns, in Prozent."""
        if self.gross_gain <= 0:
            return None
        return self.tax / self.gross_gain * 100.0


def tax_on_gain(gain: float, settings: TaxSettings | None = None) -> TaxResult:
    """Berechnet die Abgeltungsteuer auf einen realisierten Gewinn.

    Verluste ergeben keine Steuer; eine Verrechnung mit anderen Ertraegen
    bildet das Modell bewusst nicht ab - das haengt an Verlustverrechnungstoepfen
    und der uebrigen Anlagesituation.
    """
    rules = settings or TaxSettings()
    if gain <= 0:
        return TaxResult(gain, 0.0, 0.0, 0.0, 0.0)

    steuerfrei_fonds = gain * (1.0 - rules.taxable_share())
    nach_teilfreistellung = gain - steuerfrei_fonds

    durch_freibetrag = min(nach_teilfreistellung, rules.allowance_left)
    steuerpflichtig = max(0.0, nach_teilfreistellung - durch_freibetrag)
    steuer = steuerpflichtig * rules.effective_rate

    return TaxResult(
        gross_gain=gain,
        exempt_by_fund_rule=steuerfrei_fonds,
        covered_by_allowance=durch_freibetrag,
        taxable=steuerpflichtig,
        tax=steuer,
    )


def break_even_return(
    amount: float, costs: BrokerCosts, *, savings_plan: bool = False
) -> float | None:
    """Welche Rendite noetig ist, um die Kosten einer Position hereinzuholen.

    Beruecksichtigt Kauf *und* spaeteren Verkauf - beides kostet.
    """
    if amount <= 0:
        return None
    hin_und_zurueck = costs.order_cost(amount, savings_plan=savings_plan) + costs.order_cost(
        amount, savings_plan=False
    )
    return hin_und_zurueck / amount * 100.0


def cost_warning(amount: float, positions: int, costs: BrokerCosts) -> str | None:
    """Warnt, wenn die Kosten im Verhaeltnis zum Betrag ins Gewicht fallen.

    Die Schwelle von einem Prozent ist bewusst niedrig: sie entspricht in etwa
    dem, was eine breite Indexanlage pro Jahr an laufenden Kosten hat.
    """
    if amount <= 0 or positions <= 0:
        return None
    je_position = amount / positions
    anteil = costs.cost_share([je_position] * positions)
    if anteil is None:
        return None
    if anteil >= 1.0:
        return (
            f"Die Kaufkosten betragen {anteil:.2f} % des Betrags "
            f"({costs.total_cost([je_position] * positions):.2f} bei {positions} Positionen). "
            f"Bei {je_position:.0f} je Position faellt die Gebuehr spuerbar ins Gewicht - "
            "weniger Positionen oder ein groesserer Betrag senken den Anteil."
        )
    return None
