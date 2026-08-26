"""Technische Indikatoren.

Alle Funktionen arbeiten auf einer nach Datum aufsteigend sortierten Kursreihe.
Reicht die Historie fuer einen Indikator nicht aus, ist das Ergebnis ``None`` -
es wird kein verkuerztes Fenster stillschweigend eingesetzt, weil ein RSI auf
5 statt 14 Tagen eine andere Kennzahl waere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from ..models import (
    MISSING_INSUFFICIENT_HISTORY,
    UNIT_PERCENT,
    UNIT_RATIO,
    UNIT_TEXT,
    MetricSet,
    MetricValue,
    Provenance,
)

# Handelstage je Zeitraum - Naeherung fuer Momentum-Fenster.
TRADING_DAYS_PER_MONTH = 21
TRADING_DAYS_PER_YEAR = 252


def bars_to_frame(bars: list[dict]) -> pd.DataFrame:
    """Wandelt die Rohkerzen in einen sortierten DataFrame mit Datumsindex."""
    if not bars:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    frame = pd.DataFrame(bars)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.dropna(subset=["close"]).sort_values("date").set_index("date")
    for column in ("open", "high", "low", "close", "volume"):
        if column not in frame.columns:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame[["open", "high", "low", "close", "volume"]]


# --- Einzelindikatoren -------------------------------------------------------


def sma(close: pd.Series, window: int) -> float | None:
    """Einfacher gleitender Durchschnitt der letzten ``window`` Schlusskurse."""
    if len(close) < window:
        return None
    value = close.tail(window).mean()
    return float(value) if pd.notna(value) else None


def ema_series(values: pd.Series, span: int) -> pd.Series:
    """Exponentiell gewichteter Durchschnitt (wie in der Chartanalyse ueblich)."""
    return values.ewm(span=span, adjust=False).mean()


def wilder_smooth(values: pd.Series, window: int) -> pd.Series | None:
    """Glaettung nach Wilder.

    Wilder startet mit dem einfachen Mittelwert der ersten ``window`` Werte und
    schreibt ihn danach rekursiv fort. Ein reines ``ewm`` ohne diese Saat liefert
    besonders am Anfang der Reihe andere Zahlen als jedes Chartprogramm - daher
    hier die originalgetreue Variante.
    """
    array = values.to_numpy(dtype=float)
    if len(array) < window or window < 1:
        return None
    out = np.full(len(array), np.nan)
    out[window - 1] = array[:window].mean()
    for i in range(window, len(array)):
        out[i] = (out[i - 1] * (window - 1) + array[i]) / window
    return pd.Series(out, index=values.index)


def rsi(close: pd.Series, window: int = 14) -> float | None:
    """Relative Strength Index nach Wilder (Standardeinstellung 14 Perioden)."""
    if len(close) < window + 1:
        return None
    delta = close.diff().dropna()
    avg_gain_series = wilder_smooth(delta.clip(lower=0.0), window)
    avg_loss_series = wilder_smooth(-delta.clip(upper=0.0), window)
    if avg_gain_series is None or avg_loss_series is None:
        return None
    avg_gain = float(avg_gain_series.iloc[-1])
    avg_loss = float(avg_loss_series.iloc[-1])
    if not (np.isfinite(avg_gain) and np.isfinite(avg_loss)):
        return None
    if avg_loss == 0:
        # Kein Abwaertsdruck im Betrachtungszeitraum - definitionsgemaess 100.
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


@dataclass(frozen=True)
class MacdResult:
    macd: float
    signal: float
    histogram: float


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> MacdResult | None:
    """MACD-Linie, Signallinie und Histogramm."""
    if len(close) < slow + signal:
        return None
    macd_line = ema_series(close, fast) - ema_series(close, slow)
    signal_line = ema_series(macd_line, signal)
    macd_value = float(macd_line.iloc[-1])
    signal_value = float(signal_line.iloc[-1])
    return MacdResult(macd_value, signal_value, macd_value - signal_value)


@dataclass(frozen=True)
class BollingerResult:
    middle: float
    upper: float
    lower: float
    percent_b: float | None
    bandwidth: float


def bollinger(close: pd.Series, window: int = 20, num_std: float = 2.0) -> BollingerResult | None:
    """Bollinger-Baender um den 20-Tage-Durchschnitt.

    Die Standardabweichung wird als Populationsgroesse berechnet (ddof=0) - so
    handhaben es die gaengigen Chartprogramme.
    """
    if len(close) < window:
        return None
    window_values = close.tail(window)
    middle = float(window_values.mean())
    std = float(window_values.std(ddof=0))
    upper = middle + num_std * std
    lower = middle - num_std * std
    last = float(close.iloc[-1])
    percent_b = None if upper == lower else (last - lower) / (upper - lower)
    bandwidth = 0.0 if middle == 0 else (upper - lower) / middle
    return BollingerResult(middle, upper, lower, percent_b, bandwidth)


def atr(frame: pd.DataFrame, window: int = 14) -> float | None:
    """Average True Range nach Wilder."""
    if len(frame) < window + 1:
        return None
    high, low, close = frame["high"], frame["low"], frame["close"]
    previous_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1
    ).max(axis=1)
    true_range = true_range.dropna()
    smoothed = wilder_smooth(true_range, window)
    if smoothed is None:
        return None
    value = smoothed.iloc[-1]
    return float(value) if pd.notna(value) else None


def annualised_volatility(close: pd.Series, window: int = TRADING_DAYS_PER_YEAR) -> float | None:
    """Annualisierte Volatilitaet aus logarithmierten Tagesrenditen, in Prozent."""
    if len(close) < 30:
        return None
    returns = np.log(close / close.shift(1)).dropna()
    if len(returns) < 20:
        return None
    sample = returns.tail(window)
    daily_std = float(sample.std(ddof=1))
    return float(daily_std * np.sqrt(TRADING_DAYS_PER_YEAR) * 100.0)


def momentum(close: pd.Series, months: int) -> float | None:
    """Kursveraenderung ueber ``months`` Monate in Prozent."""
    lookback = months * TRADING_DAYS_PER_MONTH
    if len(close) < lookback + 1:
        return None
    past = float(close.iloc[-(lookback + 1)])
    if past <= 0:
        return None
    return float((float(close.iloc[-1]) / past - 1.0) * 100.0)


def distance_to_extreme(close: pd.Series, *, window: int = TRADING_DAYS_PER_YEAR, high: bool) -> float | None:
    """Abstand zum Hoch bzw. Tief des Fensters in Prozent.

    Positiv bedeutet ueber dem Tief bzw. - beim Hoch - unter dem Hoch:
    Rueckgabe ist stets die relative Abweichung des aktuellen Kurses.
    """
    if len(close) < 2:
        return None
    sample = close.tail(min(window, len(close)))
    extreme = float(sample.max() if high else sample.min())
    if extreme <= 0:
        return None
    return float((float(close.iloc[-1]) / extreme - 1.0) * 100.0)


def volume_trend(volume: pd.Series, short: int = 20, long: int = 60) -> float | None:
    """Verhaeltnis des kurzfristigen zum langfristigen Durchschnittsvolumen, in Prozent.

    +25 bedeutet: das Volumen der letzten 20 Tage liegt 25 % ueber dem
    Durchschnitt der letzten 60 Tage.
    """
    clean = volume.dropna()
    if len(clean) < long:
        return None
    short_avg = float(clean.tail(short).mean())
    long_avg = float(clean.tail(long).mean())
    if long_avg <= 0:
        return None
    return float((short_avg / long_avg - 1.0) * 100.0)


def cross_signal(close: pd.Series, fast: int = 50, slow: int = 200, lookback: int = 30) -> str | None:
    """Erkennt Golden Cross bzw. Death Cross innerhalb der letzten ``lookback`` Tage.

    Liegt kein Kreuzen vor, wird die aktuelle Lage der Durchschnitte zueinander
    zurueckgegeben.
    """
    if len(close) < slow + 1:
        return None
    fast_line = close.rolling(fast).mean()
    slow_line = close.rolling(slow).mean()
    diff = (fast_line - slow_line).dropna()
    if len(diff) < 2:
        return None

    recent = diff.tail(min(lookback, len(diff)))
    signs = np.sign(recent.to_numpy())
    for i in range(1, len(signs)):
        if signs[i - 1] < 0 <= signs[i]:
            return "Golden Cross"
        if signs[i - 1] > 0 >= signs[i]:
            return "Death Cross"
    return "SMA50 ueber SMA200" if diff.iloc[-1] > 0 else "SMA50 unter SMA200"


# --- Zusammenstellung --------------------------------------------------------


def _metric(
    key: str,
    label: str,
    value: float | None,
    unit: str,
    *,
    as_of: datetime | None,
    source: Provenance,
    reason: str = MISSING_INSUFFICIENT_HISTORY,
    inputs: tuple[str, ...] = ("Kurshistorie",),
) -> MetricValue:
    if value is None:
        return MetricValue.missing(
            key, label, unit=unit, reason=reason, source=source,
            is_computed=True, inputs=inputs,
        )
    return MetricValue(
        key=key, label=label, value=float(value), unit=unit, source=source,
        as_of=as_of, is_computed=True, inputs=inputs,
    )


def compute_technical_metrics(
    bars: list[dict], *, as_of: datetime | None = None, source: Provenance = Provenance.YFINANCE
) -> MetricSet:
    """Berechnet alle technischen Kennzahlen aus der Kurshistorie.

    Saemtliche Werte sind abgeleitet und werden als "berechnet" gekennzeichnet.
    """
    frame = bars_to_frame(bars)
    stamp = as_of or datetime.now(UTC)
    metrics: dict[str, MetricValue] = {}

    def add(key: str, label: str, value: float | None, unit: str = UNIT_RATIO) -> None:
        metrics[key] = _metric(key, label, value, unit, as_of=stamp, source=source)

    if frame.empty:
        for key, label, unit in _TECHNICAL_SPEC:
            metrics[key] = MetricValue.missing(
                key, label, unit=unit, reason="Keine Kurshistorie verfuegbar",
                source=source, is_computed=True, inputs=("Kurshistorie",),
            )
        return MetricSet(metrics)

    close = frame["close"]
    last_price = float(close.iloc[-1])

    sma50 = sma(close, 50)
    sma200 = sma(close, 200)
    add("price", "Kurs", last_price, UNIT_RATIO)
    add("sma_50", "SMA 50", sma50)
    add("sma_200", "SMA 200", sma200)
    add(
        "price_vs_sma_50",
        "Abstand zur SMA 50",
        None if sma50 in (None, 0) else (last_price / sma50 - 1.0) * 100.0,
        UNIT_PERCENT,
    )
    add(
        "price_vs_sma_200",
        "Abstand zur SMA 200",
        None if sma200 in (None, 0) else (last_price / sma200 - 1.0) * 100.0,
        UNIT_PERCENT,
    )

    add("rsi_14", "RSI (14)", rsi(close, 14))

    macd_result = macd(close)
    add("macd", "MACD-Linie", None if macd_result is None else macd_result.macd)
    add("macd_signal", "MACD-Signallinie", None if macd_result is None else macd_result.signal)
    add("macd_histogram", "MACD-Histogramm", None if macd_result is None else macd_result.histogram)

    bands = bollinger(close)
    add("bollinger_upper", "Bollinger oberes Band", None if bands is None else bands.upper)
    add("bollinger_middle", "Bollinger Mittellinie", None if bands is None else bands.middle)
    add("bollinger_lower", "Bollinger unteres Band", None if bands is None else bands.lower)
    add(
        "bollinger_percent_b",
        "Bollinger %B",
        None if bands is None else bands.percent_b,
    )

    atr_value = atr(frame)
    add("atr_14", "ATR (14)", atr_value)
    add(
        "atr_percent",
        "ATR in % des Kurses",
        None if atr_value is None or last_price <= 0 else atr_value / last_price * 100.0,
        UNIT_PERCENT,
    )

    add("volatility_1y", "Volatilitaet (annualisiert)", annualised_volatility(close), UNIT_PERCENT)

    for months, key in ((1, "momentum_1m"), (3, "momentum_3m"), (6, "momentum_6m"), (12, "momentum_12m")):
        add(key, f"Momentum {months} Monate", momentum(close, months), UNIT_PERCENT)

    add(
        "distance_52w_high",
        "Abstand zum 52-Wochen-Hoch",
        distance_to_extreme(close, high=True),
        UNIT_PERCENT,
    )
    add(
        "distance_52w_low",
        "Abstand zum 52-Wochen-Tief",
        distance_to_extreme(close, high=False),
        UNIT_PERCENT,
    )

    add("volume_trend", "Volumentrend (20T vs. 60T)", volume_trend(frame["volume"]), UNIT_PERCENT)

    signal = cross_signal(close)
    metrics["ma_cross"] = (
        MetricValue(
            key="ma_cross", label="SMA-50/200-Signal", text=signal, unit=UNIT_TEXT,
            source=source, as_of=stamp, is_computed=True, inputs=("Kurshistorie",),
        )
        if signal is not None
        else MetricValue.missing(
            "ma_cross", "SMA-50/200-Signal", unit=UNIT_TEXT,
            reason=MISSING_INSUFFICIENT_HISTORY, source=source, is_computed=True,
            inputs=("Kurshistorie",),
        )
    )

    return MetricSet(metrics)


# Vollstaendige Liste der technischen Kennzahlen - wird gebraucht, um bei
# fehlender Historie trotzdem alle Zeilen als "n/a" ausweisen zu koennen.
_TECHNICAL_SPEC: tuple[tuple[str, str, str], ...] = (
    ("price", "Kurs", UNIT_RATIO),
    ("sma_50", "SMA 50", UNIT_RATIO),
    ("sma_200", "SMA 200", UNIT_RATIO),
    ("price_vs_sma_50", "Abstand zur SMA 50", UNIT_PERCENT),
    ("price_vs_sma_200", "Abstand zur SMA 200", UNIT_PERCENT),
    ("rsi_14", "RSI (14)", UNIT_RATIO),
    ("macd", "MACD-Linie", UNIT_RATIO),
    ("macd_signal", "MACD-Signallinie", UNIT_RATIO),
    ("macd_histogram", "MACD-Histogramm", UNIT_RATIO),
    ("bollinger_upper", "Bollinger oberes Band", UNIT_RATIO),
    ("bollinger_middle", "Bollinger Mittellinie", UNIT_RATIO),
    ("bollinger_lower", "Bollinger unteres Band", UNIT_RATIO),
    ("bollinger_percent_b", "Bollinger %B", UNIT_RATIO),
    ("atr_14", "ATR (14)", UNIT_RATIO),
    ("atr_percent", "ATR in % des Kurses", UNIT_PERCENT),
    ("volatility_1y", "Volatilitaet (annualisiert)", UNIT_PERCENT),
    ("momentum_1m", "Momentum 1 Monate", UNIT_PERCENT),
    ("momentum_3m", "Momentum 3 Monate", UNIT_PERCENT),
    ("momentum_6m", "Momentum 6 Monate", UNIT_PERCENT),
    ("momentum_12m", "Momentum 12 Monate", UNIT_PERCENT),
    ("distance_52w_high", "Abstand zum 52-Wochen-Hoch", UNIT_PERCENT),
    ("distance_52w_low", "Abstand zum 52-Wochen-Tief", UNIT_PERCENT),
    ("volume_trend", "Volumentrend (20T vs. 60T)", UNIT_PERCENT),
    ("ma_cross", "SMA-50/200-Signal", UNIT_TEXT),
)
