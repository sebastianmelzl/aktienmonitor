# Aktienmonitor

Lokal laufende Web-App zur Analyse von Aktien anhand fundamentaler, technischer
und Analysten-Kennzahlen. Die App bereitet öffentlich verfügbare Daten auf und
macht jede Zahl bis zur Rohquelle nachvollziehbar.

> **Keine Anlageberatung.** Dieses Werkzeug bereitet Daten auf, es berät nicht.
> Es gibt keine Gewähr für Richtigkeit, Vollständigkeit oder Aktualität der
> angezeigten Daten. Alle Kennzahlen stammen aus kostenlosen Datenquellen und
> können fehlerhaft oder veraltet sein.

## Grundprinzip: keine erfundenen Daten

Die zentrale Regel des Projekts ist technisch durchgesetzt, nicht nur
dokumentiert:

- Eine nicht abrufbare Kennzahl erscheint als **n/a** – mit Begründung, warum
  sie fehlt. Es gibt keinen Codepfad, auf dem ein fehlender Wert als Zahl
  dargestellt wird.
- `NaN` und `Inf` werden beim Anlegen einer Kennzahl automatisch zu „fehlend"
  umgewandelt (`models.MetricValue.__post_init__`).
- Aus anderen Werten abgeleitete Kennzahlen sind als **berechnet** markiert und
  führen ihre Eingangsgrößen mit.
- Eine Wachstumsrate aus einem Verlust heraus, eine Division durch null oder ein
  Perzentil ohne Vergleichsgruppe ergeben **kein** Ergebnis statt eines
  plausibel aussehenden.
- `0.0` ist ein gültiger Wert und wird nie als „fehlend" behandelt – deshalb
  nutzt der Code `_pick`/`_first` statt `or` für Quellen-Rückfallebenen.

## Setup

Voraussetzung: Python 3.11 oder neuer.

```bash
# 1. Repository holen
git clone https://github.com/sebastianmelzl/aktienmonitor.git
cd aktienmonitor

# 2. Umgebung anlegen und Abhängigkeiten installieren
#    (mit uv – schnell; alternativ python -m venv .venv && pip install -e ".[dev]")
uv venv --python 3.11 .venv
uv pip install -e ".[dev]"

# 3. Konfiguration anlegen
cp .env.example .env
#    Die .env kann zunächst leer bleiben: ohne API-Schlüssel läuft die App
#    vollständig über yfinance.

# 4. Starten
.venv/bin/streamlit run app.py
```

Die App ist danach unter <http://localhost:8501> erreichbar. Beim ersten Start
legt sie `data/aktienmonitor.db` an; Logs landen unter `logs/`. Beide
Verzeichnisse sind von Git ausgeschlossen.

### API-Schlüssel (beide optional)

| Dienst | Wofür | Kostenlos erhältlich unter |
|---|---|---|
| **Finnhub** | Ergänzende Kennzahlen und Schlagzeilen für US-Titel | <https://finnhub.io/register> |
| **Anthropic** | Sentiment-Einordnung der Schlagzeilen (ab Phase 4) | <https://console.anthropic.com/settings/keys> |

Beide Schlüssel werden ausschließlich aus der `.env` gelesen. Diese Datei steht
in `.gitignore` und darf nie committet werden. Ohne Anthropic-Schlüssel bleibt
der Sentiment-Score `n/a` – es wird kein Ersatzwert erzeugt.

**Prüfen, was der eigene Schlüssel wirklich kann:** Die Seite **Datenquellen**
ruft jeden Endpunkt genau einmal auf und protokolliert das Ergebnis
(verfügbar / gesperrt / Fehler). Die Free-Tier-Grenzen der Anbieter ändern sich
regelmäßig, deshalb wird hier gemessen statt behauptet.

## Tests

```bash
.venv/bin/python -m pytest        # 204 Tests, alle ohne Netzwerkzugriff
.venv/bin/ruff check .            # Linting
```

Die Kennzahlen- und Scoring-Logik ist vollständig ohne Oberfläche und ohne
Datenquelle testbar. Jeder Test arbeitet mit fixen, im Code stehenden Werten und
prüft gegen handgerechnete Ergebnisse; die Herleitung steht jeweils als
Kommentar am Test.

## Aufbau

```
app.py                      Einstiegspunkt und Navigation
views/                      Seiten der Oberfläche (kein Rechenkram)
src/aktienmonitor/
  config.py                 Konfiguration aus .env
  models.py                 MetricValue & Co. – erzwingt "keine erfundenen Daten"
  providers/                Datenabruf
    base.py                 Cache + Rate-Limit + Retry + Protokoll je Abruf
    throttle.py             Token-Bucket, Wiederholversuche mit Backoff
    yfinance_source.py      Hauptquelle
    finnhub_source.py       Ergänzende Quelle
    capabilities.py         Datenquellen-Check
    fetcher.py              Zusammenführung zum Titel-Snapshot
  metrics/                  Kennzahlenberechnung (ohne Netz, ohne UI)
    statements.py           Lesen der Jahresabschlüsse
    fundamental.py          Fundamentale Kennzahlen
    technical.py            Technische Indikatoren
    analyst.py              Analysten-Kennzahlen
  scoring/                  Scoring (Phase 2)
  storage/                  SQLite: Schema, Cache, Watchlist, Einstellungen
  ui/                       Formatierung, Charts, gemeinsame Bausteine
tests/                      Unit-Tests mit fixen Testdaten
```

Die Schichten sind strikt getrennt: `metrics/` und `scoring/` importieren weder
aus `providers/` noch aus `ui/`. Sie nehmen einfache Datenstrukturen entgegen
und geben `MetricValue`-Objekte zurück.

## Umgang mit Rate-Limits

Rate-Limits sind die zentrale technische Herausforderung. Vier Mechanismen
greifen ineinander:

1. **Cache in SQLite mit datentyp-abhängiger Lebensdauer.** Kursdaten sind kurz
   gültig, Fundamentaldaten lange – ein Jahresabschluss ändert sich nicht
   stündlich. Die Vorgaben stehen in der `.env` und sind im UI änderbar:

   | Datenart | Vorgabe | Begründung |
   |---|---|---|
   | Realtime-Kurs | 5 Minuten | ändert sich laufend |
   | Kurshistorie | 6 Stunden | Tageskerzen ändern sich einmal täglich |
   | Bilanz / GuV / Cashflow | 7 Tage | ändert sich quartalsweise |
   | Stammdaten, Sektor | 30 Tage | ändert sich praktisch nie |
   | Analystendaten | 1 Tag | ändert sich unregelmäßig |
   | Schlagzeilen | 1 Stunde | |

2. **Token-Bucket je Quelle.** Begrenzt die Aufrufe pro Minute
   (`RATE_LIMIT_*_PER_MIN`). Ist das Kontingent erschöpft, wartet der Abruf,
   statt in einen Fehler zu laufen.

3. **Wiederholversuche mit exponentiellem Backoff.** Bei HTTP 429, Zeitüber-
   schreitungen und Verbindungsfehlern wird bis zu viermal erneut versucht
   (1 s, 2 s, 4 s … plus Zufallsaufschlag). Ein **gesperrter** Endpunkt
   (HTTP 403) wird bewusst *nicht* wiederholt – Warten macht ihn nicht frei.

4. **Veraltete Daten als Rückfallebene.** Schlägt ein Live-Abruf fehl, greift
   die App auf den abgelaufenen Cache-Eintrag zurück und weist ihn in der
   Oberfläche mit seinem Alter aus, statt die Kennzahl zu verlieren.

Jeder Zugriff wird protokolliert (Quelle, Endpunkt, Cache-Treffer, Dauer) – im
Log und in der Tabelle `api_call_log`. Die Seite **Datenquellen** zeigt
Trefferquote und Fehlerzahl der letzten 24 Stunden.

## Kennzahlen

Die Spalte **Herkunft** unterscheidet: *übernommen* = die Datenquelle liefert
den Wert fertig; *berechnet* = aus anderen Größen abgeleitet und in der
Oberfläche entsprechend markiert.

### Fundamental

| Kennzahl | Bedeutung | Herkunft |
|---|---|---|
| **KGV (aktuell)** | Kurs / Gewinn je Aktie der letzten 12 Monate. Niedrig = günstiger bewertet, aber stark sektorabhängig. | übernommen |
| **KGV (forward)** | Kurs / erwarteter Gewinn je Aktie. Beruht auf Schätzungen. | übernommen |
| **KUV** | Kurs / Umsatz je Aktie. Nützlich bei Firmen ohne Gewinn. | übernommen |
| **KBV** | Kurs / Buchwert je Aktie. Bei Banken aussagekräftiger als bei Software. | übernommen |
| **PEG** | KGV geteilt durch das Gewinnwachstum in Prozent. Setzt Bewertung ins Verhältnis zum Wachstum. Bei negativem Wachstum nicht definiert. | übernommen oder berechnet |
| **EV/EBITDA** | Unternehmenswert (inkl. Schulden) / operatives Ergebnis vor Abschreibungen. Kapitalstruktur-neutral. | übernommen oder berechnet |
| **ROE** | Nettogewinn / Eigenkapital. Hohe Verschuldung hebt den ROE künstlich. | übernommen |
| **ROIC** | Kapitalrendite: EBIT nach Steuern / investiertes Kapital. Aussagekräftiger als ROE, weil verschuldungsunabhängig. | berechnet |
| **Bruttomarge** | Bruttoergebnis / Umsatz. Zeigt die Preissetzungsmacht. | übernommen oder berechnet |
| **Operative Marge** | Betriebsergebnis / Umsatz. | übernommen oder berechnet |
| **Nettomarge** | Nettoergebnis / Umsatz. | übernommen oder berechnet |
| **Umsatzwachstum 1/3/5 J.** | Jährliche Wachstumsrate (CAGR) über den Zeitraum. | berechnet |
| **Gewinnwachstum 1/3/5 J.** | Wie oben für das Nettoergebnis. Aus einem Verlust heraus nicht definiert. | berechnet |
| **Free Cashflow** | Operativer Cashflow abzüglich Investitionen. Das, was tatsächlich frei verfügbar bleibt. | berechnet |
| **FCF-Marge** | Free Cashflow / Umsatz. | berechnet |
| **Netto-Verschuldung / EBITDA** | (Schulden − liquide Mittel) / EBITDA. Wie viele Jahresergebnisse nötig wären, um die Schulden zu tilgen. | berechnet |
| **Eigenkapitalquote** | Eigenkapital / Bilanzsumme. | berechnet |
| **Current Ratio** | Umlaufvermögen / kurzfristige Verbindlichkeiten. Unter 1 bedeutet Anspannung. | übernommen oder berechnet |
| **Dividendenrendite** | Dividende je Aktie / Kurs. | übernommen |
| **Ausschüttungsquote** | Dividende / Gewinn. Über 100 % bedeutet: aus der Substanz gezahlt. | übernommen |
| **Jahre mit Dividendenzahlung** | Anzahl Jahre mit Ausschüttung in der verfügbaren Historie. | berechnet |
| **Jahre in Folge steigende Dividende** | Laufende Serie. Das unvollständige laufende Jahr zählt nicht mit. | berechnet |
| **Marktkapitalisierung** | Kurs × Anzahl Aktien. | übernommen |
| **Anzahl Aktien** | Ausstehende Aktien. | übernommen |
| **Veränderung Aktienzahl (1 J.)** | Negativ = Rückkäufe, positiv = Verwässerung. | berechnet |

### Technisch

Alle technischen Kennzahlen werden lokal aus der Kurshistorie berechnet und sind
durchgängig als *berechnet* markiert. Reicht die Historie für ein Fenster nicht
aus, ist das Ergebnis **n/a** – es wird kein verkürztes Fenster eingesetzt, denn
ein RSI über 5 statt 14 Tage wäre eine andere Kennzahl.

| Kennzahl | Bedeutung |
|---|---|
| **SMA 50 / SMA 200** | Gleitende Durchschnitte über 50 bzw. 200 Handelstage. |
| **Abstand zur SMA 50 / 200** | Wie weit der Kurs vom jeweiligen Durchschnitt entfernt ist, in Prozent. |
| **SMA-50/200-Signal** | *Golden Cross* = SMA 50 kreuzt SMA 200 von unten nach oben (in den letzten 30 Tagen), *Death Cross* umgekehrt. Ohne Kreuzung wird die aktuelle Lage der Linien zueinander genannt. |
| **RSI (14)** | Relative Strength Index nach Wilder, Skala 0–100. Über 70 gilt als überkauft, unter 30 als überverkauft. Berechnet mit Wilder-Saat (einfacher Mittelwert der ersten 14 Werte, danach rekursive Glättung) – so rechnen die gängigen Chartprogramme. |
| **MACD, Signallinie, Histogramm** | Differenz aus 12- und 26-Tage-EMA, deren 9-Tage-EMA als Signallinie, und die Differenz beider. |
| **Bollinger-Bänder, %B** | 20-Tage-Durchschnitt ± 2 Standardabweichungen (Populationsgröße, wie in Chartprogrammen üblich). %B gibt die Lage des Kurses im Band an (0 = unteres, 1 = oberes Band). |
| **ATR (14)** | Average True Range nach Wilder – die durchschnittliche Tagesschwankung in Kurseinheiten. |
| **ATR in % des Kurses** | Dieselbe Größe relativ zum Kurs, dadurch über Titel hinweg vergleichbar. |
| **Volatilität (annualisiert)** | Standardabweichung der logarithmierten Tagesrenditen, hochgerechnet auf ein Jahr (252 Handelstage). |
| **Momentum 1/3/6/12 Monate** | Kursveränderung über 21 / 63 / 126 / 252 Handelstage. |
| **Abstand zum 52-Wochen-Hoch / -Tief** | Relative Abweichung des aktuellen Kurses vom Extremwert des Jahres. |
| **Volumentrend** | Durchschnittsvolumen der letzten 20 Tage gegenüber den letzten 60 Tagen, in Prozent. |

### Analysten

| Kennzahl | Bedeutung |
|---|---|
| **Konsens-Einordnung** | Aus den Analystenzählungen abgeleitete Einordnung: *sehr positiv* bis *sehr negativ*. Bewusst neutral formuliert – die App vergibt keine Kauf- oder Verkaufslabels. |
| **Konsens-Note** | Mittelwert auf der Skala 1 (sehr positiv) bis 5 (sehr negativ). |
| **Anzahl Analysten** | Wie viele Einschätzungen der Note zugrunde liegen. Bei zwei Analysten ist ein Konsens wenig aussagekräftig. |
| **Durchschnittliches Kursziel** | Mittelwert der Kursziele. |
| **Abstand zum Kursziel** | Differenz zwischen Kursziel und aktuellem Kurs, in Prozent. |
| **Auf-/Abwärtsrevisionen (30 Tage)** | Anzahl der nach oben bzw. unten korrigierten Gewinnschätzungen für das laufende Geschäftsjahr. |
| **Revisionssaldo (30 Tage)** | −100 = ausschließlich Abwärts-, +100 = ausschließlich Aufwärtsrevisionen. Bei null Revisionen **n/a**, nicht 0. |
| **Letzte Earnings-Überraschung** | Abweichung des gemeldeten vom erwarteten Gewinn je Aktie, in Prozent. |
| **Earnings-Überraschung (Schnitt 4 Quartale)** | Mittelwert der letzten vier veröffentlichten Quartale. Künftige Termine ohne Ergebnis zählen nicht mit. |
| **Nächster Termin Zahlen** | Datum der nächsten Veröffentlichung. |

## Scoring

Noch nicht umgesetzt – folgt in Phase 2. Geplant sind vier Teilscores
(Fundamental, Technik, Analysten, Sentiment) von jeweils 0–100 und ein
gewichteter Gesamtscore mit im UI verstellbaren Gewichten. Kennzahlen wie das
KGV werden dabei nicht absolut bewertet, sondern als Perzentil gegenüber dem
Sektor-Median – sonst gewinnen strukturell immer die niedrig bewerteten
Branchen. Fehlende Kennzahlen normieren den Teilscore auf die verbleibenden und
die Datenabdeckung wird in Prozent ausgewiesen.

## Bekannte Grenzen der Datenquellen

Diese Einschränkungen sind Eigenschaften der kostenlosen Datenquellen, keine
Fehler der App. Sie führen zu ausgewiesenen **n/a**-Werten.

### yfinance (Hauptquelle)

- **Inoffizielle Schnittstelle.** yfinance greift auf Endpunkte von Yahoo
  Finance zu, für die es keine Zusage zu Verfügbarkeit oder Richtigkeit gibt.
  Yahoo ändert sie gelegentlich ohne Ankündigung; dann fehlen Kennzahlen, bis
  eine neue yfinance-Version erscheint.
- **Nur etwa vier Geschäftsjahre Historie.** Deshalb ist das **5-Jahres-Wachstum
  häufig n/a** – ein Vergleichsjahr, das nicht existiert, wird nicht ersetzt.
- **Datenqualität schwankt je Markt.** Für US-Standardwerte ist die Abdeckung
  gut, für kleinere europäische oder asiatische Titel deutlich lückenhafter.
- **Kein offizielles Rate-Limit**, aber Yahoo drosselt bei zu vielen Abrufen.
  Die App bleibt deshalb auch hier innerhalb eines Token-Buckets.

### Finnhub (ergänzend)

- **Free-Tier ist im Kern ein US-Tier.** 60 Aufrufe pro Minute, für nicht-US-
  Titel kaum Fundamentaldaten.
- **Historische Kurse (`/stock/candle`) sind Premium** und antworten auf Free-
  Schlüssel mit HTTP 403. Die gesamte Technik-Analyse läuft deshalb über
  yfinance.
- **Analystendaten und News-Sentiment sind ebenfalls Premium** geworden.
- Die genaue Grenze verschiebt sich und hängt am Schlüssel – deshalb der
  Datenquellen-Check in der App statt einer Behauptung an dieser Stelle.

### Titelabhängige Grenzen

- **ETFs und Fonds** haben keine Unternehmenskennzahlen. ROE, Margen, ROIC oder
  Free Cashflow existieren dort begrifflich nicht und werden als *nicht
  anwendbar* geführt – nicht als Datenlücke.
- **Banken und Versicherer**: ROIC, Netto-Verschuldung/EBITDA und Current Ratio
  sind für Finanzunternehmen inhaltlich wenig aussagekräftig, weil deren
  Bilanzstruktur eine andere ist.
- **Schätzungsrevisionen** sind die dünnste Kennzahl. Kostenlos gibt es dafür
  kaum eine belastbare Zeitreihe.
- **Währungen**: Kennzahlen werden in der Berichtswährung des Titels angezeigt.
  Es findet keine Umrechnung statt.

## Nicht enthalten

Bewusst nicht gebaut: keine Orderausführung, keine Broker-Anbindung, keine
automatischen Handelsentscheidungen und kein Backtest der Score-Logik.

## Lizenz

Privates Projekt zur eigenen Verwendung.
