"""Gemeinsame Bausteine der Oberflaeche."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..config import Config, load_config
from ..logging_setup import setup_logging
from ..models import MetricSet
from ..providers.fetcher import StockDataService, StockSnapshot
from ..storage.db import Database
from ..storage.settings_store import SettingsStore
from ..storage.watchlist import Watchlist
from .format import format_metric

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
