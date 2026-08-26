"""Kurscharts mit einblendbaren Indikatoren."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ..metrics.technical import bars_to_frame, ema_series, wilder_smooth

# Farben bewusst zurueckhaltend und in beiden Streamlit-Themes lesbar.
COLOR_PRICE = "#1f77b4"
COLOR_SMA_50 = "#ff7f0e"
COLOR_SMA_200 = "#8c564b"
COLOR_BAND = "rgba(100, 100, 100, 0.18)"
COLOR_UP = "#2ca02c"
COLOR_DOWN = "#d62728"

INDICATOR_OPTIONS = ("SMA 50", "SMA 200", "Bollinger-Baender", "Volumen", "RSI (14)", "MACD")


def price_chart(
    bars: list[dict],
    *,
    indicators: tuple[str, ...] = ("SMA 50", "SMA 200"),
    title: str = "",
    candlestick: bool = True,
) -> go.Figure | None:
    """Baut den Kurschart. Gibt ``None`` zurueck, wenn keine Historie vorliegt."""
    frame = bars_to_frame(bars)
    if frame.empty:
        return None

    show_rsi = "RSI (14)" in indicators
    show_macd = "MACD" in indicators
    show_volume = "Volumen" in indicators

    # Zeilenaufteilung: Kurs oben, danach optional Volumen, RSI und MACD.
    heights = [0.55]
    subplot_titles = ["Kurs"]
    if show_volume:
        heights.append(0.15)
        subplot_titles.append("Volumen")
    if show_rsi:
        heights.append(0.15)
        subplot_titles.append("RSI (14)")
    if show_macd:
        heights.append(0.15)
        subplot_titles.append("MACD")
    total = sum(heights)
    heights = [h / total for h in heights]

    figure = make_subplots(
        rows=len(heights), cols=1, shared_xaxes=True, vertical_spacing=0.04,
        row_heights=heights, subplot_titles=subplot_titles,
    )

    if candlestick and frame[["open", "high", "low"]].notna().all(axis=None):
        figure.add_trace(
            go.Candlestick(
                x=frame.index, open=frame["open"], high=frame["high"], low=frame["low"],
                close=frame["close"], name="Kurs",
                increasing_line_color=COLOR_UP, decreasing_line_color=COLOR_DOWN,
            ),
            row=1, col=1,
        )
    else:
        figure.add_trace(
            go.Scatter(
                x=frame.index, y=frame["close"], name="Schlusskurs",
                line={"color": COLOR_PRICE, "width": 1.6},
            ),
            row=1, col=1,
        )

    if "SMA 50" in indicators and len(frame) >= 50:
        figure.add_trace(
            go.Scatter(
                x=frame.index, y=frame["close"].rolling(50).mean(), name="SMA 50",
                line={"color": COLOR_SMA_50, "width": 1.3},
            ),
            row=1, col=1,
        )
    if "SMA 200" in indicators and len(frame) >= 200:
        figure.add_trace(
            go.Scatter(
                x=frame.index, y=frame["close"].rolling(200).mean(), name="SMA 200",
                line={"color": COLOR_SMA_200, "width": 1.3},
            ),
            row=1, col=1,
        )
    if "Bollinger-Baender" in indicators and len(frame) >= 20:
        middle = frame["close"].rolling(20).mean()
        deviation = frame["close"].rolling(20).std(ddof=0)
        figure.add_trace(
            go.Scatter(x=frame.index, y=middle + 2 * deviation, name="Bollinger oben",
                       line={"color": "rgba(120,120,120,0.6)", "width": 1}),
            row=1, col=1,
        )
        figure.add_trace(
            go.Scatter(
                x=frame.index, y=middle - 2 * deviation, name="Bollinger unten",
                line={"color": "rgba(120,120,120,0.6)", "width": 1},
                fill="tonexty", fillcolor=COLOR_BAND,
            ),
            row=1, col=1,
        )

    row = 2
    if show_volume:
        figure.add_trace(
            go.Bar(
                x=frame.index, y=frame["volume"], name="Volumen",
                marker_color="rgba(120,120,120,0.5)",
            ),
            row=row, col=1,
        )
        row += 1

    if show_rsi:
        rsi_line = _rsi_series(frame["close"])
        if rsi_line is not None:
            figure.add_trace(
                go.Scatter(x=frame.index, y=rsi_line, name="RSI (14)",
                           line={"color": COLOR_PRICE, "width": 1.3}),
                row=row, col=1,
            )
            # Uebliche Orientierungslinien - keine Handlungsempfehlung.
            for level, dash in ((70, "dash"), (30, "dash")):
                figure.add_hline(
                    y=level, line_dash=dash, line_color="rgba(150,150,150,0.7)",
                    row=row, col=1,
                )
            figure.update_yaxes(range=[0, 100], row=row, col=1)
        row += 1

    if show_macd:
        macd_line = ema_series(frame["close"], 12) - ema_series(frame["close"], 26)
        signal_line = ema_series(macd_line, 9)
        figure.add_trace(
            go.Bar(x=frame.index, y=macd_line - signal_line, name="Histogramm",
                   marker_color="rgba(120,120,120,0.5)"),
            row=row, col=1,
        )
        figure.add_trace(
            go.Scatter(x=frame.index, y=macd_line, name="MACD",
                       line={"color": COLOR_PRICE, "width": 1.3}),
            row=row, col=1,
        )
        figure.add_trace(
            go.Scatter(x=frame.index, y=signal_line, name="Signal",
                       line={"color": COLOR_SMA_50, "width": 1.2}),
            row=row, col=1,
        )

    figure.update_layout(
        title=title,
        height=260 + 190 * (len(heights) - 1),
        margin={"l": 10, "r": 10, "t": 50 if title else 30, "b": 10},
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )
    return figure


def _rsi_series(close: pd.Series, window: int = 14) -> pd.Series | None:
    """RSI als Zeitreihe fuer die Chartdarstellung.

    Randfaelle wie "keine Abwaertsbewegung im Fenster" werden genauso behandelt
    wie in ``metrics.technical.rsi``, damit Chart und Kennzahlentabelle dieselbe
    Zahl zeigen.
    """
    if len(close) < window + 1:
        return None
    delta = close.diff().dropna()
    gains = wilder_smooth(delta.clip(lower=0.0), window)
    losses = wilder_smooth(-delta.clip(upper=0.0), window)
    if gains is None or losses is None:
        return None

    gain_values = gains.to_numpy(dtype=float)
    loss_values = losses.to_numpy(dtype=float)
    result = np.full(len(gain_values), np.nan)
    valid = ~np.isnan(gain_values) & ~np.isnan(loss_values)

    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.divide(
            gain_values, loss_values,
            out=np.full_like(gain_values, np.nan), where=loss_values > 0,
        )
    result = np.where(valid & (loss_values > 0), 100.0 - 100.0 / (1.0 + rs), result)
    result = np.where(valid & (loss_values == 0) & (gain_values > 0), 100.0, result)
    result = np.where(valid & (loss_values == 0) & (gain_values <= 0), 50.0, result)
    return pd.Series(result, index=gains.index).reindex(close.index)
