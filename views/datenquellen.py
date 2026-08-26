"""Datenquellen-Check und Zugriffsprotokoll."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from aktienmonitor.providers.capabilities import (
    REFERENCE_TICKER,
    STATUS_AVAILABLE,
    STATUS_FORBIDDEN,
    STATUS_NO_KEY,
    CapabilityChecker,
)
from aktienmonitor.ui.common import get_config, get_database, get_service, page_header

page_header(
    "Datenquellen",
    "Was die hinterlegten Schluessel tatsaechlich koennen - geprueft, nicht vermutet",
)

config = get_config()
service = get_service()
checker = CapabilityChecker(get_database(), service.yfinance, service.finnhub)

SYMBOLE = {
    STATUS_AVAILABLE: "✅",
    STATUS_FORBIDDEN: "🔒",
    STATUS_NO_KEY: "➖",
}

st.subheader("Verfuegbarkeitspruefung")
st.write(
    "Die Free-Tier-Grenzen der Anbieter aendern sich und haengen am konkreten Schluessel. "
    f"Der Check ruft jeden Endpunkt genau einmal fuer **{REFERENCE_TICKER}** ab und haelt "
    "das Ergebnis fest. Ein gesperrter Endpunkt (🔒) fuehrt dazu, dass die davon "
    "abhaengigen Kennzahlen dauerhaft als **n/a** gefuehrt werden."
)

if st.button("Check jetzt ausfuehren", type="primary"):
    with st.spinner("Endpunkte werden geprueft ..."):
        checker.run()
    st.success("Pruefung abgeschlossen.")

ergebnisse = checker.stored()
if not ergebnisse:
    st.info("Es liegt noch kein Pruefergebnis vor. Bitte den Check einmal ausfuehren.")
else:
    tabelle = pd.DataFrame(
        [
            {
                "": SYMBOLE.get(item.status, "⚠️"),
                "Quelle": item.source,
                "Endpunkt": item.endpoint,
                "Liefert": item.description,
                "Status": item.status,
                "Geprueft": item.checked_at.strftime("%d.%m.%Y %H:%M"),
                "Detail": (item.detail or "")[:160],
            }
            for item in ergebnisse
        ]
    )
    st.dataframe(tabelle, width="stretch", hide_index=True)

    gesperrt = [i for i in ergebnisse if i.status == STATUS_FORBIDDEN]
    if gesperrt:
        st.warning(
            "Gesperrte Endpunkte:\n\n"
            + "\n".join(f"- **{i.source} {i.endpoint}** – {i.description}" for i in gesperrt)
        )

st.divider()

st.subheader("Schluessel")
spalte_finnhub, spalte_anthropic = st.columns(2)
with spalte_finnhub:
    if config.has_finnhub:
        st.success("Finnhub-Schluessel ist hinterlegt.")
    else:
        st.info(
            "Kein Finnhub-Schluessel hinterlegt. Kostenlos unter "
            "https://finnhub.io/register erhaeltlich und in der `.env` unter "
            "`FINNHUB_API_KEY` eintragen."
        )
with spalte_anthropic:
    if config.has_anthropic:
        st.success("Anthropic-Schluessel ist hinterlegt - Schlagzeilen werden eingeordnet.")
    else:
        st.info(
            "Kein Anthropic-Schluessel hinterlegt. Die Sentiment-Einordnung bleibt "
            "damit n/a; es wird kein Ersatzwert erzeugt."
        )

st.divider()

st.subheader("Zugriffsprotokoll")
zusammenfassung = service.call_log.summary()
spalte_gesamt, spalte_cache, spalte_fehler = st.columns(3)
spalte_gesamt.metric("Zugriffe (24 Std.)", zusammenfassung["total"])
quote = (
    round(zusammenfassung["cache_hits"] / zusammenfassung["total"] * 100)
    if zusammenfassung["total"]
    else 0
)
spalte_cache.metric("Cache-Trefferquote", f"{quote} %")
spalte_fehler.metric("Fehlgeschlagen", zusammenfassung["errors"])

eintraege = service.call_log.recent(200)
if eintraege:
    protokoll = pd.DataFrame(eintraege)
    protokoll["cache_hit"] = protokoll["cache_hit"].map({1: "Cache", 0: "Live"})
    protokoll = protokoll.rename(
        columns={
            "ts": "Zeitpunkt", "source": "Quelle", "endpoint": "Endpunkt", "ticker": "Titel",
            "cache_hit": "Herkunft", "status": "Status", "duration_ms": "Dauer (ms)",
            "error": "Fehler",
        }
    )
    st.dataframe(protokoll, width="stretch", hide_index=True)
else:
    st.info("Noch keine Zugriffe protokolliert.")

st.divider()

st.subheader("Cache")
statistik = service.cache.stats()
if statistik:
    st.dataframe(
        pd.DataFrame(statistik).rename(
            columns={"data_kind": "Datenart", "source": "Quelle", "n": "Eintraege",
                     "oldest": "Aeltester Abruf"}
        ),
        width="stretch", hide_index=True,
    )
else:
    st.info("Der Cache ist leer.")

spalte_aufraeumen, spalte_leeren = st.columns(2)
if spalte_aufraeumen.button("Abgelaufene Eintraege entfernen"):
    st.success(f"{service.cache.purge_expired()} abgelaufene Eintraege entfernt.")
    st.rerun()
if spalte_leeren.button("Cache vollstaendig leeren"):
    st.success(f"{service.cache.clear()} Eintraege entfernt.")
    st.rerun()
