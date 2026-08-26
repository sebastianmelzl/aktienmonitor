"""Klassifikation von Schlagzeilen ueber die Anthropic-API.

Grundsaetze:

* **Kein Schluessel, keine Einordnung.** Fehlt der Schluessel oder scheitert der
  Aufruf, bleiben die Meldungen unbewertet. Es wird nichts geraten.
* **Jede Einordnung ist belegt.** Zu jeder Schlagzeile wird eine kurze
  Begruendung mitgefuehrt, und die Originalquelle bleibt stets verlinkt.
* **Einmal eingeordnet, dauerhaft gespeichert.** Schlagzeilen aendern sich
  nicht, also wird das Ergebnis je Schlagzeile zwischengespeichert. Ein
  erneuter Lauf kostet dadurch praktisch nichts.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from ..models import NewsItem
from ..storage.cache import Cache

logger = logging.getLogger("aktienmonitor.sentiment")

# Vorgabemodell. Ueber ANTHROPIC_MODEL in der .env aenderbar.
DEFAULT_MODEL = "claude-opus-5"

# Schlagzeilen je Anfrage. Kleine Buendel halten die Antwort ueberschaubar und
# begrenzen den Schaden, wenn ein einzelner Aufruf scheitert.
BATCH_SIZE = 20

# Schlagzeilen sind unveraenderlich - ein Jahr Cache ist grosszuegig, aber
# fachlich korrekt.
CACHE_TTL_SECONDS = 365 * 24 * 3600

MAX_TOKENS = 4000


class SentimentLabel(StrEnum):
    POSITIVE = "positiv"
    NEUTRAL = "neutral"
    NEGATIVE = "negativ"


# Zuordnung der englischen Modellantwort auf die deutschen Bezeichnungen.
_LABEL_MAP = {
    "positive": SentimentLabel.POSITIVE,
    "neutral": SentimentLabel.NEUTRAL,
    "negative": SentimentLabel.NEGATIVE,
}

SYSTEM_PROMPT = """Du ordnest Finanz-Schlagzeilen danach ein, wie sie sich
voraussichtlich auf die Geschaeftsaussichten des genannten Unternehmens
auswirken.

Regeln:
- Bewerte ausschliesslich die Schlagzeile selbst. Ziehe kein Vorwissen ueber
  den aktuellen Kurs oder die Marktlage heran.
- "positive": deutet auf verbesserte Geschaeftsaussichten hin (uebertroffene
  Erwartungen, Grossauftraege, angehobene Prognosen, erfolgreiche Zulassungen).
- "negative": deutet auf verschlechterte Aussichten hin (verfehlte Erwartungen,
  gesenkte Prognosen, Rueckrufe, Rechtsstreitigkeiten, Abgaenge in der Fuehrung).
- "neutral": reine Ankuendigungen, Termine, Analystenkommentare ohne klare
  Richtung, allgemeine Branchenmeldungen, oder wenn die Schlagzeile zu
  unspezifisch ist.
- Im Zweifel "neutral". Eine unsichere Einordnung ist schaedlicher als keine
  Aussage.
- Die Begruendung ist ein knapper deutscher Satz, der sich nur auf den Wortlaut
  der Schlagzeile stuetzt.

Antworte ausschliesslich im vorgegebenen JSON-Format."""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "label": {"type": "string", "enum": ["positive", "neutral", "negative"]},
                    "rationale": {"type": "string"},
                },
                "required": ["index", "label", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


def headline_key(item: NewsItem) -> str:
    """Stabiler Schluessel je Schlagzeile - unabhaengig vom Titel, zu dem sie gehoert."""
    roh = f"{item.headline}|{item.url}".encode()
    return hashlib.sha256(roh).hexdigest()[:32]


@dataclass(frozen=True)
class Verdict:
    label: SentimentLabel
    rationale: str


class SentimentUnavailable(RuntimeError):
    """Die Einordnung ist nicht moeglich (kein Schluessel oder Paket fehlt)."""


class SentimentClassifier:
    """Ordnet Schlagzeilen ein - mit Cache und ohne jeden Ersatzwert."""

    def __init__(
        self,
        api_key: str | None,
        cache: Cache,
        *,
        model: str = DEFAULT_MODEL,
        client: Any = None,
    ) -> None:
        self.api_key = api_key
        self.cache = cache
        self.model = model
        # Ein vorgegebener Client erlaubt Tests ohne Netzzugriff.
        self._client = client

    @property
    def available(self) -> bool:
        return bool(self.api_key) or self._client is not None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise SentimentUnavailable(
                "Kein Anthropic-Schluessel hinterlegt (ANTHROPIC_API_KEY in .env)"
            )
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - Installationsproblem
            raise SentimentUnavailable(
                "Paket 'anthropic' ist nicht installiert: pip install -e '.[sentiment]'"
            ) from exc
        self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    # --- oeffentliche Schnittstelle -----------------------------------------

    def classify(self, items: list[NewsItem], *, cache_only: bool = False) -> list[NewsItem]:
        """Ordnet die Meldungen ein und gibt sie ergaenzt zurueck.

        Meldungen, fuer die keine Einordnung zustande kommt, werden unveraendert
        zurueckgegeben - ihr ``sentiment`` bleibt ``None`` und die Oberflaeche
        weist sie als nicht eingeordnet aus.

        Mit ``cache_only`` unterbleibt jeder API-Aufruf: es werden nur bereits
        gespeicherte Einordnungen verwendet. Das ist die Betriebsart beim Aufbau
        der Uebersicht, die keine Kosten verursachen darf.
        """
        if not items:
            return []

        ergebnis: list[NewsItem] = list(items)
        offen: list[tuple[int, NewsItem]] = []

        # 1. Was schon eingeordnet wurde, aus dem Cache holen.
        for position, item in enumerate(items):
            gespeichert = self._from_cache(item)
            if gespeichert is not None:
                ergebnis[position] = replace(
                    item,
                    sentiment=str(gespeichert.label),
                    sentiment_rationale=gespeichert.rationale,
                )
            else:
                offen.append((position, item))

        if not offen:
            logger.info("Sentiment: alle %d Schlagzeilen aus dem Cache", len(items))
            return ergebnis

        if cache_only:
            logger.info(
                "Sentiment: %d Schlagzeilen ohne gespeicherte Einordnung (kein Abruf angefordert)",
                len(offen),
            )
            return ergebnis

        if not self.available:
            logger.info(
                "Sentiment: kein Schluessel - %d Schlagzeilen bleiben unbewertet", len(offen)
            )
            return ergebnis

        # 2. Den Rest in Buendeln klassifizieren.
        for start in range(0, len(offen), BATCH_SIZE):
            buendel = offen[start : start + BATCH_SIZE]
            try:
                urteile = self._classify_batch([item for _, item in buendel])
            except SentimentUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001 - ein Buendel darf den Rest nicht kippen
                logger.warning("Sentiment-Buendel fehlgeschlagen: %s", exc)
                continue

            for lokal, (position, item) in enumerate(buendel):
                urteil = urteile.get(lokal)
                if urteil is None:
                    # Das Modell hat zu dieser Schlagzeile nichts geliefert -
                    # sie bleibt unbewertet statt auf "neutral" gesetzt zu werden.
                    continue
                self._to_cache(item, urteil)
                ergebnis[position] = replace(
                    item, sentiment=str(urteil.label), sentiment_rationale=urteil.rationale
                )
        return ergebnis

    # --- Cache ---------------------------------------------------------------

    def _cache_key(self, item: NewsItem) -> str:
        return f"sentiment|{self.model}|{headline_key(item)}"

    def _from_cache(self, item: NewsItem) -> Verdict | None:
        eintrag = self.cache.get(self._cache_key(item), allow_stale=True)
        if eintrag is None or not isinstance(eintrag.payload, dict):
            return None
        rohes_label = eintrag.payload.get("label")
        try:
            label = SentimentLabel(rohes_label)
        except ValueError:
            return None
        return Verdict(label=label, rationale=str(eintrag.payload.get("rationale") or ""))

    def _to_cache(self, item: NewsItem, verdict: Verdict) -> None:
        self.cache.set(
            self._cache_key(item),
            {"label": str(verdict.label), "rationale": verdict.rationale},
            source="anthropic",
            data_kind="sentiment",
            ttl_seconds=CACHE_TTL_SECONDS,
        )

    # --- API-Aufruf ----------------------------------------------------------

    def _classify_batch(self, items: list[NewsItem]) -> dict[int, Verdict]:
        """Ordnet ein Buendel ein. Schluessel des Ergebnisses ist der Index im Buendel."""
        zeilen = [
            f"{i}. [{item.source_name}] {item.headline}" for i, item in enumerate(items)
        ]
        anfrage = (
            "Ordne jede der folgenden Schlagzeilen ein. Gib fuer jede Zeile genau einen "
            "Eintrag mit ihrem Index zurueck.\n\n" + "\n".join(zeilen)
        )

        antwort = self._get_client().messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": anfrage}],
            output_config={
                # Klassifikation braucht keine tiefe Abwaegung.
                "effort": "low",
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
        )

        if getattr(antwort, "stop_reason", None) == "refusal":
            logger.warning("Sentiment: Anfrage wurde abgelehnt")
            return {}

        text = next(
            (block.text for block in antwort.content if getattr(block, "type", None) == "text"),
            None,
        )
        if not text:
            return {}

        try:
            daten = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Sentiment: Antwort war kein gueltiges JSON")
            return {}

        urteile: dict[int, Verdict] = {}
        for eintrag in daten.get("verdicts", []):
            if not isinstance(eintrag, dict):
                continue
            index = eintrag.get("index")
            label = _LABEL_MAP.get(str(eintrag.get("label", "")).lower())
            if not isinstance(index, int) or label is None or not (0 <= index < len(items)):
                continue
            urteile[index] = Verdict(
                label=label, rationale=str(eintrag.get("rationale") or "").strip()
            )
        return urteile
