"""Aufteilung eines Betrags auf mehrere Titel.

Was dieses Modul tut: es rechnet aus, wie sich eine Summe nach *vorgegebenen
Regeln* auf eine Auswahl verteilt - inklusive Obergrenzen je Position und je
Branche, Mindestgroessen und ganzen Stueckzahlen.

Was es nicht tut und nicht kann: beurteilen, ob eine Anlage sinnvoll ist. Die
zugrundeliegenden Scores beruhen auf Schwellen, die als Konvention gesetzt und
nicht auf Prognosekraft geprueft wurden. Die Aufteilung beruecksichtigt weder
Korrelationen zwischen den Titeln noch die uebrige Vermoegenslage, den
Anlagehorizont, Steuern oder Gebuehren.

Die Obergrenzen sind der eigentliche Zweck: eine rein score-proportionale
Aufteilung landet regelmaessig zu grossen Teilen in einer einzigen Branche.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

# Wie oft die Umverteilung nach dem Deckeln wiederholt wird. Jede Runde kann
# neue Ueberschreitungen erzeugen; in der Praxis ist nach wenigen Runden Ruhe.
MAX_REBALANCE_ROUNDS = 25
EPSILON = 1e-9


class AllocationMethod(StrEnum):
    EQUAL = "Gleichgewichtet"
    SCORE_WEIGHTED = "Nach Score gewichtet"


@dataclass(frozen=True)
class AllocationConstraints:
    """Regeln, nach denen aufgeteilt wird. Alle Anteile als Bruchteil von 1."""

    max_position_share: float = 0.25
    max_sector_share: float = 0.40
    min_position_amount: float = 250.0
    # Mindest-Datenabdeckung des Fundamental-Teilscores in Prozent. Ein Score
    # aus drei von zwanzig Kennzahlen taugt nicht als Grundlage.
    #
    # Die Schwelle ist bewusst nicht hoeher: die sektorrelativen Regeln machen
    # rund 47 % der Fundamentalgewichtung aus und fallen ohne ausreichende
    # Vergleichsgruppe komplett weg. Ohne Branchengruppen im Universum sind
    # daher hoechstens etwa 53 % erreichbar - eine Schwelle von 50 % wuerde
    # dann fast jeden Titel ausschliessen.
    min_coverage: float = 35.0
    min_score: float | None = None
    max_positions: int = 10

    def describe(self) -> list[str]:
        """Die geltenden Regeln im Klartext - fuer die Anzeige."""
        return [
            f"Hoechstens {self.max_position_share * 100:.0f} % in einen Titel",
            f"Hoechstens {self.max_sector_share * 100:.0f} % in eine Branche",
            f"Mindestens {self.min_position_amount:.0f} je Position",
            f"Mindestens {self.min_coverage:.0f} % Datenabdeckung fundamental",
            f"Hoechstens {self.max_positions} Positionen",
        ] + ([f"Mindestscore {self.min_score:.0f}"] if self.min_score is not None else [])


@dataclass
class AllocationItem:
    """Eine Position im Vorschlag."""

    ticker: str
    name: str
    sector: str
    score: float
    price: float | None
    currency: str | None
    weight: float = 0.0
    target_amount: float = 0.0
    shares: int = 0
    invested_amount: float = 0.0

    @property
    def leftover(self) -> float:
        """Was vom Zielbetrag wegen ganzer Stueckzahlen uebrig bleibt."""
        return max(0.0, self.target_amount - self.invested_amount)


@dataclass
class AllocationResult:
    """Ergebnis der Aufteilung samt allem, was nicht hineinkam."""

    amount: float
    method: AllocationMethod
    constraints: AllocationConstraints
    items: list[AllocationItem] = field(default_factory=list)
    excluded: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def invested(self) -> float:
        return sum(item.invested_amount for item in self.items)

    @property
    def cash_left(self) -> float:
        return max(0.0, self.amount - self.invested)

    @property
    def sector_shares(self) -> dict[str, float]:
        """Tatsaechlicher Anteil je Branche nach ganzen Stueckzahlen, in Prozent."""
        gesamt = self.invested
        if gesamt <= 0:
            return {}
        anteile: dict[str, float] = {}
        for item in self.items:
            anteile[item.sector] = anteile.get(item.sector, 0.0) + item.invested_amount
        return {sector: betrag / gesamt * 100.0 for sector, betrag in anteile.items()}

    @property
    def has_items(self) -> bool:
        return bool(self.items)


def _cap_weights(
    weights: dict[str, float], sectors: dict[str, str], constraints: AllocationConstraints
) -> dict[str, float]:
    """Deckelt Positions- und Branchenanteile und verteilt den Ueberhang um.

    Nach jedem Deckeln wird der frei gewordene Anteil auf die noch nicht
    gedeckelten Positionen verteilt - das kann dort neue Ueberschreitungen
    ausloesen, deshalb die Wiederholung.
    """
    aktuell = dict(weights)

    for _ in range(MAX_REBALANCE_ROUNDS):
        geaendert = False

        # --- Obergrenze je Position -----------------------------------------
        ueberhang = 0.0
        frei: list[str] = []
        for ticker, gewicht in aktuell.items():
            if gewicht > constraints.max_position_share + EPSILON:
                ueberhang += gewicht - constraints.max_position_share
                aktuell[ticker] = constraints.max_position_share
                geaendert = True
            elif gewicht < constraints.max_position_share - EPSILON:
                frei.append(ticker)

        if ueberhang > EPSILON and frei:
            basis = sum(aktuell[t] for t in frei)
            for ticker in frei:
                anteil = (aktuell[ticker] / basis) if basis > 0 else 1.0 / len(frei)
                aktuell[ticker] += ueberhang * anteil

        # --- Obergrenze je Branche ------------------------------------------
        je_branche: dict[str, float] = {}
        for ticker, gewicht in aktuell.items():
            branche = sectors.get(ticker, "")
            je_branche[branche] = je_branche.get(branche, 0.0) + gewicht

        for branche, summe in je_branche.items():
            if summe <= constraints.max_sector_share + EPSILON:
                continue
            faktor = constraints.max_sector_share / summe
            befreit = summe - constraints.max_sector_share
            for ticker in [t for t in aktuell if sectors.get(t, "") == branche]:
                aktuell[ticker] *= faktor
            andere = [t for t in aktuell if sectors.get(t, "") != branche]
            if andere:
                basis = sum(aktuell[t] for t in andere)
                for ticker in andere:
                    anteil = (aktuell[ticker] / basis) if basis > 0 else 1.0 / len(andere)
                    aktuell[ticker] += befreit * anteil
            geaendert = True

        if not geaendert:
            break

    summe = sum(aktuell.values())
    return {t: g / summe for t, g in aktuell.items()} if summe > 0 else aktuell


def _capacity(sectors: dict[str, str], constraints: AllocationConstraints) -> float:
    """Wie viel Anteil sich unter beiden Deckeln ueberhaupt unterbringen laesst.

    Je Branche begrenzt entweder der Branchendeckel oder die Zahl ihrer Titel
    mal dem Positionsdeckel - je nachdem, was kleiner ist. Liegt die Summe
    unter 1, sind die Regeln mit dieser Auswahl nicht gleichzeitig erfuellbar.
    """
    je_branche: dict[str, int] = {}
    for branche in sectors.values():
        je_branche[branche] = je_branche.get(branche, 0) + 1
    return sum(
        min(constraints.max_sector_share, anzahl * constraints.max_position_share)
        for anzahl in je_branche.values()
    )


def _cap_violations(
    weights: dict[str, float], sectors: dict[str, str], constraints: AllocationConstraints
) -> list[str]:
    """Benennt Deckel, die nach der Umverteilung noch verletzt sind."""
    hinweise: list[str] = []
    toleranz = 0.005

    ueber_position = sorted(
        t for t, g in weights.items() if g > constraints.max_position_share + toleranz
    )
    if ueber_position:
        hinweise.append(
            f"Der Positionsdeckel von {constraints.max_position_share * 100:.0f} % liess "
            f"sich fuer {', '.join(ueber_position)} nicht einhalten."
        )

    je_branche: dict[str, float] = {}
    for ticker, gewicht in weights.items():
        branche = sectors.get(ticker, "")
        je_branche[branche] = je_branche.get(branche, 0.0) + gewicht
    ueber_branche = sorted(
        b for b, summe in je_branche.items()
        if summe > constraints.max_sector_share + toleranz
    )
    if ueber_branche:
        hinweise.append(
            f"Der Branchendeckel von {constraints.max_sector_share * 100:.0f} % liess sich "
            f"fuer {', '.join(ueber_branche)} nicht einhalten."
        )
    return hinweise


def allocate(
    candidates: list[tuple],
    amount: float,
    *,
    method: AllocationMethod = AllocationMethod.EQUAL,
    constraints: AllocationConstraints | None = None,
) -> AllocationResult:
    """Verteilt ``amount`` auf die Kandidaten.

    ``candidates`` ist eine Liste aus ``(snapshot, scored)``. Titel ohne Score,
    ohne Kurs oder mit zu duenner Datenlage werden mit Grund ausgeschlossen -
    sie verschwinden nicht stillschweigend.
    """
    rules = constraints or AllocationConstraints()
    result = AllocationResult(amount=max(0.0, amount), method=method, constraints=rules)

    if result.amount <= 0:
        result.warnings.append("Kein Betrag angegeben.")
        return result

    # --- 1. Eignung pruefen --------------------------------------------------
    geeignet: list[AllocationItem] = []
    for snapshot, scored in candidates:
        ticker = snapshot.ticker
        if not scored.is_available:
            result.excluded.append((ticker, "Kein Gesamtscore berechenbar"))
            continue
        abdeckung = scored.categories["fundamental"].weight_coverage * 100.0
        if abdeckung < rules.min_coverage:
            result.excluded.append(
                (ticker, f"Datenabdeckung {abdeckung:.0f} % unter {rules.min_coverage:.0f} %")
            )
            continue
        if rules.min_score is not None and scored.total < rules.min_score:
            result.excluded.append(
                (ticker, f"Score {scored.total:.0f} unter {rules.min_score:.0f}")
            )
            continue
        if snapshot.price is None or snapshot.price <= 0:
            result.excluded.append((ticker, "Kein Kurs verfuegbar - Stueckzahl nicht bestimmbar"))
            continue

        geeignet.append(
            AllocationItem(
                ticker=ticker,
                name=snapshot.profile.name or ticker,
                sector=snapshot.profile.sector or "Ohne Branchenangabe",
                score=scored.total,
                price=snapshot.price,
                currency=snapshot.currency,
            )
        )

    if not geeignet:
        result.warnings.append(
            "Kein Titel erfuellt die Voraussetzungen. Zuerst aktualisieren oder die "
            "Anforderungen an die Datenabdeckung senken."
        )
        return result

    # --- 2. Beste nach Score, begrenzt auf die Hoechstzahl -------------------
    geeignet.sort(key=lambda i: (-i.score, i.ticker))
    for item in geeignet[rules.max_positions :]:
        result.excluded.append(
            (item.ticker, f"Nicht unter den besten {rules.max_positions} nach Score")
        )
    ausgewaehlt = geeignet[: rules.max_positions]

    # --- 3. Rohgewichte ------------------------------------------------------
    if method is AllocationMethod.EQUAL:
        roh = {item.ticker: 1.0 / len(ausgewaehlt) for item in ausgewaehlt}
    else:
        summe = sum(item.score for item in ausgewaehlt)
        roh = (
            {item.ticker: item.score / summe for item in ausgewaehlt}
            if summe > 0
            else {item.ticker: 1.0 / len(ausgewaehlt) for item in ausgewaehlt}
        )

    sectors = {item.ticker: item.sector for item in ausgewaehlt}

    kapazitaet = _capacity(sectors, rules)
    if kapazitaet < 1.0 - EPSILON:
        # Beide Deckel zugleich sind mit dieser Auswahl rechnerisch unmoeglich.
        # Das wird benannt, nicht stillschweigend aufgeloest.
        result.warnings.append(
            f"Positions- und Branchendeckel sind mit diesen {len(ausgewaehlt)} Titeln nicht "
            f"gleichzeitig erfuellbar: unter beiden Grenzen liessen sich nur "
            f"{kapazitaet * 100:.0f} % des Betrags unterbringen. Abhilfe: mehr Titel aus "
            "anderen Branchen aufnehmen, oder eine der beiden Grenzen anheben."
        )

    gewichte = _cap_weights(roh, sectors, rules)

    # --- 4. Mindestgroesse: zu kleine Positionen fliegen raus ----------------
    # Kleine Posten werden von Gebuehren aufgezehrt. Nach jedem Entfernen muss
    # neu verteilt werden, weil die uebrigen dadurch groesser werden.
    for _ in range(len(ausgewaehlt)):
        zu_klein = [
            t for t, g in gewichte.items()
            if g * result.amount < rules.min_position_amount - EPSILON
        ]
        # Es wird einzeln entfernt, nicht alle auf einmal: durch das Entfernen
        # einer Position werden die uebrigen groesser und erreichen die
        # Mindestgroesse womoeglich schon.
        if not zu_klein or len(gewichte) <= 1:
            break
        entfernt = min(zu_klein, key=lambda t: gewichte[t])
        result.excluded.append(
            (
                entfernt,
                f"Anteil ergaebe weniger als {rules.min_position_amount:.0f} je Position",
            )
        )
        del gewichte[entfernt]
        ausgewaehlt = [i for i in ausgewaehlt if i.ticker != entfernt]
        sectors.pop(entfernt, None)
        basis = {t: roh[t] for t in gewichte}
        gewichte = _cap_weights(basis, sectors, rules)

    # --- 5. Betraege und ganze Stueckzahlen ----------------------------------
    for item in ausgewaehlt:
        item.weight = gewichte.get(item.ticker, 0.0)
        item.target_amount = item.weight * result.amount
        item.shares = int(math.floor(item.target_amount / item.price)) if item.price else 0
        item.invested_amount = item.shares * (item.price or 0.0)

    result.items = [i for i in ausgewaehlt if i.shares > 0]
    for item in ausgewaehlt:
        if item.shares == 0:
            result.excluded.append(
                (
                    item.ticker,
                    f"Zielbetrag {item.target_amount:.0f} reicht nicht fuer ein ganzes Stueck "
                    f"(Kurs {item.price:.2f})",
                )
            )

    result.warnings.extend(_cap_violations(gewichte, sectors, rules))
    result.warnings.extend(_build_warnings(result))
    return result


def _build_warnings(result: AllocationResult) -> list[str]:
    hinweise: list[str] = []
    if not result.items:
        return hinweise

    anteile = result.sector_shares
    if len(anteile) == 1:
        hinweise.append(
            f"Alle Positionen liegen in einer einzigen Branche ({next(iter(anteile))}). "
            "Das ist ein Klumpenrisiko, das die Aufteilung nicht aufloesen kann - "
            "dafuer muessten Titel anderer Branchen im Universum sein."
        )
    elif anteile:
        groesste, wert = max(anteile.items(), key=lambda kv: kv[1])
        if wert > result.constraints.max_sector_share * 100.0 + 1.0:
            hinweise.append(
                f"Die Branche '{groesste}' kommt nach Rundung auf {wert:.0f} % - "
                "ganze Stueckzahlen lassen sich nicht exakt deckeln."
            )

    if len(result.items) < 3:
        hinweise.append(
            f"Nur {len(result.items)} Position(en). Eine so kleine Aufteilung streut kaum."
        )

    waehrungen = {i.currency for i in result.items if i.currency}
    if len(waehrungen) > 1:
        hinweise.append(
            "Die Positionen notieren in unterschiedlichen Waehrungen ("
            + ", ".join(sorted(waehrungen))
            + "). Die Betraege sind NICHT umgerechnet - der Vorschlag behandelt sie "
            "wie dieselbe Einheit."
        )

    if result.cash_left > result.amount * 0.05:
        hinweise.append(
            f"{result.cash_left:.0f} bleiben uebrig, weil nur ganze Stuecke gekauft werden "
            f"koennen ({result.cash_left / result.amount * 100:.0f} % des Betrags)."
        )
    return hinweise
