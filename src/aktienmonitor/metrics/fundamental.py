"""Fundamentale Kennzahlen.

Quellenlage: Werte, die eine Datenquelle fertig liefert, werden uebernommen und
mit ihrer Herkunft gekennzeichnet. Alles, was aus Bilanz, GuV oder Cashflow
abgeleitet wird, ist als "berechnet" markiert und fuehrt seine Eingangsgroessen
mit. Nicht ermittelbare Kennzahlen bleiben "n/a" mit Begruendung.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..models import (
    MISSING_DIVISION_UNDEFINED,
    MISSING_INPUT,
    MISSING_INSUFFICIENT_HISTORY,
    MISSING_NOT_APPLICABLE,
    MISSING_NOT_PROVIDED,
    UNIT_COUNT,
    UNIT_CURRENCY,
    UNIT_PERCENT,
    UNIT_RATIO,
    MetricSet,
    MetricValue,
    Provenance,
    SecurityProfile,
)
from .statements import (
    CAPEX,
    CASH,
    CURRENT_ASSETS,
    CURRENT_LIABILITIES,
    DILUTED_SHARES,
    EBIT,
    EBITDA,
    FREE_CASH_FLOW,
    GROSS_PROFIT,
    INVESTED_CAPITAL,
    NET_INCOME,
    OPERATING_CASH_FLOW,
    OPERATING_INCOME,
    PRETAX_INCOME,
    REVENUE,
    SHARES_ISSUED,
    TAX_PROVISION,
    TAX_RATE,
    TOTAL_ASSETS,
    TOTAL_DEBT,
    TOTAL_EQUITY,
    Series,
    Statements,
)

# Toleranz beim Suchen eines Vergleichsjahres fuer Wachstumsraten (in Tagen).
PERIOD_TOLERANCE_DAYS = 200


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    """Division, die bei fehlenden Werten oder Nenner null ``None`` liefert."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def cagr(series: Series, years: int) -> float | None:
    """Jaehrliche Wachstumsrate ueber ``years`` Jahre, in Prozent.

    Voraussetzung ist ein *positiver* Ausgangswert: aus einem Verlust heraus ist
    eine Wachstumsrate mathematisch nicht definiert. In dem Fall wird bewusst
    ``None`` zurueckgegeben statt einer irrefuehrenden Zahl.
    """
    if len(series) < 2 or years < 1:
        return None
    end_date, end_value = series[-1]
    target = end_date.replace(tzinfo=None) - _years_as_timedelta(years)

    best: tuple[float, float] | None = None  # (Abstand in Tagen, Wert)
    for stamp, value in series[:-1]:
        distance = abs((stamp.replace(tzinfo=None) - target).days)
        if distance <= PERIOD_TOLERANCE_DAYS and (best is None or distance < best[0]):
            best = (float(distance), value)
    if best is None:
        return None

    start_value = best[1]
    if start_value <= 0 or end_value <= 0:
        return None
    return float(((end_value / start_value) ** (1.0 / years) - 1.0) * 100.0)


def _years_as_timedelta(years: int):
    from datetime import timedelta

    return timedelta(days=round(365.25 * years))


class _Builder:
    """Hilfsklasse, die Kennzahlen einheitlich mit Herkunft ablegt."""

    def __init__(self, as_of: datetime) -> None:
        self.metrics: dict[str, MetricValue] = {}
        self.as_of = as_of

    def add(
        self,
        key: str,
        label: str,
        value: float | None,
        *,
        unit: str = UNIT_RATIO,
        source: Provenance,
        computed: bool = False,
        inputs: tuple[str, ...] = (),
        reason: str = MISSING_NOT_PROVIDED,
    ) -> None:
        if value is None:
            self.metrics[key] = MetricValue.missing(
                key, label, unit=unit, reason=reason, source=source,
                is_computed=computed, inputs=inputs,
            )
            return
        self.metrics[key] = MetricValue(
            key=key, label=label, value=float(value), unit=unit, source=source,
            as_of=self.as_of, is_computed=computed, inputs=inputs,
        )

    def add_text(
        self, key: str, label: str, text: str | None, *, source: Provenance, unit: str,
        reason: str = MISSING_NOT_PROVIDED,
    ) -> None:
        if not text:
            self.metrics[key] = MetricValue.missing(key, label, unit=unit, reason=reason, source=source)
            return
        self.metrics[key] = MetricValue(
            key=key, label=label, text=text, unit=unit, source=source, as_of=self.as_of
        )


def _info_value(info: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = info.get(key)
        if isinstance(value, int | float):
            return float(value)
    return None


def _finnhub_value(metric: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = metric.get(key)
        if isinstance(value, int | float):
            return float(value)
    return None


def _pick(
    *candidates: tuple[float | None, Provenance],
) -> tuple[float | None, Provenance]:
    """Waehlt den ersten *vorhandenen* Wert samt Quelle.

    Bewusst nicht ueber ``or`` geloest: ein echter Wert von 0.0 (etwa eine
    Bruttomarge von genau null) ist ein Wert und darf nicht als fehlend gelten.
    """
    for value, source in candidates:
        if value is not None:
            return value, source
    return None, candidates[0][1] if candidates else Provenance.UNKNOWN


def _first(*values: float | None) -> float | None:
    """Erster nicht fehlender Wert - dieselbe Begruendung wie bei ``_pick``."""
    for value in values:
        if value is not None:
            return value
    return None


def _as_percent(value: float | None) -> float | None:
    """yfinance liefert Quoten als Anteil (0.35) - wir rechnen in Prozentpunkten."""
    return None if value is None else value * 100.0


def compute_fundamental_metrics(
    *,
    info: dict[str, Any] | None,
    statements_payload: dict[str, Any] | None,
    profile: SecurityProfile | None = None,
    finnhub_metric: dict[str, Any] | None = None,
    as_of: datetime | None = None,
) -> MetricSet:
    """Berechnet alle fundamentalen Kennzahlen eines Titels."""
    info = info or {}
    finnhub_metric = finnhub_metric or {}
    statements = Statements(statements_payload)
    builder = _Builder(as_of or datetime.now(UTC))
    is_fund = profile.is_fund if profile is not None else False

    yf = Provenance.YFINANCE
    fh = Provenance.FINNHUB

    # Bei Fonds und ETFs existieren Unternehmenskennzahlen nicht - sie werden
    # als "nicht anwendbar" gefuehrt, nicht als "Datenquelle liefert nichts".
    fund_reason = MISSING_NOT_APPLICABLE if is_fund else MISSING_NOT_PROVIDED

    # --- Groesse ------------------------------------------------------------
    market_cap = _info_value(info, "marketCap")
    if market_cap is None:
        # Finnhub gibt die Marktkapitalisierung in Millionen an.
        finnhub_cap = _finnhub_value(finnhub_metric, "marketCapitalization")
        if finnhub_cap is not None:
            builder.add(
                "market_cap", "Marktkapitalisierung", finnhub_cap * 1_000_000,
                unit=UNIT_CURRENCY, source=fh,
            )
        else:
            builder.add("market_cap", "Marktkapitalisierung", None, unit=UNIT_CURRENCY, source=yf)
    else:
        builder.add("market_cap", "Marktkapitalisierung", market_cap, unit=UNIT_CURRENCY, source=yf)

    shares = _info_value(info, "sharesOutstanding")
    builder.add("shares_outstanding", "Anzahl Aktien", shares, unit=UNIT_COUNT, source=yf)

    # Verwaesserung bzw. Rueckkaeufe: Veraenderung der verwaesserten Aktienzahl.
    shares_series = statements.income.series(*DILUTED_SHARES) or statements.balance.series(*SHARES_ISSUED)
    share_change = None
    if len(shares_series) >= 2 and shares_series[-2][1] > 0:
        share_change = (shares_series[-1][1] / shares_series[-2][1] - 1.0) * 100.0
    builder.add(
        "share_count_change_1y", "Veraenderung Aktienzahl (1 J.)", share_change,
        unit=UNIT_PERCENT, source=yf, computed=True,
        inputs=("Verwaesserte Aktienzahl (GuV)",),
        reason=MISSING_INSUFFICIENT_HISTORY if is_fund is False else fund_reason,
    )

    # --- Bewertung ----------------------------------------------------------
    pe_value, pe_source = _pick(
        (_info_value(info, "trailingPE"), yf), (_finnhub_value(finnhub_metric, "peTTM"), fh)
    )
    builder.add("pe_trailing", "KGV (aktuell)", pe_value, source=pe_source, reason=fund_reason)
    builder.add(
        "pe_forward", "KGV (forward)", _info_value(info, "forwardPE"), source=yf, reason=fund_reason
    )
    ps_value, ps_source = _pick(
        (_info_value(info, "priceToSalesTrailing12Months"), yf),
        (_finnhub_value(finnhub_metric, "psTTM"), fh),
    )
    builder.add("ps", "KUV", ps_value, source=ps_source, reason=fund_reason)
    pb_value, pb_source = _pick(
        (_info_value(info, "priceToBook"), yf), (_finnhub_value(finnhub_metric, "pbAnnual"), fh)
    )
    builder.add("pb", "KBV", pb_value, source=pb_source, reason=fund_reason)

    # PEG: bevorzugt der gelieferte Wert, sonst aus KGV und Gewinnwachstum.
    peg = _info_value(info, "trailingPegRatio")
    if peg is not None:
        builder.add("peg", "PEG", peg, source=yf, reason=fund_reason)
    else:
        pe = _info_value(info, "trailingPE")
        growth = _as_percent(_info_value(info, "earningsGrowth"))
        computed_peg = None if growth is None or growth <= 0 else safe_div(pe, growth)
        builder.add(
            "peg", "PEG", computed_peg, source=yf, computed=True,
            inputs=("KGV (aktuell)", "Gewinnwachstum"),
            reason=MISSING_DIVISION_UNDEFINED if growth is not None and growth <= 0 else fund_reason,
        )

    # EV/EBITDA: gelieferter Wert, sonst aus Enterprise Value und EBITDA.
    ev_ebitda = _info_value(info, "enterpriseToEbitda")
    if ev_ebitda is not None:
        builder.add("ev_ebitda", "EV/EBITDA", ev_ebitda, source=yf, reason=fund_reason)
    else:
        enterprise_value = _info_value(info, "enterpriseValue")
        ebitda = _first(_info_value(info, "ebitda"), statements.income.latest(*EBITDA))
        builder.add(
            "ev_ebitda", "EV/EBITDA",
            None if (ebitda is None or ebitda <= 0) else safe_div(enterprise_value, ebitda),
            source=yf, computed=True, inputs=("Enterprise Value", "EBITDA"),
            reason=fund_reason if enterprise_value is None else MISSING_DIVISION_UNDEFINED,
        )

    # --- Rentabilitaet ------------------------------------------------------
    roe_value, roe_source = _pick(
        (_as_percent(_info_value(info, "returnOnEquity")), yf),
        (_finnhub_value(finnhub_metric, "roeTTM"), fh),
    )
    builder.add(
        "roe", "Eigenkapitalrendite (ROE)", roe_value, unit=UNIT_PERCENT,
        source=roe_source, reason=fund_reason,
    )

    roic = _compute_roic(statements)
    builder.add(
        "roic", "Kapitalrendite (ROIC)", roic, unit=UNIT_PERCENT, source=yf, computed=True,
        inputs=("EBIT", "Steuerquote", "Investiertes Kapital"),
        reason=fund_reason if is_fund else MISSING_INPUT,
    )

    for key, label, info_key, finnhub_key, aliases_num, aliases_den in (
        ("gross_margin", "Bruttomarge", "grossMargins", "grossMarginTTM", GROSS_PROFIT, REVENUE),
        (
            "operating_margin", "Operative Marge", "operatingMargins", "operatingMarginTTM",
            OPERATING_INCOME, REVENUE,
        ),
        ("net_margin", "Nettomarge", "profitMargins", "netProfitMarginTTM", NET_INCOME, REVENUE),
    ):
        supplied = _as_percent(_info_value(info, info_key))
        if supplied is not None:
            builder.add(key, label, supplied, unit=UNIT_PERCENT, source=yf, reason=fund_reason)
            continue
        from_finnhub = _finnhub_value(finnhub_metric, finnhub_key)
        if from_finnhub is not None:
            builder.add(key, label, from_finnhub, unit=UNIT_PERCENT, source=fh, reason=fund_reason)
            continue
        derived = safe_div(statements.income.latest(*aliases_num), statements.income.latest(*aliases_den))
        builder.add(
            key, label, None if derived is None else derived * 100.0, unit=UNIT_PERCENT,
            source=yf, computed=True, inputs=("GuV",), reason=fund_reason,
        )

    # --- Wachstum -----------------------------------------------------------
    revenue_series = statements.income.series(*REVENUE)
    earnings_series = statements.income.series(*NET_INCOME)
    for years in (1, 3, 5):
        builder.add(
            f"revenue_growth_{years}y", f"Umsatzwachstum ({years} J. p.a.)",
            cagr(revenue_series, years), unit=UNIT_PERCENT, source=yf, computed=True,
            inputs=("Umsatzreihe (GuV)",),
            reason=fund_reason if is_fund else MISSING_INSUFFICIENT_HISTORY,
        )
        builder.add(
            f"earnings_growth_{years}y", f"Gewinnwachstum ({years} J. p.a.)",
            cagr(earnings_series, years), unit=UNIT_PERCENT, source=yf, computed=True,
            inputs=("Nettoergebnisreihe (GuV)",),
            reason=fund_reason if is_fund else MISSING_INSUFFICIENT_HISTORY,
        )

    # --- Cashflow -----------------------------------------------------------
    free_cash_flow = statements.cashflow.latest(*FREE_CASH_FLOW)
    fcf_computed = False
    if free_cash_flow is None:
        operating = statements.cashflow.latest(*OPERATING_CASH_FLOW)
        capex = statements.cashflow.latest(*CAPEX)
        if operating is not None and capex is not None:
            # Capex steht bei Yahoo als negative Zahl in der Kapitalflussrechnung.
            free_cash_flow = operating + capex
            fcf_computed = True
    if free_cash_flow is None:
        free_cash_flow = _info_value(info, "freeCashflow")

    builder.add(
        "free_cash_flow", "Free Cashflow", free_cash_flow, unit=UNIT_CURRENCY, source=yf,
        computed=fcf_computed, inputs=("Operativer Cashflow", "Investitionen") if fcf_computed else (),
        reason=fund_reason,
    )

    revenue_latest = _first(statements.income.latest(*REVENUE), _info_value(info, "totalRevenue"))
    builder.add(
        "fcf_margin", "FCF-Marge",
        None if (fcf_margin := safe_div(free_cash_flow, revenue_latest)) is None else fcf_margin * 100.0,
        unit=UNIT_PERCENT, source=yf, computed=True, inputs=("Free Cashflow", "Umsatz"),
        reason=fund_reason,
    )

    # --- Bilanzqualitaet ----------------------------------------------------
    total_debt = _first(statements.balance.latest(*TOTAL_DEBT), _info_value(info, "totalDebt"))
    cash = _first(statements.balance.latest(*CASH), _info_value(info, "totalCash"))
    ebitda_value = _first(_info_value(info, "ebitda"), statements.income.latest(*EBITDA))
    net_debt = None if (total_debt is None or cash is None) else total_debt - cash
    builder.add(
        "net_debt_ebitda", "Netto-Verschuldung / EBITDA",
        None if (ebitda_value is None or ebitda_value <= 0) else safe_div(net_debt, ebitda_value),
        source=yf, computed=True, inputs=("Gesamtverschuldung", "Liquide Mittel", "EBITDA"),
        reason=fund_reason if ebitda_value is not None else MISSING_INPUT,
    )

    equity = statements.balance.latest(*TOTAL_EQUITY)
    assets = statements.balance.latest(*TOTAL_ASSETS)
    builder.add(
        "equity_ratio", "Eigenkapitalquote",
        None if (ratio := safe_div(equity, assets)) is None else ratio * 100.0,
        unit=UNIT_PERCENT, source=yf, computed=True, inputs=("Eigenkapital", "Bilanzsumme"),
        reason=fund_reason,
    )

    current_ratio = _first(
        _info_value(info, "currentRatio"), _finnhub_value(finnhub_metric, "currentRatioAnnual")
    )
    if current_ratio is None:
        current_ratio = safe_div(
            statements.balance.latest(*CURRENT_ASSETS), statements.balance.latest(*CURRENT_LIABILITIES)
        )
        builder.add(
            "current_ratio", "Current Ratio", current_ratio, source=yf, computed=True,
            inputs=("Umlaufvermoegen", "Kurzfristige Verbindlichkeiten"), reason=fund_reason,
        )
    else:
        builder.add("current_ratio", "Current Ratio", current_ratio, source=yf, reason=fund_reason)

    # --- Dividende ----------------------------------------------------------
    dividend_yield = _info_value(info, "dividendYield")
    if dividend_yield is not None and dividend_yield < 1.0:
        # yfinance liefert die Rendite je nach Feld als Anteil oder in Prozent.
        dividend_yield *= 100.0
    builder.add(
        "dividend_yield", "Dividendenrendite", dividend_yield, unit=UNIT_PERCENT, source=yf,
        reason=MISSING_NOT_APPLICABLE if dividend_yield is None else MISSING_NOT_PROVIDED,
    )
    builder.add(
        "payout_ratio", "Ausschuettungsquote", _as_percent(_info_value(info, "payoutRatio")),
        unit=UNIT_PERCENT, source=yf, reason=fund_reason,
    )

    years_paid, streak = _dividend_history(statements.dividends)
    builder.add(
        "dividend_years", "Jahre mit Dividendenzahlung", years_paid, unit=UNIT_COUNT,
        source=yf, computed=True, inputs=("Dividendenhistorie",),
        reason=MISSING_NOT_APPLICABLE,
    )
    builder.add(
        "dividend_growth_streak", "Jahre in Folge steigende Dividende", streak, unit=UNIT_COUNT,
        source=yf, computed=True, inputs=("Dividendenhistorie",), reason=MISSING_NOT_APPLICABLE,
    )

    return MetricSet(builder.metrics)


def _compute_roic(statements: Statements) -> float | None:
    """ROIC = NOPAT / investiertes Kapital.

    NOPAT wird als EBIT nach Steuern angesetzt. Die Steuerquote stammt bevorzugt
    aus der von Yahoo gelieferten Groesse, sonst aus Steueraufwand geteilt durch
    Vorsteuerergebnis. Fehlt eine der Groessen, gibt es kein Ergebnis.
    """
    ebit = _first(statements.income.latest(*EBIT), statements.income.latest(*OPERATING_INCOME))
    if ebit is None:
        return None

    tax_rate = statements.income.latest(*TAX_RATE)
    if tax_rate is None:
        pretax = statements.income.latest(*PRETAX_INCOME)
        tax = statements.income.latest(*TAX_PROVISION)
        if pretax is not None and pretax > 0 and tax is not None:
            tax_rate = tax / pretax
    if tax_rate is None or not (0.0 <= tax_rate < 1.0):
        return None

    invested = statements.balance.latest(*INVESTED_CAPITAL)
    if invested is None:
        equity = statements.balance.latest(*TOTAL_EQUITY)
        debt = statements.balance.latest(*TOTAL_DEBT)
        if equity is not None and debt is not None:
            invested = equity + debt
    if invested is None or invested <= 0:
        return None

    return float((ebit * (1.0 - tax_rate)) / invested * 100.0)


def _dividend_history(dividends: dict[str, float]) -> tuple[float | None, float | None]:
    """Anzahl Jahre mit Zahlung und laufende Serie steigender Jahresdividenden."""
    if not dividends:
        return None, None
    per_year: dict[int, float] = {}
    for raw_date, amount in dividends.items():
        try:
            year = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00")).year
        except ValueError:
            continue
        per_year[year] = per_year.get(year, 0.0) + float(amount)
    if not per_year:
        return None, None

    years = sorted(per_year)
    # Das laufende Jahr ist noch unvollstaendig und wuerde die Serie verfaelschen.
    current_year = datetime.now(UTC).year
    complete = [y for y in years if y < current_year]
    if len(complete) < 2:
        return float(len(years)), None

    streak = 0
    for earlier, later in zip(complete, complete[1:], strict=False):
        if per_year[later] > per_year[earlier]:
            streak += 1
        else:
            streak = 0
    return float(len(years)), float(streak)
