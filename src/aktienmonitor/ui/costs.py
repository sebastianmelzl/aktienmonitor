"""Darstellung der Handelskosten in der Oberflaeche."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..costs.model import BrokerCosts, break_even_return, cost_warning
from ..formatting import german_number
from ..scoring.allocation import AllocationItem


def render_allocation_costs(items: list[AllocationItem], costs: BrokerCosts | None = None) -> None:
    """Zeigt die Kaufkosten und die Break-Even-Rendite je vorgeschlagener Position.

    Die Ordergebuehr faellt je Position unabhaengig vom Betrag als Fixum an -
    deshalb ist die Break-Even-Rendite bei kleinen Positionen deutlich hoeher
    als bei grossen. Das ist die praktische Konsequenz der Gebuehrenstruktur,
    nicht eine Einschaetzung des Titels.
    """
    if not items:
        return
    costs = costs or BrokerCosts()

    amounts = [item.invested_amount for item in items]
    warnung = cost_warning(sum(amounts), len(items), costs)
    if warnung:
        st.warning(warnung, icon="⚠️")

    table = pd.DataFrame(
        [
            {
                "Ticker": item.ticker,
                "Betrag": german_number(item.invested_amount, 2),
                f"Kosten ({costs.name})": german_number(costs.order_cost(item.invested_amount), 2),
                "Break-Even (Kauf + Verkauf)": (
                    f"{german_number(be, 2)} %"
                    if (be := break_even_return(item.invested_amount, costs)) is not None
                    else "-"
                ),
            }
            for item in items
        ]
    )
    st.dataframe(table, width="stretch", hide_index=True)

    gesamtkosten = costs.total_cost(amounts)
    anteil = costs.cost_share(amounts)
    kpi = st.columns(2)
    kpi[0].metric(f"Kaufkosten gesamt ({costs.name})", german_number(gesamtkosten, 2))
    kpi[1].metric(
        "Anteil am eingesetzten Betrag",
        f"{german_number(anteil, 2)} %" if anteil is not None else "-",
    )
    st.caption(
        f"Kosten fuer {costs.name}: {german_number(costs.order_fee, 2)} Fremdkostenpauschale "
        f"je Order plus die halbe angenommene Handelsspanne "
        f"({costs.spread_bps:.0f} Basispunkte). Sparplaene sind kostenlos - das ist hier "
        "nicht gerechnet, weil die Aufteilung einen Einmalkauf unterstellt. Die Break-Even-"
        "Rendite zaehlt Kauf **und** spaeteren Verkauf, weil beides eine Order ist."
    )


__all__ = ["render_allocation_costs"]
