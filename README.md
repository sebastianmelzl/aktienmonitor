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
| **Anthropic** | Sentiment-Einordnung der Schlagzeilen | <https://console.anthropic.com/settings/keys> |

Beide Schlüssel werden ausschließlich aus der `.env` gelesen. Diese Datei steht
in `.gitignore` und darf nie committet werden. Ohne Anthropic-Schlüssel bleibt
der Sentiment-Score `n/a` – es wird kein Ersatzwert erzeugt.

**Prüfen, was der eigene Schlüssel wirklich kann:** Die Seite **Datenquellen**
ruft jeden Endpunkt genau einmal auf und protokolliert das Ergebnis
(verfügbar / gesperrt / Fehler). Die Free-Tier-Grenzen der Anbieter ändern sich
regelmäßig, deshalb wird hier gemessen statt behauptet.

## Tests

```bash
.venv/bin/python -m pytest        # 335 Tests, alle ohne Netzwerkzugriff
.venv/bin/ruff check .            # Linting
```

Die Kennzahlen- und Scoring-Logik ist vollständig ohne Oberfläche und ohne
Datenquelle testbar. Jeder Test arbeitet mit fixen, im Code stehenden Werten und
prüft gegen handgerechnete Ergebnisse; die Herleitung steht jeweils als
Kommentar am Test.

`tests/test_pages.py` führt zusätzlich jede Seite mit Streamlits eigenem
Testläufer gegen eine temporäre Datenbank mit synthetischen Titeln aus. Das
fängt Fehler, die Unit-Tests nicht sehen – eine umbenannte Funktion oder eine
fehlerhafte Spaltenkonfiguration fällt sonst erst im Browser auf.

## Aufbau

```
app.py                      Einstiegspunkt und Navigation
views/                      Seiten der Oberfläche (kein Rechenkram)
  uebersicht.py             Der "Knopfdruck": Tabelle, Filter, CSV-Export
  watchlist.py              Universum verwalten, CSV-Import, Listen
  detail.py                 Chart, Kennzahlen, Score-Aufschlüsselung
  vergleich.py              2-5 Titel nebeneinander
  datenquellen.py           Verfügbarkeitsprüfung, Zugriffsprotokoll
  einstellungen.py          Gewichtung, Sektorvergleich, Cache
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
  sentiment/                Schlagzeilen-Einordnung
    classifier.py           Anthropic-API, Caching je Schlagzeile
    metrics.py              Stimmungssaldo und Anteile
  scoring/                  Scoring - ohne Netz und ohne UI testbar
    rules.py                Stuetzstellen-Interpolation, Regeltypen
    definitions.py          Das Regelwerk: Kennzahl, Gewicht, Bewertungsart
    sector.py               Perzentilrang innerhalb der Branche
    engine.py               Teilscores, Gesamtscore, Beitrags-Aufschluesselung
  storage/                  SQLite: Schema, Cache, Watchlist, Einstellungen
  ui/                       Formatierung, Charts, Tabellenlogik, Score-Anzeige, Zugang
tests/                      Unit-Tests mit fixen Testdaten
Dockerfile                  Container-Abbild für den gehosteten Betrieb
railway.toml                Railway-Konfiguration (Build, Healthcheck, Replikate)
.streamlit/config.toml      Serverkonfiguration
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

### News und Sentiment

| Kennzahl | Bedeutung |
|---|---|
| **Gefundene Meldungen** | Anzahl der Schlagzeilen zum Titel. |
| **Davon eingeordnet** | Wie viele davon eine Sentiment-Einordnung erhalten haben. Ohne Anthropic-Schlüssel ist das null. |
| **Stimmungssaldo** | (positive − negative) / eingeordnete × 100. −100 heißt ausschließlich negativ, +100 ausschließlich positiv. Neutrale Meldungen zählen in den Nenner, drücken den Saldo also Richtung null. |
| **Stimmungssaldo (7 Tage)** | Derselbe Saldo, beschränkt auf die letzten sieben Tage. |
| **Anteil positiver Meldungen** | Ergänzt den Saldo: viele neutrale Meldungen erzeugen einen Saldo nahe null, ohne dass Negatives vorliegt. |

Die Einordnung stammt von einem Sprachmodell (Anthropic API) und ist eine
**Einschätzung, keine Messung**. Zu jeder Meldung wird eine kurze Begründung
mitgeführt, und die Originalquelle bleibt immer verlinkt – die Einordnung lässt
sich am Original nachlesen.

Zwei Vorsichtsmaßnahmen: Bei weniger als drei eingeordneten Meldungen wird kein
Saldo gebildet – aus zwei Schlagzeilen entsteht Rauschen, kein Signal. Und wenn
das Modell zu einer Meldung kein Urteil liefert, bleibt sie **unbewertet**
statt stillschweigend auf „neutral" gesetzt zu werden.

**Kosten:** Eine Schlagzeile kostet rund 40 Token. Ein voller Lauf über 50 Titel
mit je 10 Meldungen liegt bei etwa 20.000 Token – rund 10 Cent. Jede Schlagzeile
wird nach der ersten Einordnung dauerhaft zwischengespeichert, Folgeläufe kosten
praktisch nichts. Das Modell ist über `ANTHROPIC_MODEL` in der `.env` wählbar.

## Scoring

Vier Teilscores von jeweils 0–100 ergeben einen gewichteten Gesamtscore. Der
Score ist eine **Aufbereitung, keine Einschätzung** – die Schwellen des
Regelwerks sind eine Konvention, keine Wahrheit. Deshalb spricht die Oberfläche
durchgehend von *Score*, *Signal* und *Kandidat*, nie von Kaufen oder Verkaufen.

### Formel

Jede Kennzahl wird über eine Regel in Punkte von 0 bis 100 übersetzt und geht
mit ihrem Gewicht in den Teilscore ein:

```
Teilscore = Σ(Punkte_i × Gewicht_i) / Σ(Gewicht_i)      nur über verfügbare Kennzahlen
```

Der entscheidende Teil ist das *nur über verfügbare Kennzahlen*: eine fehlende
Kennzahl geht **nicht mit null Punkten** ein, sondern fällt aus Zähler und
Nenner heraus. Sie kann den Score also nicht nach unten ziehen. Stattdessen
wird die Abdeckung ausgewiesen, etwa „Fundamental-Score: 76 – basiert auf 20
von 20 Kennzahlen (100 % der Gewichtung)".

Der Gesamtscore gewichtet die Teilscores:

```
Gesamtscore = Σ(Teilscore_k × Gewicht_k) / Σ(Gewicht_k)  nur über berechenbare Teilscores
```

Ein nicht berechenbarer Teilscore erhält das Gewicht null, und die übrigen
Gewichte werden proportional hochskaliert. Ohne Anthropic-Schlüssel trifft das
immer den Sentiment-Score: aus der Voreinstellung 40/25/25/10 wird dann
44/28/28. Die Oberfläche nennt die umverteilten Bereiche ausdrücklich.

**Voreinstellung der Gewichte:** Fundamental 40 %, Technik 25 %, Analysten
25 %, Sentiment 10 %. Über Schieberegler in der Seitenleiste und unter
*Einstellungen* veränderbar; nur die Verhältnisse zählen, intern wird auf 100 %
normiert.

### Drei Bewertungsarten

| Art | Wann | Beispiel |
|---|---|---|
| **Sektor-Perzentil** | Kennzahl ist nur im Branchenvergleich aussagekräftig | KGV, KUV, KBV, EV/EBITDA, ROE, Margen |
| **absolut** | Kennzahl hat einen branchenübergreifend sinnvollen Maßstab | ROIC, Eigenkapitalquote, Verschuldung/EBITDA, RSI, Momentum |
| **kategorial** | Kennzahl ist Text | SMA-50/200-Signal |

Bei der absoluten Bewertung wird zwischen hinterlegten Stützstellen linear
interpoliert. Die Punktefolge muss nicht steigen – so lassen sich Kennzahlen
mit günstigem Mittelbereich abbilden: die Ausschüttungsquote erreicht bei 50 %
ihr Maximum und fällt darüber wieder ab, weil über 100 % aus der Substanz
gezahlt wird. Auch der RSI ist so modelliert: Extremwerte in beide Richtungen
geben weniger Punkte.

### Sektorvergleich

Ein absoluter KGV-Maßstab würde strukturell immer dieselben Branchen nach oben
spülen – Banken handeln nun einmal niedriger als Softwarehäuser. Bewertet wird
deshalb der Rang innerhalb der eigenen Branche:

```
Perzentil = (schlechtere + 0,5 × gleiche) / Anzahl × 100
```

100 heißt bester Wert der Vergleichsgruppe, 0 der schlechteste. Bei Kennzahlen,
bei denen ein niedriger Wert besser ist (KGV), zählt ein höherer Wert als
schlechter.

**Wichtige Einschränkung:** Die Vergleichsgruppe ist das **eigene beobachtete
Universum**, nicht der Gesamtmarkt – eine kostenlose Quelle für echte
Sektor-Mediane gibt es nicht. Wer nur fünf Technologiewerte beobachtet,
vergleicht gegen diese fünf. Bei weniger als drei Titeln derselben Branche
(einstellbar) wird eine sektorrelative Kennzahl **gar nicht bewertet**, statt
einen Rang aus zwei Titeln zu behaupten. Das senkt die ausgewiesene Abdeckung
und ist beabsichtigt: ein einzelner Finanzwert in einer Tech-Watchlist bekommt
für seine Bewertungskennzahlen keine Punkte, und die Oberfläche sagt das auch.

Die Sektorstatistik wird ausschließlich aus bereits zwischengespeicherten Daten
gebildet. Ohne diese Einschränkung würde ihr Aufbau bei 50 Titeln Hunderte
Abrufe gegen die Rate-Limits auslösen.

### Nachvollziehbarkeit

Jeder Teilscore lässt sich in der Detailansicht aufklappen und zeigt dann pro
Kennzahl: den Wert, die Bewertungsart, die erreichten Punkte, das Gewicht, den
resultierenden Beitrag, die Datenquelle und – bei sektorrelativer Bewertung –
Größe und Median der Vergleichsgruppe. Darunter stehen die nicht eingegangenen
Kennzahlen mit Begründung sowie die Begründung jeder einzelnen Regel.

## Bedienung

### Übersicht – der Knopfdruck

**Alle Werte aktualisieren** holt die Daten des gewählten Universums. Ohne den
Haken *Cache verwerfen* werden nur Bereiche geholt, deren Lebensdauer abgelaufen
ist – ein erneutes Aktualisieren kurz danach kostet daher fast nichts. Mit Haken
wird alles neu geholt; das dauert bei 50 Titeln mehrere Minuten und belastet die
Rate-Limits.

Wichtig: **die Ansicht selbst ruft nie Daten ab.** Filter, Sortierung und
Gewichtung arbeiten auf dem vorhandenen Stand, sonst würde jedes Verschieben
eines Reglers einen Abruf auslösen. Neue Daten kommen ausschließlich über den
Knopf.

Filter gibt es für Gesamtscore, Sektor, Marktkapitalisierung, Dividendenrendite
und KGV. Dabei wird ein Punkt getrennt ausgewiesen, der leicht untergeht: ein
Titel, dessen gefilterte Kennzahl **fehlt**, ist nicht durch den Filter
gefallen – er ist nicht prüfbar. Beide Gruppen werden getrennt gezählt und
benannt, damit Titel nicht stillschweigend aus der Ansicht verschwinden.

Der CSV-Export gibt es in zwei Varianten: deutsch (Semikolon, Dezimalkomma –
öffnet in Excel direkt) und international (Komma, Dezimalpunkt). Fehlende Werte
erscheinen als leeres Feld, nie als 0.

### Vergleich

Zwei bis fünf Titel nebeneinander, mit Teilscores, Datenabdeckung je Titel und
den Kennzahlen als Matrix. Die Abdeckungsspalte ist hier besonders nützlich: ein
hoher Score aus wenigen Kennzahlen ist weniger belastbar als derselbe Score aus
vielen.

## Betrieb auf einem Server (Railway)

Die App ist als **lokale** Anwendung entworfen. Sie lässt sich hosten, aber vier
Dinge ändern sich dadurch grundlegend – bitte vor dem Deploy lesen.

### Was sich beim Hosten ändert

**1. Zugangsschutz ist Pflicht.** Wer die URL kennt, kann Datenabrufe auslösen –
und damit die hinterlegten API-Schlüssel verbrauchen. Beim Sprachmodell
entstehen dabei echte Kosten auf Ihrer Rechnung. Die App **verweigert deshalb
den Start**, wenn sie einen Hoster erkennt (Variable `PORT` gesetzt) und
`AKTIENMONITOR_APP_PASSWORD` leer ist. Lokal bleibt sie ohne Passwort nutzbar.

Zur Einordnung: Das ist ein einzelnes gemeinsames Passwort, keine
Benutzerverwaltung. Es schützt vor zufälligem Zugriff und ungewollten Kosten,
nicht vor einem entschlossenen Angreifer.

**2. Ohne Volume sind alle Daten nach jedem Deploy weg.** Der Container hat kein
dauerhaftes Dateisystem. Watchlist, Einstellungen und – besonders schmerzhaft –
der Cache würden bei jedem Neustart verschwinden. Der Cache ist die zentrale
Verteidigung gegen die Rate-Limits der Datenanbieter; ohne ihn läuft jeder
Seitenaufruf in neue Abrufe. **Ein Volume unter `/data` ist deshalb keine
Option, sondern Voraussetzung.**

**3. yfinance aus einem Rechenzentrum ist unzuverlässig.** Yahoo drosselt und
sperrt Anfragen von Cloud-IP-Bereichen deutlich aggressiver als von privaten
Anschlüssen. Da yfinance in diesem Projekt die Hauptdatenquelle ist, kann das
die gehostete App weitgehend unbrauchbar machen – mit vielen `n/a` statt Zahlen.
Das lässt sich vorab nicht zuverlässig sagen; es hängt vom Anbieter, der Region
und dem Zeitpunkt ab. Falls es auftritt, ist der lokale Betrieb die verlässliche
Variante.

**4. Eine Instanz, nicht mehr.** SQLite verträgt keine zwei Schreiber. In
`railway.toml` steht deshalb `numReplicas = 1`; bitte nicht hochsetzen.

### Schritte

```bash
# 1. Railway-CLI installieren (eine der beiden Varianten)
npm install -g @railway/cli
brew install railway

# 2. Anmelden und Projekt anlegen
railway login
railway init

# 3. Volume anlegen und unter /data einhängen
#    Am verlässlichsten über das Railway-Dashboard:
#    Service -> Settings -> Volumes -> Mount path: /data
#    (Die CLI kann das je nach Version auch, die Befehlsnamen wechseln dort
#     häufiger – im Zweifel das Dashboard nehmen.)

# 4. Variablen setzen
railway variables --set "AKTIENMONITOR_APP_PASSWORD=<eigenes-passwort>"
railway variables --set "FINNHUB_API_KEY=<optional>"
railway variables --set "ANTHROPIC_API_KEY=<optional>"

# 5. Deployen
railway up

# 6. Öffentliche Adresse erzeugen
railway domain
```

`AKTIENMONITOR_DB_PATH=/data/aktienmonitor.db` und `AKTIENMONITOR_LOG_DIR=/data/logs`
sind im `Dockerfile` bereits gesetzt und müssen nur angepasst werden, wenn Sie
das Volume woanders einhängen.

Railway baut über das `Dockerfile` (`railway.toml` legt das fest) und prüft die
Bereitschaft über `/_stcore/health`. Der Container läuft als unprivilegierter
Benutzer.

### Prüfen, dass der Schutz greift

Nach dem ersten Deploy sollte der Aufruf der URL eine Passwortabfrage zeigen.
Erscheint stattdessen die Meldung „Start verweigert", fehlt
`AKTIENMONITOR_APP_PASSWORD` – dann ist nichts offen, die App liefert nur keine
Inhalte aus.

### Lokal im Container testen

```bash
docker build -t aktienmonitor .
docker run --rm -p 8501:8501 \
  -e AKTIENMONITOR_APP_PASSWORD=test \
  -v "$(pwd)/data:/data" \
  aktienmonitor
```

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
