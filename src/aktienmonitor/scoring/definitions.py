"""Das Bewertungsregelwerk.

Hier steht, welche Kennzahl mit welchem Gewicht in welchen Teilscore eingeht und
wie ihr Wert in Punkte uebersetzt wird. Die Stuetzstellen sind bewusst
konservativ und branchenneutral gewaehlt; jede Regel traegt ihre Begruendung
mit, die in der Oberflaeche aufklappbar ist.

Wichtig zur Einordnung: Diese Schwellen sind eine Konvention, keine Wahrheit.
Sie machen Titel untereinander vergleichbar - sie sagen nicht, ob ein Titel
"gut" ist. Bewertungskennzahlen (KGV, KUV, KBV, EV/EBITDA) und Margen werden
grundsaetzlich im Branchenvergleich bewertet, nicht absolut.
"""

from __future__ import annotations

from .rules import ScoreMode, ScoreRule

# --- Teilscore-Bezeichner ----------------------------------------------------

CATEGORY_FUNDAMENTAL = "fundamental"
CATEGORY_TECHNICAL = "technical"
CATEGORY_ANALYST = "analyst"
CATEGORY_SENTIMENT = "sentiment"

CATEGORY_LABELS = {
    CATEGORY_FUNDAMENTAL: "Fundamental",
    CATEGORY_TECHNICAL: "Technik",
    CATEGORY_ANALYST: "Analysten",
    CATEGORY_SENTIMENT: "Sentiment",
}

# Voreingestellte Gewichtung des Gesamtscores. Im UI per Schieberegler aenderbar.
DEFAULT_WEIGHTS: dict[str, float] = {
    CATEGORY_FUNDAMENTAL: 0.40,
    CATEGORY_TECHNICAL: 0.25,
    CATEGORY_ANALYST: 0.25,
    CATEGORY_SENTIMENT: 0.10,
}

_REL = ScoreMode.SECTOR_RELATIVE
_ABS = ScoreMode.ABSOLUTE
_CAT = ScoreMode.CATEGORICAL


FUNDAMENTAL_RULES: tuple[ScoreRule, ...] = (
    # --- Bewertung: ausschliesslich im Branchenvergleich --------------------
    ScoreRule(
        "pe_trailing", 1.0, _REL, higher_is_better=False,
        rationale="Guenstigeres KGV als die Branche gibt mehr Punkte. Absolut waeren "
                  "Banken strukturell im Vorteil, deshalb der Branchenvergleich.",
    ),
    ScoreRule(
        "pe_forward", 0.8, _REL, higher_is_better=False,
        rationale="Wie das KGV, aber auf Basis der Gewinnschaetzung - beruht auf Prognosen.",
    ),
    ScoreRule(
        "ps", 0.6, _REL, higher_is_better=False,
        rationale="Kurs-Umsatz-Verhaeltnis im Branchenvergleich. Zwischen Branchen "
                  "besonders unterschiedlich, daher geringeres Gewicht.",
    ),
    ScoreRule(
        "pb", 0.6, _REL, higher_is_better=False,
        rationale="Kurs-Buchwert-Verhaeltnis im Branchenvergleich. Bei Banken "
                  "aussagekraeftig, bei Software kaum.",
    ),
    ScoreRule(
        "ev_ebitda", 1.0, _REL, higher_is_better=False,
        rationale="Unternehmenswert je EBITDA - kapitalstrukturneutral und damit die "
                  "robusteste Bewertungskennzahl.",
    ),
    ScoreRule(
        "peg", 0.8, _ABS,
        breakpoints=((0.5, 100.0), (1.0, 80.0), (1.5, 60.0), (2.0, 40.0), (3.0, 15.0), (5.0, 0.0)),
        rationale="PEG unter 1 gilt traditionell als guenstig bewertetes Wachstum. "
                  "Absolut bewertbar, weil die Kennzahl das Wachstum bereits einrechnet.",
    ),

    # --- Rentabilitaet ------------------------------------------------------
    ScoreRule(
        "roe", 0.9, _REL, higher_is_better=True,
        rationale="Eigenkapitalrendite im Branchenvergleich. Absolut irrefuehrend, "
                  "weil hohe Verschuldung den ROE rechnerisch hebt.",
    ),
    ScoreRule(
        "roic", 1.0, _ABS,
        breakpoints=((0.0, 0.0), (5.0, 25.0), (10.0, 55.0), (15.0, 75.0), (20.0, 90.0), (30.0, 100.0)),
        rationale="Kapitalrendite absolut bewertet: rund 8-10 % entsprechen ueblichen "
                  "Kapitalkosten, darunter wird kein Wert geschaffen.",
    ),
    ScoreRule(
        "gross_margin", 0.5, _REL, higher_is_better=True,
        rationale="Bruttomarge im Branchenvergleich - zwischen Handel und Software "
                  "liegen Groessenordnungen.",
    ),
    ScoreRule(
        "operating_margin", 0.8, _REL, higher_is_better=True,
        rationale="Operative Marge im Branchenvergleich.",
    ),
    ScoreRule(
        "net_margin", 0.7, _REL, higher_is_better=True,
        rationale="Nettomarge im Branchenvergleich.",
    ),

    # --- Wachstum -----------------------------------------------------------
    ScoreRule(
        "revenue_growth_3y", 0.9, _ABS,
        breakpoints=((-10.0, 0.0), (0.0, 25.0), (5.0, 50.0), (10.0, 70.0), (20.0, 90.0), (30.0, 100.0)),
        rationale="Umsatzwachstum ueber drei Jahre. Drei Jahre glaetten Einmaleffekte "
                  "besser als ein Jahr und sind haeufiger verfuegbar als fuenf.",
    ),
    ScoreRule(
        "earnings_growth_3y", 0.9, _ABS,
        breakpoints=((-10.0, 0.0), (0.0, 25.0), (5.0, 50.0), (10.0, 70.0), (20.0, 90.0), (30.0, 100.0)),
        rationale="Gewinnwachstum ueber drei Jahre. Aus einem Verlustjahr heraus nicht "
                  "berechenbar und dann n/a.",
    ),

    # --- Cashflow -----------------------------------------------------------
    ScoreRule(
        "fcf_margin", 0.9, _ABS,
        breakpoints=((-5.0, 0.0), (0.0, 20.0), (5.0, 45.0), (10.0, 70.0), (15.0, 85.0), (25.0, 100.0)),
        rationale="Free-Cashflow-Marge absolut bewertet - anders als der Gewinn ist der "
                  "freie Cashflow bilanzpolitisch schwer zu gestalten.",
    ),

    # --- Bilanzqualitaet ----------------------------------------------------
    ScoreRule(
        "net_debt_ebitda", 0.8, _ABS,
        breakpoints=((-1.0, 100.0), (0.0, 95.0), (1.0, 80.0), (2.0, 60.0), (3.0, 40.0),
                     (4.0, 20.0), (6.0, 0.0)),
        rationale="Verschuldung in Jahren EBITDA. Negativ bedeutet Nettoliquiditaet. "
                  "Ab etwa dem Dreifachen gilt die Bilanz als angespannt.",
    ),
    ScoreRule(
        "equity_ratio", 0.6, _ABS,
        breakpoints=((10.0, 0.0), (20.0, 30.0), (30.0, 55.0), (40.0, 75.0), (50.0, 90.0), (60.0, 100.0)),
        rationale="Eigenkapitalquote. Fuer Banken und Versicherer wenig aussagekraeftig, "
                  "da deren Bilanzstruktur eine andere ist.",
    ),
    ScoreRule(
        "current_ratio", 0.5, _ABS,
        breakpoints=((0.5, 0.0), (1.0, 45.0), (1.5, 75.0), (2.0, 95.0), (2.5, 100.0)),
        rationale="Kurzfristige Zahlungsfaehigkeit. Unter 1 bedeutet Anspannung; "
                  "deutlich ueber 2 bringt keine zusaetzlichen Punkte mehr.",
    ),

    # --- Dividende und Aktienzahl -------------------------------------------
    ScoreRule(
        "dividend_yield", 0.5, _ABS,
        breakpoints=((0.0, 0.0), (1.0, 30.0), (2.0, 55.0), (3.0, 75.0), (4.0, 90.0), (6.0, 100.0)),
        rationale="Dividendenrendite. Achtung: eine sehr hohe Rendite entsteht oft durch "
                  "einen gefallenen Kurs - der Score bestraft das nicht.",
    ),
    ScoreRule(
        "payout_ratio", 0.4, _ABS,
        breakpoints=((0.0, 40.0), (30.0, 85.0), (50.0, 100.0), (70.0, 80.0), (90.0, 45.0),
                     (110.0, 10.0), (150.0, 0.0)),
        rationale="Ausschuettungsquote mit guenstigem Mittelbereich: zu wenig laesst "
                  "Spielraum ungenutzt, ueber 100 % wird aus der Substanz gezahlt.",
    ),
    ScoreRule(
        "share_count_change_1y", 0.5, _ABS,
        breakpoints=((-5.0, 100.0), (-2.0, 85.0), (0.0, 60.0), (2.0, 30.0), (5.0, 10.0), (10.0, 0.0)),
        rationale="Sinkende Aktienzahl bedeutet Rueckkaeufe, steigende Verwaesserung.",
    ),
)


TECHNICAL_RULES: tuple[ScoreRule, ...] = (
    ScoreRule(
        "price_vs_sma_200", 1.0, _ABS,
        breakpoints=((-30.0, 0.0), (-10.0, 30.0), (0.0, 55.0), (10.0, 80.0), (25.0, 95.0), (40.0, 100.0)),
        rationale="Lage zum langfristigen Durchschnitt - das gebraeuchlichste Mass fuer "
                  "einen intakten Aufwaertstrend.",
    ),
    ScoreRule(
        "price_vs_sma_50", 0.7, _ABS,
        breakpoints=((-20.0, 0.0), (-7.0, 30.0), (0.0, 55.0), (7.0, 80.0), (15.0, 95.0), (25.0, 100.0)),
        rationale="Lage zum mittelfristigen Durchschnitt.",
    ),
    ScoreRule(
        "ma_cross", 0.8, _CAT,
        categories=(
            ("Golden Cross", 100.0),
            ("SMA50 ueber SMA200", 75.0),
            ("SMA50 unter SMA200", 30.0),
            ("Death Cross", 0.0),
        ),
        rationale="Kreuzung der Durchschnitte. Ein frisches Golden Cross wiegt schwerer "
                  "als eine laenger bestehende Lage.",
    ),
    ScoreRule(
        "rsi_14", 0.8, _ABS,
        breakpoints=((0.0, 35.0), (20.0, 65.0), (30.0, 85.0), (45.0, 100.0), (55.0, 100.0),
                     (70.0, 60.0), (80.0, 30.0), (100.0, 0.0)),
        rationale="RSI mit guenstigem Mittelbereich: Extremwerte in beide Richtungen "
                  "gelten als Uebertreibung und geben weniger Punkte.",
    ),
    ScoreRule(
        "macd_histogram_pct", 0.6, _ABS,
        breakpoints=((-2.0, 0.0), (-0.5, 30.0), (0.0, 50.0), (0.5, 70.0), (2.0, 100.0)),
        rationale="MACD-Histogramm, auf den Kurs normiert und damit zwischen Titeln "
                  "vergleichbar. Positiv bedeutet zunehmende Aufwaertsdynamik.",
    ),
    ScoreRule(
        "momentum_3m", 0.8, _ABS,
        breakpoints=((-30.0, 0.0), (-10.0, 25.0), (0.0, 50.0), (10.0, 72.0), (25.0, 90.0), (50.0, 100.0)),
        rationale="Kursentwicklung ueber drei Monate.",
    ),
    ScoreRule(
        "momentum_6m", 0.8, _ABS,
        breakpoints=((-40.0, 0.0), (-15.0, 25.0), (0.0, 50.0), (15.0, 72.0), (35.0, 90.0), (70.0, 100.0)),
        rationale="Kursentwicklung ueber sechs Monate.",
    ),
    ScoreRule(
        "momentum_12m", 0.7, _ABS,
        breakpoints=((-50.0, 0.0), (-20.0, 25.0), (0.0, 50.0), (20.0, 72.0), (50.0, 90.0), (100.0, 100.0)),
        rationale="Kursentwicklung ueber zwoelf Monate.",
    ),
    ScoreRule(
        "momentum_1m", 0.4, _ABS,
        breakpoints=((-15.0, 0.0), (-5.0, 25.0), (0.0, 50.0), (5.0, 72.0), (12.0, 90.0), (25.0, 100.0)),
        rationale="Kurzfristige Entwicklung - stark schwankend, daher geringes Gewicht.",
    ),
    ScoreRule(
        "distance_52w_high", 0.7, _ABS,
        breakpoints=((-60.0, 0.0), (-30.0, 30.0), (-15.0, 55.0), (-5.0, 80.0), (0.0, 100.0)),
        rationale="Naehe zum Jahreshoch als Mass relativer Staerke.",
    ),
    ScoreRule(
        "volatility_1y", 0.5, _ABS,
        breakpoints=((10.0, 100.0), (20.0, 80.0), (30.0, 60.0), (45.0, 35.0), (60.0, 15.0), (100.0, 0.0)),
        rationale="Annualisierte Schwankungsbreite - niedrigere Werte geben mehr Punkte.",
    ),
    ScoreRule(
        "atr_percent", 0.4, _ABS,
        breakpoints=((1.0, 100.0), (2.0, 80.0), (3.0, 60.0), (5.0, 30.0), (8.0, 0.0)),
        rationale="Durchschnittliche Tagesschwankung in Prozent des Kurses.",
    ),
)


ANALYST_RULES: tuple[ScoreRule, ...] = (
    ScoreRule(
        "consensus_score", 1.0, _ABS,
        breakpoints=((1.0, 100.0), (2.0, 80.0), (3.0, 50.0), (4.0, 20.0), (5.0, 0.0)),
        rationale="Konsens-Note auf der Skala 1 (sehr positiv) bis 5 (sehr negativ).",
    ),
    ScoreRule(
        "target_upside", 1.0, _ABS,
        breakpoints=((-20.0, 0.0), (0.0, 35.0), (10.0, 60.0), (20.0, 80.0), (40.0, 95.0), (60.0, 100.0)),
        rationale="Abstand zum durchschnittlichen Kursziel. Kursziele sind Schaetzungen "
                  "und werden erfahrungsgemaess dem Kurs nachgezogen.",
    ),
    ScoreRule(
        "revision_balance", 0.8, _ABS,
        breakpoints=((-100.0, 0.0), (-50.0, 20.0), (0.0, 50.0), (50.0, 80.0), (100.0, 100.0)),
        rationale="Saldo der Schaetzungsrevisionen der letzten 30 Tage. Die Richtung der "
                  "Revisionen gilt als aussagekraeftiger als ihr Niveau.",
    ),
    ScoreRule(
        "earnings_surprise_avg_4q", 0.6, _ABS,
        breakpoints=((-10.0, 0.0), (-2.0, 30.0), (0.0, 50.0), (2.0, 70.0), (5.0, 85.0), (10.0, 100.0)),
        rationale="Durchschnittliche Abweichung vom erwarteten Gewinn der letzten vier "
                  "veroeffentlichten Quartale.",
    ),
)


# Der Sentiment-Teilscore folgt in Phase 4. Bis dahin ist die Regelmenge leer -
# der Teilscore ist damit nicht berechenbar und sein Gewicht wird auf die
# uebrigen umverteilt, statt einen Ersatzwert einzusetzen.
SENTIMENT_RULES: tuple[ScoreRule, ...] = ()


RULES_BY_CATEGORY: dict[str, tuple[ScoreRule, ...]] = {
    CATEGORY_FUNDAMENTAL: FUNDAMENTAL_RULES,
    CATEGORY_TECHNICAL: TECHNICAL_RULES,
    CATEGORY_ANALYST: ANALYST_RULES,
    CATEGORY_SENTIMENT: SENTIMENT_RULES,
}
