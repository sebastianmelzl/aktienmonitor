"""Datenquellen-Check.

Die Free-Tier-Grenzen der Anbieter verschieben sich regelmaessig und haengen am
konkreten Key. Statt sie zu behaupten, probiert dieser Check jeden Endpunkt
genau einmal aus und schreibt das Ergebnis in die Datenbank. Die Oberflaeche
zeigt damit an, was *dieser* Key tatsaechlich kann.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from ..storage.db import Database
from .base import SourceUnavailable
from .finnhub_source import FinnhubSource, InvalidApiKey
from .throttle import AccessForbidden, RateLimitExceeded
from .yfinance_source import YFinanceSource

logger = logging.getLogger("aktienmonitor.capabilities")

# Referenztitel fuer den Check: ein US-Standardwert, der bei jedem Anbieter
# vorhanden sein sollte.
REFERENCE_TICKER = "AAPL"

STATUS_AVAILABLE = "verfuegbar"
STATUS_FORBIDDEN = "gesperrt"
STATUS_NO_KEY = "kein Key"
STATUS_EMPTY = "leer"
STATUS_ERROR = "Fehler"


@dataclass(frozen=True)
class CapabilityResult:
    source: str
    endpoint: str
    description: str
    status: str
    detail: str | None
    checked_at: datetime

    @property
    def ok(self) -> bool:
        return self.status == STATUS_AVAILABLE


# (Endpunkt-Bezeichner, Beschreibung fuer die Oberflaeche)
FINNHUB_PROBES = (
    ("/quote", "Realtime-Kurs"),
    ("/stock/profile2", "Firmenprofil, Sektor, Branche"),
    ("/stock/metric", "Basis-Kennzahlen (KGV, ROE, Margen, ...)"),
    ("/stock/recommendation", "Analysten-Konsens"),
    ("/stock/price-target", "Kursziele"),
    ("/stock/earnings", "Earnings-Surprises"),
    ("/company-news", "Unternehmens-Schlagzeilen"),
)

YFINANCE_PROBES = (
    ("info", "Stammdaten und Basis-Kennzahlen"),
    ("fast_info", "Kurs, Marktkapitalisierung"),
    ("history", "Kurshistorie (Basis der Technik-Analyse)"),
    ("financials", "Bilanz, GuV, Cashflow"),
    ("analyst", "Konsens, Kursziele, Schaetzungsrevisionen"),
    ("news", "Schlagzeilen"),
)


class CapabilityChecker:
    """Prueft alle Endpunkte und legt das Ergebnis ab."""

    def __init__(
        self, db: Database, yfinance: YFinanceSource, finnhub: FinnhubSource | None
    ) -> None:
        self.db = db
        self.yfinance = yfinance
        self.finnhub = finnhub

    def run(self, ticker: str = REFERENCE_TICKER) -> list[CapabilityResult]:
        """Fuehrt den kompletten Check aus und speichert die Ergebnisse."""
        results: list[CapabilityResult] = []
        results.extend(self._check_yfinance(ticker))
        results.extend(self._check_finnhub(ticker))
        self._store(results)
        return results

    # --- Einzelpruefungen ----------------------------------------------------

    def _check_yfinance(self, ticker: str) -> list[CapabilityResult]:
        callers = {
            "info": lambda: self.yfinance.profile(ticker, force_refresh=True),
            "fast_info": lambda: self.yfinance.quote(ticker, force_refresh=True),
            "history": lambda: self.yfinance.price_history(
                ticker, period="1mo", force_refresh=True
            ),
            "financials": lambda: self.yfinance.fundamentals(ticker, force_refresh=True),
            "analyst": lambda: self.yfinance.analyst(ticker, force_refresh=True),
            "news": lambda: self.yfinance.news(ticker, force_refresh=True),
        }
        results = []
        for endpoint, description in YFINANCE_PROBES:
            results.append(
                self._probe("yfinance", endpoint, description, callers[endpoint])
            )
        return results

    def _check_finnhub(self, ticker: str) -> list[CapabilityResult]:
        now = datetime.now(UTC)
        if self.finnhub is None or not self.finnhub.available:
            return [
                CapabilityResult(
                    source="finnhub",
                    endpoint=endpoint,
                    description=description,
                    status=STATUS_NO_KEY,
                    detail="FINNHUB_API_KEY ist in der .env nicht gesetzt",
                    checked_at=now,
                )
                for endpoint, description in FINNHUB_PROBES
            ]

        source = self.finnhub
        callers = {
            "/quote": lambda: source.quote(ticker, force_refresh=True),
            "/stock/profile2": lambda: source.profile(ticker, force_refresh=True),
            "/stock/metric": lambda: source.basic_financials(ticker, force_refresh=True),
            "/stock/recommendation": lambda: source.recommendations(ticker, force_refresh=True),
            "/stock/price-target": lambda: source.price_target(ticker, force_refresh=True),
            "/stock/earnings": lambda: source.earnings_surprises(ticker, force_refresh=True),
            "/company-news": lambda: source.company_news(ticker, force_refresh=True),
        }
        return [
            self._probe("finnhub", endpoint, description, callers[endpoint])
            for endpoint, description in FINNHUB_PROBES
        ]

    def _probe(self, source: str, endpoint: str, description: str, caller) -> CapabilityResult:
        now = datetime.now(UTC)
        try:
            result = caller()
        except AccessForbidden as exc:
            return CapabilityResult(source, endpoint, description, STATUS_FORBIDDEN, str(exc), now)
        except InvalidApiKey as exc:
            return CapabilityResult(source, endpoint, description, STATUS_ERROR, str(exc), now)
        except SourceUnavailable as exc:
            return CapabilityResult(source, endpoint, description, STATUS_NO_KEY, str(exc), now)
        except RateLimitExceeded as exc:
            return CapabilityResult(source, endpoint, description, STATUS_ERROR, str(exc), now)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Check %s/%s fehlgeschlagen: %s", source, endpoint, exc)
            return CapabilityResult(
                source, endpoint, description, STATUS_ERROR, f"{type(exc).__name__}: {exc}", now
            )

        if result.ok:
            return CapabilityResult(source, endpoint, description, STATUS_AVAILABLE, None, now)

        error = result.error or "Keine Daten geliefert"
        # Die Runtime faengt 403 ab und meldet sie als Fehlertext zurueck.
        status = STATUS_FORBIDDEN if "403" in error or "gesperrt" in error else STATUS_EMPTY
        return CapabilityResult(source, endpoint, description, status, error, now)

    # --- Persistenz ----------------------------------------------------------

    def _store(self, results: list[CapabilityResult]) -> None:
        with self.db.connect() as conn:
            for item in results:
                conn.execute(
                    """
                    INSERT INTO source_capability (source, endpoint, status, detail, checked_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(source, endpoint) DO UPDATE SET
                        status = excluded.status,
                        detail = excluded.detail,
                        checked_at = excluded.checked_at
                    """,
                    (
                        item.source,
                        item.endpoint,
                        item.status,
                        item.detail,
                        item.checked_at.isoformat(),
                    ),
                )

    def stored(self) -> list[CapabilityResult]:
        """Liest das zuletzt gespeicherte Ergebnis."""
        descriptions = {
            ("finnhub", endpoint): desc for endpoint, desc in FINNHUB_PROBES
        } | {("yfinance", endpoint): desc for endpoint, desc in YFINANCE_PROBES}
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT source, endpoint, status, detail, checked_at FROM source_capability"
                " ORDER BY source, endpoint"
            ).fetchall()
        return [
            CapabilityResult(
                source=row["source"],
                endpoint=row["endpoint"],
                description=descriptions.get((row["source"], row["endpoint"]), ""),
                status=row["status"],
                detail=row["detail"],
                checked_at=datetime.fromisoformat(row["checked_at"]),
            )
            for row in rows
        ]
