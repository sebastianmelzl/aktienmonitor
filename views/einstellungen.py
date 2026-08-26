"""Einstellungen: Gewichtung, Cache-Lebensdauer, aktive Datenquellen."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from aktienmonitor.config import DATA_KINDS, DEFAULT_TTL_SECONDS
from aktienmonitor.scoring.definitions import CATEGORY_LABELS, DEFAULT_WEIGHTS
from aktienmonitor.scoring.sector import DEFAULT_MIN_PEERS
from aktienmonitor.ui.common import (
    MIN_PEERS_SETTING_KEY,
    WEIGHTS_SETTING_KEY,
    clear_sector_cache,
    get_config,
    get_service,
    get_settings,
    get_watchlist,
    page_header,
)
from aktienmonitor.ui.scores import weight_sliders


def _dauer(sekunden: int) -> str:
    """Sekunden lesbar darstellen."""
    if sekunden >= 86_400:
        return f"{sekunden / 86_400:.0f} Tage"
    if sekunden >= 3_600:
        return f"{sekunden / 3_600:.0f} Std."
    if sekunden >= 60:
        return f"{sekunden / 60:.0f} Min."
    return f"{sekunden} Sek."


page_header("Einstellungen", "Gewichtung, Cache und Datenquellen")

store = get_settings()
config = get_config()
service = get_service()

tab_gewichte, tab_sektor, tab_cache, tab_quellen = st.tabs(
    ["Gewichtung", "Sektorvergleich", "Cache", "Datenquellen"]
)

with tab_gewichte:
    st.subheader("Gewichtung der Teilscores")
    st.write(
        "Bestimmt, wie stark die vier Teilscores in den Gesamtscore eingehen. "
        "Nur die Verhaeltnisse zaehlen – die Gewichte werden intern auf 100 % normiert. "
        "Ein Teilscore ohne Daten geht nicht mit null ein, sondern sein Gewicht wird auf "
        "die uebrigen verteilt."
    )
    spalte_regler, spalte_info = st.columns([2, 1])
    with spalte_regler:
        gewichte = weight_sliders(store, key_prefix="settings_")
    with spalte_info:
        summe = sum(gewichte.values())
        if summe > 0:
            st.write("**Effektive Verteilung**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Teilscore": CATEGORY_LABELS[k], "Anteil": f"{v / summe * 100:.0f} %"}
                        for k, v in gewichte.items()
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        st.caption(
            "Voreinstellung: "
            + ", ".join(
                f"{CATEGORY_LABELS[k]} {v * 100:.0f} %" for k, v in DEFAULT_WEIGHTS.items()
            )
        )

    if st.button("Auf Voreinstellung zuruecksetzen"):
        store.set(WEIGHTS_SETTING_KEY, dict(DEFAULT_WEIGHTS))
        st.success("Gewichtung zurueckgesetzt.")
        st.rerun()

with tab_sektor:
    st.subheader("Sektorvergleich")
    st.write(
        "Bewertungskennzahlen wie KGV, KUV oder Margen werden nicht absolut bewertet, "
        "sondern als Rang innerhalb der eigenen Branche. Die Vergleichsgruppe ist das "
        "eigene Universum – eine kostenlose Quelle fuer echte Sektor-Mediane gibt es nicht. "
        "**Der Vergleich ist damit relativ zur Watchlist, nicht zum Gesamtmarkt.**"
    )

    aktuell = int(store.get(MIN_PEERS_SETTING_KEY, DEFAULT_MIN_PEERS))
    schwelle = st.slider(
        "Mindestgroesse der Vergleichsgruppe",
        min_value=2,
        max_value=15,
        value=aktuell,
        help="Unterhalb dieser Zahl wird eine Kennzahl gar nicht bewertet, statt einen "
             "Rang aus wenigen Titeln zu behaupten. Das senkt die Datenabdeckung, "
             "verhindert aber Scheingenauigkeit.",
    )
    if schwelle != aktuell:
        store.set(MIN_PEERS_SETTING_KEY, schwelle)
        clear_sector_cache()
        st.rerun()

    from aktienmonitor.ui.common import get_sector_statistics

    statistik = get_sector_statistics(get_watchlist().tickers(), min_peers=schwelle)
    if statistik is None:
        st.info(
            "Noch keine zwischengespeicherten Daten. Der Sektorvergleich steht zur "
            "Verfuegung, sobald mehrere Titel in der Detailansicht geladen wurden."
        )
    else:
        st.dataframe(
            pd.DataFrame(statistik.coverage_report()), width="stretch", hide_index=True
        )
        if st.button("Sektordaten neu aufbauen"):
            clear_sector_cache()
            st.rerun()

with tab_cache:
    st.subheader("Cache-Lebensdauer")
    st.write(
        "Kurzlebige Daten haeufig, langlebige selten abrufen – das ist der wirksamste "
        "Hebel gegen die Rate-Limits der Anbieter. Die Werte stammen aus der `.env` und "
        "werden hier nur angezeigt; zum Aendern die `.env` anpassen und die App neu starten."
    )
    beschriftungen = {
        "quote": "Realtime-Kurs",
        "price_history": "Kurshistorie",
        "fundamentals": "Bilanz, GuV, Cashflow",
        "profile": "Stammdaten, Sektor",
        "analyst": "Analystendaten",
        "news": "Schlagzeilen",
    }
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Datenart": beschriftungen.get(art, art),
                    "Aktuell": _dauer(config.ttl_seconds[art]),
                    "Voreinstellung": _dauer(DEFAULT_TTL_SECONDS[art]),
                    "Variable": f"CACHE_TTL_{art.upper()}",
                }
                for art in DATA_KINDS
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    st.subheader("Cache-Inhalt")
    statistik_cache = service.cache.stats()
    if statistik_cache:
        st.dataframe(
            pd.DataFrame(statistik_cache).rename(
                columns={
                    "data_kind": "Datenart",
                    "source": "Quelle",
                    "n": "Eintraege",
                    "oldest": "Aeltester Abruf",
                }
            ),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("Der Cache ist leer.")

    spalte_a, spalte_b = st.columns(2)
    if spalte_a.button("Abgelaufene Eintraege entfernen"):
        anzahl = service.cache.purge_expired()
        clear_sector_cache()
        st.success(f"{anzahl} abgelaufene Eintraege entfernt.")
    if spalte_b.button("Cache vollstaendig leeren"):
        anzahl = service.cache.clear()
        clear_sector_cache()
        st.success(f"{anzahl} Eintraege entfernt.")

with tab_quellen:
    st.subheader("Aktive Datenquellen")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Quelle": "yfinance",
                    "Rolle": "Hauptquelle",
                    "Schluessel": "nicht noetig",
                    "Status": "aktiv",
                    "Limit/Min.": str(config.rate_limit_per_min.get("yfinance", 0)),
                },
                {
                    "Quelle": "Finnhub",
                    "Rolle": "ergaenzend",
                    "Schluessel": "FINNHUB_API_KEY",
                    "Status": "aktiv" if config.has_finnhub else "kein Schluessel",
                    "Limit/Min.": str(config.rate_limit_per_min.get("finnhub", 0)),
                },
                {
                    "Quelle": "Anthropic",
                    "Rolle": "Sentiment-Einordnung",
                    "Schluessel": "ANTHROPIC_API_KEY",
                    "Status": "aktiv" if config.has_anthropic else "kein Schluessel",
                    "Limit/Min.": "-",
                },
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "Schluessel werden ausschliesslich aus der `.env` gelesen. Welche Endpunkte "
        "damit tatsaechlich nutzbar sind, prueft die Seite **Datenquellen**."
    )
    st.write(f"Wiederholversuche bei Fehlern: **{config.retry_max_attempts}**")
