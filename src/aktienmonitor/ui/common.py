"""Gemeinsame Bausteine der Oberflaeche."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..config import Config, load_config
from ..costs.model import TaxSettings
from ..formatting import format_metric
from ..logging_setup import setup_logging
from ..models import MetricSet
from ..providers.fetcher import StockDataService, StockSnapshot
from ..scoring.definitions import DEFAULT_WEIGHTS
from ..scoring.sector import DEFAULT_MIN_PEERS, SectorStatistics
from ..storage.db import Database
from ..storage.settings_store import SettingsStore
from ..storage.watchlist import Watchlist

DISCLAIMER = (
    "**Hinweis:** Dieses Werkzeug bereitet oeffentlich verfuegbare Daten auf und "
    "stellt **keine Anlageberatung** dar. Es gibt **keine Gewaehr fuer die "
    "Richtigkeit, Vollstaendigkeit oder Aktualitaet** der angezeigten Daten. "
    "Alle Kennzahlen stammen aus kostenlosen Datenquellen und koennen fehlerhaft "
    "oder veraltet sein. Entscheidungen treffen Sie eigenverantwortlich."
)


@st.cache_resource
def get_config() -> Config:
    config = load_config()
    setup_logging(config.log_level)
    return config


@st.cache_resource
def get_database() -> Database:
    return Database(get_config().db_path)


@st.cache_resource
def get_service() -> StockDataService:
    return StockDataService(get_config(), get_database())


def get_watchlist() -> Watchlist:
    return Watchlist(get_database())


def get_settings() -> SettingsStore:
    return SettingsStore(get_database())


def page_header(title: str, subtitle: str | None = None) -> None:
    """Einheitlicher Seitenkopf samt dauerhaftem Hinweis."""
    st.title(title)
    if subtitle:
        st.caption(subtitle)
    st.info(DISCLAIMER, icon="ℹ️")


def render_freshness(snapshot: StockSnapshot) -> None:
    """Zeigt je Teilbereich Quelle, Alter und Cache-Status."""
    with st.expander("Datenstand und Quellen", expanded=False):
        rows = [
            {
                "Bereich": item.label,
                "Quelle": item.source.value,
                "Stand": item.age_text,
                "Herkunft": "Cache" if item.from_cache else "Live abgerufen",
                "Hinweis": item.error or "",
            }
            for item in snapshot.freshness
        ]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        if snapshot.errors:
            st.warning(
                "Nicht alle Bereiche konnten abgerufen werden. Betroffene Kennzahlen "
                "werden als n/a gefuehrt:\n\n- " + "\n- ".join(snapshot.errors)
            )


def metrics_table(metrics: MetricSet, currency: str | None = None) -> pd.DataFrame:
    """Baut die Anzeigetabelle einer Kennzahlengruppe."""
    rows = []
    for metric in metrics:
        rows.append(
            {
                "Kennzahl": metric.label,
                "Wert": format_metric(metric, currency),
                "Quelle": metric.source_label,
                "Hinweis": metric.missing_reason if not metric.is_available else "",
            }
        )
    return pd.DataFrame(rows)


def coverage_caption(metrics: MetricSet, label: str) -> str:
    """Text zur Datenabdeckung einer Gruppe."""
    available = len(metrics.available)
    total = len(metrics)
    percent = round(metrics.coverage * 100)
    return f"{label}: {available} von {total} Kennzahlen verfuegbar ({percent} %)"


# --- Sektorstatistik ---------------------------------------------------------

WEIGHTS_SETTING_KEY = "score_weights"
MIN_PEERS_SETTING_KEY = "sector_min_peers"


@st.cache_data(ttl=600, show_spinner=False)
def _universe_sector_data(tickers: tuple[str, ...]) -> list[tuple[str | None, dict]]:
    """Liest die Fundamentalkennzahlen des Universums - ausschliesslich aus dem Cache.

    Ohne ``cache_only`` wuerde der Aufbau der Vergleichsgruppe bei 50 Titeln
    Hunderte Abrufe ausloesen. Der Sektorvergleich stuetzt sich deshalb auf das,
    was bereits geholt wurde; die Aktualisierung ist ein eigener Schritt.
    """
    service = get_service()
    result: list[tuple[str | None, dict]] = []
    for ticker in tickers:
        snapshot = service.get_snapshot(ticker, cache_only=True)
        if not snapshot.fundamental.available:
            continue
        # Nur Werte weiterreichen - MetricSet ist fuer den Streamlit-Cache
        # unnoetig schwer.
        werte = {m.key: m.value for m in snapshot.fundamental.available if m.value is not None}
        result.append((snapshot.profile.sector, werte))
    return result


def get_sector_statistics(
    tickers: list[str], *, min_peers: int | None = None
) -> SectorStatistics | None:
    """Baut die Sektorstatistik aus den zwischengespeicherten Daten des Universums."""
    if not tickers:
        return None
    threshold = min_peers if min_peers is not None else int(
        get_settings().get(MIN_PEERS_SETTING_KEY, DEFAULT_MIN_PEERS)
    )
    rohdaten = _universe_sector_data(tuple(sorted(tickers)))
    if not rohdaten:
        return None

    statistics = SectorStatistics(min_peers=threshold)
    for sector, werte in rohdaten:
        eimer = statistics.values.setdefault(sector or "Ohne Branchenangabe", {})
        for key, value in werte.items():
            eimer.setdefault(key, []).append(float(value))
    return statistics


def clear_sector_cache() -> None:
    """Erzwingt den Neuaufbau der Sektorstatistik beim naechsten Zugriff."""
    _universe_sector_data.clear()


TAX_SETTINGS_KEY = "tax_settings"


def get_tax_settings() -> TaxSettings:
    """Gespeicherte persoenliche Steuerangaben, sonst ledig ohne Kirchensteuer."""
    stored = get_settings().get(TAX_SETTINGS_KEY, None)
    if not isinstance(stored, dict):
        return TaxSettings()
    return TaxSettings(
        church_tax_rate=float(stored.get("church_tax_rate", 0.0)),
        joint_assessment=bool(stored.get("joint_assessment", False)),
        allowance_used=float(stored.get("allowance_used", 0.0)),
    )


def get_score_weights() -> dict[str, float]:
    """Gespeicherte Gewichtung der Teilscores, sonst die Voreinstellung."""
    stored = get_settings().get(WEIGHTS_SETTING_KEY, None)
    weights = dict(DEFAULT_WEIGHTS)
    if isinstance(stored, dict):
        weights.update(
            {k: float(v) for k, v in stored.items() if k in DEFAULT_WEIGHTS}
        )
    return weights
