"""Darstellung des Benchmark-Vergleichs in der Oberflaeche."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..benchmark.compare import PERIODS, BenchmarkComparison, compare, total_return
from ..formatting import format_change

BENCHMARK_CAPTION = (
    "Verglichen werden reine **Kursrenditen** - Ausschuettungen sind darin nicht "
    "enthalten. Bei ausschuettenden ETFs wie dem Referenzindex wirkt sich das "
    "zulasten der Benchmark aus; der tatsaechliche Renditeabstand faellt real "
    "etwas kleiner aus."
)


def render_comparison(
    ticker: str, bars: list[dict], benchmark_ticker: str, benchmark_bars: list[dict]
) -> BenchmarkComparison:
    """Zeigt den Renditevergleich ueber mehrere Zeitraeume und gibt ihn zurueck."""
    comparison = compare(ticker, bars, benchmark_ticker, benchmark_bars)
    if not benchmark_bars:
        st.info(
            f"Fuer die Benchmark **{benchmark_ticker}** liegt keine Kurshistorie vor - "
            "vermutlich noch nicht abgerufen.",
            icon="ℹ️",
        )
        return comparison

    table = pd.DataFrame(
        [
            {
                "Zeitraum": period.label,
                ticker: format_change(period.subject),
                benchmark_ticker: format_change(period.benchmark),
                "Vorsprung": format_change(period.excess),
            }
            for period in comparison.periods
        ]
    )
    st.dataframe(table, width="stretch", hide_index=True)
    if comparison.available:
        st.caption(comparison.summary)
    st.caption(BENCHMARK_CAPTION)
    return comparison


def render_portfolio_comparison(
    benchmark_ticker: str,
    benchmark_bars: list[dict],
    weighted_bars: list[tuple[float, list[dict]]],
) -> None:
    """Vergleicht eine gewichtete Positionsliste mit der Benchmark.

    ``weighted_bars`` sind Paare aus Portfolioanteil (0..1) und Kurshistorie.
    Die Portfoliorendite je Zeitraum ist die gewichtete Summe der Einzelrenditen
    der Titel, die fuer diesen Zeitraum eine Rendite ausweisen koennen - deren
    Gewichte werden dafuer neu auf 1 normiert, statt fehlende Titel mit 0 zu
    werten.
    """
    if not benchmark_bars:
        st.info(
            f"Fuer die Benchmark **{benchmark_ticker}** liegt keine Kurshistorie vor - "
            "vermutlich noch nicht abgerufen.",
            icon="ℹ️",
        )
        return
    if not weighted_bars:
        return

    rows = []
    for label, tage in PERIODS:
        beitraege = [
            (gewicht, total_return(bars, trading_days=tage)) for gewicht, bars in weighted_bars
        ]
        vorhandene = [(g, r) for g, r in beitraege if r is not None]
        gewichtssumme = sum(g for g, _ in vorhandene)
        portfolio = (
            sum(g * r for g, r in vorhandene) / gewichtssumme if gewichtssumme > 0 else None
        )
        referenz = total_return(benchmark_bars, trading_days=tage)
        vorsprung = None if portfolio is None or referenz is None else portfolio - referenz
        rows.append(
            {
                "Zeitraum": label,
                "Portfolio (gewichtet)": format_change(portfolio),
                benchmark_ticker: format_change(referenz),
                "Vorsprung": format_change(vorsprung),
            }
        )

    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption(
        "Die Portfoliorendite je Zeitraum ist die nach Zielanteil gewichtete Kursrendite "
        "der Positionen - unabhaengig vom hier vorgeschlagenen Kaufzeitpunkt, also kein "
        "Rueckblick darauf, was dieser konkrete Vorschlag erzielt haette."
    )
    st.caption(BENCHMARK_CAPTION)


__all__ = ["render_comparison", "render_portfolio_comparison"]
