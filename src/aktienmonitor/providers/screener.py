"""Marktweite Abfrage ueber den Yahoo-Screener.

Uebersetzt die Suchprofile aus ``screening/profiles.py`` in die Abfragesprache
von yfinance und fuehrt die Abfrage ueber ``ProviderRuntime`` aus - also mit
demselben Cache, Rate-Limit und Protokoll wie jeder andere Abruf.

Ein Lauf ist genau eine Anfrage und liefert bis zu 250 Titel. Die eigentliche
Bewertung passiert erst danach und nur fuer die besten Treffer, weil dafuer je
Titel mehrere Abrufe noetig sind.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import DATA_KIND_PROFILE
from ..models import Provenance, ProviderResult
from ..screening.profiles import (
    FIELD_REGION,
    FIELD_SECTOR,
    Comparison,
    ScreenRequest,
)
from .base import ProviderRuntime

logger = logging.getLogger("aktienmonitor.providers.screener")

SOURCE_KEY = "yfinance"

# Die Marktabfrage aendert sich langsam; ein halber Tag Cache spart Abrufe,
# ohne dass das Ergebnis veraltet wirkt.
SCREEN_TTL_SECONDS = 12 * 3600

_COMPARISON_TO_OPERATOR = {
    Comparison.GREATER: "gt",
    Comparison.LESS: "lt",
    Comparison.BETWEEN: "btwn",
    Comparison.EQUALS: "eq",
}


def build_query(request: ScreenRequest) -> Any:
    """Baut die ``EquityQuery`` aus einem Suchauftrag.

    Wird nur hier gebraucht - so bleibt ``screening/`` frei von yfinance und
    einzeln pruefbar.
    """
    from yfinance import EquityQuery

    bedingungen: list[Any] = []

    for criterion in request.all_criteria():
        operator = _COMPARISON_TO_OPERATOR[criterion.comparison]
        if criterion.comparison is Comparison.BETWEEN:
            untere, obere = criterion.value  # type: ignore[misc]
            bedingungen.append(
                EquityQuery("btwn", [criterion.field_name, float(untere), float(obere)])
            )
        else:
            bedingungen.append(
                EquityQuery(operator, [criterion.field_name, float(criterion.value)])
            )

    if request.regions:
        bedingungen.append(
            EquityQuery("is-in", [FIELD_REGION, *[r.lower() for r in request.regions]])
            if len(request.regions) > 1
            else EquityQuery("eq", [FIELD_REGION, request.regions[0].lower()])
        )

    if request.sectors:
        bedingungen.append(
            EquityQuery("is-in", [FIELD_SECTOR, *request.sectors])
            if len(request.sectors) > 1
            else EquityQuery("eq", [FIELD_SECTOR, request.sectors[0]])
        )

    if len(bedingungen) == 1:
        return bedingungen[0]
    return EquityQuery("and", bedingungen)


def cache_signature(request: ScreenRequest) -> str:
    """Kennzeichnet einen Suchauftrag eindeutig fuer den Cache."""
    teile = [
        request.profile.key,
        ",".join(sorted(request.regions)),
        ",".join(sorted(request.sectors)),
        f"{request.min_market_cap:.0f}",
        str(request.limit),
    ]
    return "|".join(teile)


class MarketScreener:
    """Fuehrt marktweite Abfragen aus."""

    source = Provenance.YFINANCE
    source_key = SOURCE_KEY

    def __init__(self, runtime: ProviderRuntime) -> None:
        self.runtime = runtime

    def run(
        self, request: ScreenRequest, *, force_refresh: bool = False, cache_only: bool = False
    ) -> ProviderResult:
        """Fuehrt die Marktabfrage aus und gibt die Rohantwort zurueck."""

        def load() -> dict[str, Any] | None:
            import yfinance as yf

            query = build_query(request)
            antwort = yf.screen(
                query,
                size=min(request.limit, 250),
                sortField=request.profile.sort_field,
                sortAsc=request.profile.sort_ascending,
            )
            if not isinstance(antwort, dict):
                return None
            # Nur das Noetige behalten - die Rohantwort enthaelt viel Ballast.
            return {
                "count": antwort.get("count"),
                "total": antwort.get("total"),
                "quotes": antwort.get("quotes", []),
            }

        return self.runtime.fetch(
            source=self.source,
            source_key=self.source_key,
            endpoint="screen",
            ticker=None,
            data_kind=DATA_KIND_PROFILE,
            loader=load,
            cache_parts=(cache_signature(request),),
            ttl_override=SCREEN_TTL_SECONDS,
            force_refresh=force_refresh,
            cache_only=cache_only,
        )
