"""Erzeugung der Begruendung ueber die Anthropic-API.

Der Text fasst ausschliesslich das uebergebene Faktenblatt zusammen. Das Modell
darf kein Weltwissen ueber das Unternehmen einbringen, keine Kursprognose
abgeben und keine Handelsbegriffe verwenden - das steht so in der Anweisung und
wird im Test geprueft.

Wie beim Sentiment gilt: kein Schluessel, kein Text. Es wird nichts geraten.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
from dataclasses import dataclass
from typing import Any

from ..storage.cache import Cache

logger = logging.getLogger("aktienmonitor.narrative")

DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 1500
CACHE_TTL_SECONDS = 90 * 24 * 3600

SYSTEM_PROMPT = """Du fasst ein Faktenblatt zu einem Wertpapier in wenigen
Saetzen zusammen. Das Faktenblatt enthaelt berechnete Kennzahlen und Punkte aus
einem Bewertungsmodell.

Strenge Regeln:
- Stuetze dich AUSSCHLIESSLICH auf die Zahlen im Faktenblatt. Bringe kein
  Wissen ueber das Unternehmen, seine Produkte, seine Geschichte oder aktuelle
  Ereignisse ein. Was nicht im Faktenblatt steht, existiert fuer dich nicht.
- Nenne konkrete Zahlen aus dem Faktenblatt, wenn du eine Aussage machst.
- Keine Kursprognose, keine Aussage darueber, ob sich ein Kauf lohnt, keine
  Begriffe wie kaufen, verkaufen, halten, empfehlen, Chance oder Risiko im
  Sinne einer Handlungsaufforderung.
- Das Bewertungsmodell ist eine Konvention, keine belegte Prognose. Formuliere
  entsprechend zurueckhaltend: "erreicht", "liegt", "faellt auf", nicht
  "ueberzeugt" oder "ist attraktiv".
- Wenn Kennzahlen fehlen, benenne das als Einschraenkung der Aussagekraft.
- Antworte auf Deutsch, sachlich und knapp.

Gliederung:
- einordnung: ein bis zwei Saetze, was diesen Titel im Modell auszeichnet.
- dafuer: bis zu drei Punkte, die im Modell hohe Punktzahlen erzeugen.
- dagegen: bis zu drei Punkte, die im Modell niedrige Punktzahlen erzeugen.
- datenluecken: fehlende Kennzahlen und was das fuer die Aussagekraft bedeutet."""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "einordnung": {"type": "string"},
        "dafuer": {"type": "array", "items": {"type": "string"}},
        "dagegen": {"type": "array", "items": {"type": "string"}},
        "datenluecken": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["einordnung", "dafuer", "dagegen", "datenluecken"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Narrative:
    """Die erzeugte Begruendung."""

    einordnung: str
    dafuer: tuple[str, ...] = ()
    dagegen: tuple[str, ...] = ()
    datenluecken: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.einordnung.strip()


def _anthropic_installed() -> bool:
    return importlib.util.find_spec("anthropic") is not None


def briefing_key(ticker: str, briefing: str) -> str:
    """Schluessel je Datenstand.

    Aendern sich die Zahlen nicht, wird auch kein neuer Text erzeugt - der
    gespeicherte reicht dann.
    """
    digest = hashlib.sha256(briefing.encode("utf-8")).hexdigest()[:32]
    return f"narrative|{ticker.upper()}|{digest}"


class NarrativeGenerator:
    """Erzeugt Begruendungen und legt sie je Datenstand ab."""

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
        self._client = client

    @property
    def available(self) -> bool:
        if self._client is not None:
            return True
        return bool(self.api_key) and _anthropic_installed()

    @property
    def unavailable_reason(self) -> str | None:
        if self.available:
            return None
        if not self.api_key:
            return "Kein Anthropic-Schluessel hinterlegt (ANTHROPIC_API_KEY in .env)"
        return "Paket 'anthropic' ist nicht installiert: uv pip install -e '.[dev]'"

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def generate(
        self, ticker: str, briefing: str, *, cache_only: bool = False
    ) -> Narrative | None:
        """Liefert die Begruendung - aus dem Cache oder frisch erzeugt.

        ``None`` bedeutet: es gibt keinen Text. Die Oberflaeche zeigt dann die
        berechneten Zahlen ohne Fliesstext, statt etwas zu erfinden.
        """
        if not briefing.strip():
            return None

        key = briefing_key(ticker, briefing)
        gespeichert = self.cache.get(key, allow_stale=True)
        if gespeichert is not None and isinstance(gespeichert.payload, dict):
            return _from_payload(gespeichert.payload)

        if cache_only or not self.available:
            return None

        try:
            antwort = self._get_client().messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": "Fasse dieses Faktenblatt zusammen:\n\n" + briefing,
                    }
                ],
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
                },
            )
        except Exception as exc:  # noqa: BLE001 - ohne Text ist die Seite weiter nutzbar
            logger.warning("Begruendung fuer %s fehlgeschlagen: %s", ticker, exc)
            return None

        if getattr(antwort, "stop_reason", None) == "refusal":
            logger.warning("Begruendung fuer %s wurde abgelehnt", ticker)
            return None

        text = next(
            (b.text for b in antwort.content if getattr(b, "type", None) == "text"), None
        )
        if not text:
            return None
        try:
            daten = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Begruendung fuer %s war kein gueltiges JSON", ticker)
            return None

        narrative = _from_payload(daten)
        if narrative is None or narrative.is_empty:
            return None

        self.cache.set(
            key,
            {
                "einordnung": narrative.einordnung,
                "dafuer": list(narrative.dafuer),
                "dagegen": list(narrative.dagegen),
                "datenluecken": list(narrative.datenluecken),
            },
            source="anthropic",
            data_kind="narrative",
            ttl_seconds=CACHE_TTL_SECONDS,
            ticker=ticker,
        )
        return narrative


def _strings(value: Any, limit: int = 5) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(v).strip() for v in value if str(v).strip())[:limit]


def _from_payload(payload: dict[str, Any]) -> Narrative | None:
    einordnung = str(payload.get("einordnung") or "").strip()
    if not einordnung:
        return None
    return Narrative(
        einordnung=einordnung,
        dafuer=_strings(payload.get("dafuer")),
        dagegen=_strings(payload.get("dagegen")),
        datenluecken=_strings(payload.get("datenluecken")),
    )
