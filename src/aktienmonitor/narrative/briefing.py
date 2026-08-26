"""Faktenblatt eines Titels.

Stellt genau die Zahlen zusammen, auf die sich eine Begruendung stuetzen darf.
Reine Textaufbereitung, ohne Netz und ohne Sprachmodell - und damit einzeln
pruefbar. Was hier nicht drinsteht, kann in der Begruendung nicht auftauchen.
"""

from __future__ import annotations

from ..formatting import format_metric, german_number
from ..scoring.engine import TotalScore

# Wie viele Beitraege je Richtung ins Faktenblatt kommen.
TOP_CONTRIBUTIONS = 5


def _contribution_line(contribution, currency: str | None) -> str:
    teile = [
        f"{contribution.metric.label}: {format_metric(contribution.metric, currency)}",
        f"{contribution.points:.0f} von 100 Punkten",
        f"Gewicht {german_number(contribution.rule.weight, 1)}",
        f"Bewertung {contribution.mode_label}",
    ]
    if contribution.comparison is not None:
        teile.append(
            f"{contribution.comparison.percentile:.0f}. Perzentil in "
            f"'{contribution.comparison.sector}', Median "
            f"{german_number(contribution.comparison.median, 2)}, "
            f"{contribution.comparison.peer_count} Vergleichstitel"
        )
    return "  - " + "; ".join(teile)


def build_briefing(snapshot, scored: TotalScore, changes=None) -> str:
    """Baut das Faktenblatt als Klartext.

    Enthaelt Stammdaten, Scores samt Abdeckung, die staerksten und schwaechsten
    Beitraege, nicht bewertete Kennzahlen mit Grund und - sofern vorhanden - die
    erkannten Veraenderungen.
    """
    profile = snapshot.profile
    currency = snapshot.currency
    zeilen: list[str] = []

    zeilen.append(f"Titel: {snapshot.ticker}" + (f" ({profile.name})" if profile.name else ""))
    zeilen.append(f"Branche: {profile.sector or 'nicht angegeben'}")
    if profile.is_fund:
        zeilen.append(
            "Hinweis: Fonds oder ETF - Unternehmenskennzahlen existieren hier nicht."
        )
    if snapshot.price is not None:
        zeilen.append(f"Kurs: {german_number(snapshot.price, 2)} {currency or ''}".rstrip())
    if snapshot.change_percent is not None:
        zeilen.append(
            f"Veraenderung zum Vortag: {german_number(snapshot.change_percent, 2)} %"
        )

    zeilen.append("")
    zeilen.append(
        "Gesamtscore: "
        + (f"{scored.total:.0f} von 100" if scored.is_available else "nicht berechenbar")
    )
    for name, category in scored.categories.items():
        anteil = scored.effective_weights.get(name, 0.0)
        wert = f"{category.score:.0f}" if category.is_available else "n/a"
        zeilen.append(
            f"  {category.label}: {wert} "
            f"(aus {category.used_count} von {category.total_count} Kennzahlen, "
            f"Gewicht im Gesamtscore {anteil * 100:.0f} %)"
        )
    if scored.redistributed:
        zeilen.append(
            "  Ohne Daten und daher nicht im Gesamtscore: "
            + ", ".join(scored.redistributed)
        )

    alle = [c for k in scored.categories.values() for c in k.included]
    if alle:
        nach_beitrag = sorted(alle, key=lambda c: c.points or 0.0, reverse=True)
        zeilen.append("")
        zeilen.append("Staerkste Kennzahlen:")
        zeilen.extend(
            _contribution_line(c, currency) for c in nach_beitrag[:TOP_CONTRIBUTIONS]
        )
        zeilen.append("")
        zeilen.append("Schwaechste Kennzahlen:")
        zeilen.extend(
            _contribution_line(c, currency)
            for c in list(reversed(nach_beitrag))[:TOP_CONTRIBUTIONS]
        )

    fehlend = [c for k in scored.categories.values() for c in k.excluded]
    if fehlend:
        nach_grund: dict[str, list[str]] = {}
        for contribution in fehlend:
            nach_grund.setdefault(contribution.excluded_reason or "", []).append(
                contribution.metric.label
            )
        zeilen.append("")
        zeilen.append("Nicht in die Bewertung eingegangen:")
        for grund, labels in nach_grund.items():
            zeilen.append(f"  - {grund}: {', '.join(sorted(labels))}")

    if changes is not None and getattr(changes, "has_events", False):
        zeilen.append("")
        zeilen.append(f"Veraenderungen {changes.reference_text}:")
        zeilen.extend(f"  - {e.label}: {e.detail}" for e in changes.events)

    return "\n".join(zeilen)
