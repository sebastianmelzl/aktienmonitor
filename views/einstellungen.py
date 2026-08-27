"""Einstellungen: Gewichtung, Cache-Lebensdauer, aktive Datenquellen."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from aktienmonitor.config import DATA_KINDS, DEFAULT_TTL_SECONDS
from aktienmonitor.costs.model import CHURCH_TAX_RATES, BrokerCosts, TaxSettings, tax_on_gain
from aktienmonitor.formatting import german_number
from aktienmonitor.scoring.definitions import CATEGORY_LABELS, DEFAULT_WEIGHTS
from aktienmonitor.scoring.sector import DEFAULT_MIN_PEERS
from aktienmonitor.ui.common import (
    MIN_PEERS_SETTING_KEY,
    TAX_SETTINGS_KEY,
    WEIGHTS_SETTING_KEY,
    clear_sector_cache,
    get_config,
    get_service,
    get_settings,
    get_tax_settings,
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

tab_gewichte, tab_sektor, tab_steuer, tab_cache, tab_quellen = st.tabs(
    ["Gewichtung", "Sektorvergleich", "Kosten & Steuer", "Cache", "Datenquellen"]
)

with tab_gewichte:
    st.subheader("Gewichtung der Teilscores")
    st.write(
        "Bestimmt, wie stark die vier Teilscores in den Gesamtscore eingehen. "
        "Nur die Verhaeltnisse zaehlen – die Gewichte werden intern auf 100 % normiert. "
        "Ein Teilscore ohne Daten geht nicht mit null ein, sondern sein Gewicht wird auf "
        "die uebrigen verteilt."
    )
    col_sliders, col_info = st.columns([2, 1])
    with col_sliders:
        weights = weight_sliders(store, key_prefix="settings_")
    with col_info:
        total = sum(weights.values())
        if total > 0:
            st.write("**Effektive Verteilung**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Teilscore": CATEGORY_LABELS[k], "Anteil": f"{v / total * 100:.0f} %"}
                        for k, v in weights.items()
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

    recent = int(store.get(MIN_PEERS_SETTING_KEY, DEFAULT_MIN_PEERS))
    threshold = st.slider(
        "Mindestgroesse der Vergleichsgruppe",
        min_value=2,
        max_value=15,
        value=recent,
        help="Unterhalb dieser Zahl wird eine Kennzahl gar nicht bewertet, statt einen "
             "Rang aus wenigen Titeln zu behaupten. Das senkt die Datenabdeckung, "
             "verhindert aber Scheingenauigkeit.",
    )
    if threshold != recent:
        store.set(MIN_PEERS_SETTING_KEY, threshold)
        clear_sector_cache()
        st.rerun()

    from aktienmonitor.ui.common import get_sector_statistics

    statistics = get_sector_statistics(get_watchlist().tickers(), min_peers=threshold)
    if statistics is None:
        st.info(
            "Noch keine zwischengespeicherten Daten. Der Sektorvergleich steht zur "
            "Verfuegung, sobald mehrere Titel in der Detailansicht geladen wurden."
        )
    else:
        st.dataframe(
            pd.DataFrame(statistics.coverage_report()), width="stretch", hide_index=True
        )
        if st.button("Sektordaten neu aufbauen"):
            clear_sector_cache()
            st.rerun()

with tab_steuer:
    st.subheader("Handelskosten")
    tr = BrokerCosts()
    st.write(
        f"Angenommen wird **{tr.name}**: {german_number(tr.order_fee, 2)} EUR "
        f"Fremdkostenpauschale je Order (Sparplaene kostenlos), plus die halbe angenommene "
        f"Handelsspanne von {tr.spread_bps:.0f} Basispunkten. Diese Annahmen fliessen in "
        "die Kostenanzeige auf der Seite **Aufteilung** ein."
    )

    st.subheader("Persoenliche Steuerangaben")
    st.write(
        "Fuer die Beispielrechnung unten. Ohne Angabe wird ledig, ohne Kirchensteuer und "
        "mit vollem Sparerpauschbetrag gerechnet."
    )
    stored_tax = get_tax_settings()
    col_kirche, col_veranlagung = st.columns(2)
    with col_kirche:
        church_label = st.selectbox(
            "Kirchensteuer",
            options=list(CHURCH_TAX_RATES),
            index=next(
                (i for i, v in enumerate(CHURCH_TAX_RATES.values())
                 if v == stored_tax.church_tax_rate),
                0,
            ),
        )
    with col_veranlagung:
        joint = st.checkbox("Zusammenveranlagung", value=stored_tax.joint_assessment)
    allowance_used = st.number_input(
        "Sparerpauschbetrag bereits verbraucht (z. B. bei anderen Banken)",
        min_value=0.0, value=stored_tax.allowance_used, step=100.0,
    )
    tax_settings = TaxSettings(
        church_tax_rate=CHURCH_TAX_RATES[church_label],
        joint_assessment=joint,
        allowance_used=allowance_used,
    )
    if tax_settings != stored_tax:
        store.set(
            TAX_SETTINGS_KEY,
            {
                "church_tax_rate": tax_settings.church_tax_rate,
                "joint_assessment": tax_settings.joint_assessment,
                "allowance_used": tax_settings.allowance_used,
            },
        )

    kpi_steuer = st.columns(3)
    kpi_steuer[0].metric("Effektiver Steuersatz", f"{tax_settings.effective_rate * 100:.3f} %")
    kpi_steuer[1].metric("Sparerpauschbetrag", german_number(tax_settings.allowance, 0))
    kpi_steuer[2].metric("davon noch frei", german_number(tax_settings.allowance_left, 0))

    st.subheader("Beispielrechnung")
    col_gewinn, col_fonds = st.columns(2)
    with col_gewinn:
        beispiel_gewinn = st.number_input(
            "Angenommener realisierter Gewinn", min_value=0.0, value=1_000.0, step=100.0
        )
    with col_fonds:
        ist_fonds = st.checkbox(
            "Aktienfonds/-ETF (30 % Teilfreistellung)",
            value=False,
            help="Gilt fuer Fonds mit dauerhaft mehr als 50 % Aktienanteil, nicht fuer "
                 "Einzelaktien.",
        )
    ergebnis = tax_on_gain(
        beispiel_gewinn,
        TaxSettings(
            church_tax_rate=tax_settings.church_tax_rate,
            joint_assessment=tax_settings.joint_assessment,
            allowance_used=tax_settings.allowance_used,
            equity_fund=ist_fonds,
        ),
    )
    kpi_beispiel = st.columns(3)
    kpi_beispiel[0].metric("Steuer", german_number(ergebnis.tax, 2))
    kpi_beispiel[1].metric("Netto verbleibend", german_number(ergebnis.net_gain, 2))
    kpi_beispiel[2].metric(
        "Effektive Belastung",
        f"{ergebnis.effective_burden:.2f} %" if ergebnis.effective_burden is not None else "-",
    )
    st.caption(
        "Reine Beispielrechnung, keine Steuerberatung. Verlustverrechnung mit anderen "
        "Geschaeften und die uebrige steuerliche Situation sind nicht abgebildet."
    )

with tab_cache:
    st.subheader("Cache-Lebensdauer")
    st.write(
        "Kurzlebige Daten haeufig, langlebige selten abrufen – das ist der wirksamste "
        "Hebel gegen die Rate-Limits der Anbieter. Die Werte stammen aus der `.env` und "
        "werden hier nur angezeigt; zum Aendern die `.env` anpassen und die App neu starten."
    )
    labels = {
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
                    "Datenart": labels.get(art, art),
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
    cache_stats = service.cache.stats()
    if cache_stats:
        st.dataframe(
            pd.DataFrame(cache_stats).rename(
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

    col_a, col_b = st.columns(2)
    if col_a.button("Abgelaufene Eintraege entfernen"):
        count = service.cache.purge_expired()
        clear_sector_cache()
        st.success(f"{count} abgelaufene Eintraege entfernt.")
    if col_b.button("Cache vollstaendig leeren"):
        count = service.cache.clear()
        clear_sector_cache()
        st.success(f"{count} Eintraege entfernt.")

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
