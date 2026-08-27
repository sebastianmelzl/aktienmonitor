# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Sprachkonvention

Oberfläche, Kommentare und Docstrings sind **deutsch**. Bezeichner im Code sind
**englisch**. Beides wurde bewusst so festgelegt — nicht angleichen.

Umlaute werden in Quelldateien als `ae/oe/ue/ss` geschrieben (`Kennzahlen fuer
...`), in der Oberfläche und in Markdown-Dateien dagegen normal (`für`).

## Befehle

```bash
./start.sh                 # richtet beim ersten Lauf alles ein und startet
./start.sh 8502            # anderer Port

.venv/bin/python -m pytest                          # alle Tests (ohne Netz)
.venv/bin/python -m pytest tests/test_scoring.py    # eine Datei
.venv/bin/python -m pytest -k "perzentil"           # nach Namen filtern
.venv/bin/python -m pytest tests/test_pages.py -q   # nur die Seitendurchläufe
.venv/bin/ruff check . --fix                        # Linting
```

Manuelles Setup ohne `start.sh`: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`.

## Die zentrale Regel: keine erfundenen Daten

Das ist die wichtigste Eigenschaft dieses Projekts und technisch durchgesetzt,
nicht nur dokumentiert. Wer hier Code ändert, muss sie kennen:

- **`MetricValue` (`models.py`) ist der einzige Träger für Kennzahlen.** Ein
  fehlender Wert ist dort ein expliziter Zustand mit `missing_reason` — niemals
  `0.0`, niemals `NaN`, niemals ein Schätzwert.
- `__post_init__` wandelt `NaN` und `Inf` automatisch in „fehlend" um.
- `0.0` ist ein **gültiger Wert**. Deshalb nutzt der Code `_pick`/`_first` statt
  `or` für Quellen-Rückfallebenen (`metrics/fundamental.py`) — ein `or` würde
  eine Marge von exakt null als fehlend behandeln und still auf die falsche
  Quelle ausweichen.
- Nicht berechenbar heißt **kein Wert**: Wachstumsrate aus einem Verlust heraus,
  Division durch null, Perzentil ohne Vergleichsgruppe, Stimmungssaldo aus
  weniger als drei Meldungen.
- Abgeleitete Kennzahlen tragen `is_computed=True` und führen ihre
  Eingangsgrößen in `inputs` mit.

Beim Erweitern gilt: lieber eine Kennzahl weglassen als sie zu raten.

## Schichten

`metrics/` und `scoring/` importieren **nie** aus `providers/` oder `ui/`. Sie
nehmen einfache Datenstrukturen entgegen und geben `MetricValue` zurück. Das ist
der Grund, warum das gesamte Rechenwerk ohne Netz und ohne Oberfläche testbar
ist — diese Trennung bitte nicht aufweichen.

```
app.py            Navigation (st.navigation, nach Sektionen gruppiert) + Zugangsschutz
views/            Seiten — nur Darstellung, kein Rechenkram
src/aktienmonitor/
  models.py       MetricValue, MetricSet, NewsItem, SecurityProfile
  config.py       Konfiguration aus .env
  providers/      Datenabruf
  metrics/        Kennzahlen (netzfrei, UI-frei)
  scoring/        Bewertung (netzfrei, UI-frei)
  sentiment/      Schlagzeilen-Einordnung
  narrative/      Faktenblatt und textliche Begruendung je Kandidat
  screening/      Suchprofile fuer die marktweite Vorauswahl (ohne yfinance)
  costs/          Trade-Republic-Kosten und deutsche Kapitalertragsteuer
  benchmark/      Renditevergleich gegen einen Referenz-ETF
  backtest/       Rollierender Test des technischen Teilscores ohne Lookahead
  formatting.py   Zahlformatierung - bewusst auf Paketebene, nicht unter ui/
  storage/        SQLite: Schema, Cache, Watchlist, Einstellungen
  ui/             Formatierung, Charts, Tabellenlogik, Zugang
```

## Datenabruf

**`ProviderRuntime.fetch` (`providers/base.py`) ist der einzige Weg nach
draußen.** Jeder Abruf durchläuft dort dieselbe Kette: Cache → Token-Bucket →
Wiederholversuche mit Backoff → Protokollierung. Neue Endpunkte gehen durch
diese Methode, nicht daran vorbei.

Besonderheiten, die man kennen muss:

- **`cache_only=True`** unterdrückt jeden Netzzugriff und liefert auch
  abgelaufene Stände. Die Übersicht und der Sektorvergleich laufen ausschließlich
  so — sonst würde jede Filteränderung bei 50 Titeln Hunderte Abrufe auslösen.
  Neue Daten kommen nur über den Aktualisieren-Knopf.
- **Abgelaufener Cache als Rückfallebene:** Schlägt ein Live-Abruf fehl, wird der
  alte Stand geliefert und über `age_seconds` als alt ausgewiesen.
- **`AccessForbidden` (HTTP 403) wird nicht wiederholt** — ein im Free-Tier
  gesperrter Endpunkt wird durch Warten nicht frei.

**yfinance ist die Hauptquelle, Finnhub ergänzt.** Der Finnhub-Free-Tier deckt
weder Kurshistorie noch nicht-US-Titel ab. `providers/capabilities.py` prüft zur
Laufzeit, was der Schlüssel des Nutzers wirklich kann, statt es zu behaupten.

Yahoo benennt Bilanzpositionen nicht einheitlich. `metrics/statements.py` arbeitet
deshalb mit Aliaslisten (exakt → normalisiert → Teilstring) und gibt `None`
zurück, wenn keine Bezeichnung passt.

## Scoring

Vier Teilscores 0–100, gewichtet zum Gesamtscore. Drei Bewertungsarten in
`scoring/rules.py`:

- **absolut** — Stützstellen mit linearer Interpolation. Die Punktefolge darf
  fallen, damit Kennzahlen mit günstigem Mittelbereich abbildbar sind
  (Ausschüttungsquote, RSI).
- **sektorrelativ** — Perzentilrang innerhalb der Branche, für alle
  Bewertungskennzahlen und Margen.
- **kategorial** — Textwerte wie das SMA-Kreuzungssignal.

Zwei Mechanismen, die man beim Ändern nicht kaputt machen darf:

- **Normierung auf verfügbare Kennzahlen.** Eine fehlende Kennzahl fällt aus
  Zähler *und* Nenner heraus, geht also nicht mit null Punkten ein. Die Abdeckung
  wird nach Anzahl und Gewicht ausgewiesen.
- **Gewichtsumverteilung.** Ein nicht berechenbarer Teilscore bekommt Gewicht
  null, die übrigen werden proportional hochskaliert.

**Die Vergleichsgruppe des Sektorvergleichs ist das eigene Universum**, nicht der
Markt — für echte Sektor-Mediane gibt es keine kostenlose Quelle. Unter drei
Titeln derselben Branche wird gar nicht bewertet. Das ist Absicht und in der
Oberfläche benannt.

Neue Regeln brauchen zwingend ein `rationale`; es wird in der Oberfläche
angezeigt und ist im Regelwerkstest eingefordert.

## Verlauf und Kandidaten

`storage/history.py` schreibt bei **jedem Aktualisieren in der Uebersicht** einen
Stand je Titel fort (Scores, Abdeckung, Kurs, SMA-Signal, Revisionssaldo).
Nur dort - nicht bei jedem Seitenaufbau, sonst gaebe es nie einen brauchbaren
Vergleichsstand.

`ScoreHistory.previous()` liefert bewusst den **vorletzten** Stand mit
Mindestabstand von sechs Stunden. Der letzte entspricht dem aktuellen Zustand;
ein Vergleich damit waere immer null.

`scoring/changes.py` leitet daraus Ereignisse ab (netzfrei, UI-frei). Ereignisse
ohne Vergleichsstand - ein frisches Kreuzen der Durchschnitte - werden auch beim
ersten Lauf gemeldet.

## Marktweite Vorschlaege

Alles uebrige bewertet das Universum des Nutzers. `screening/` sucht Kandidaten
*ausserhalb* davon, in zwei Stufen:

1. **`providers/screener.py`** setzt ein Profil in eine `EquityQuery` um und
   fragt Yahoo einmal ab - bis zu 250 Titel je Lauf, gestuetzt auf wenige Felder.
2. Die vollstaendige Bewertung laeuft erst danach und nur fuer die gewaehlten
   Treffer, weil dafuer je Titel mehrere Abrufe noetig sind.

`screening/profiles.py` importiert bewusst **kein yfinance** - die Profile sind
Daten und einzeln pruefbar; die Uebersetzung passiert im Provider.

Zwei Dinge, die beim Aendern erhalten bleiben muessen:

- **Jedes Profil braucht eine Qualitaetshuerde** (Rentabilitaet, Marge,
  Verschuldung oder Liquiditaet). Eine Suche allein nach Guenstigkeit findet
  vor allem Titel, die aus gutem Grund billig sind. Ein Test fordert das ein.
- **Die Einheiten der Screenerfelder sind nicht dokumentiert** und liessen sich
  ohne Netzzugang nicht pruefen. `diagnose_result_count` meldet deshalb null
  Treffer und das Anschlagen an der Obergrenze als wahrscheinlichen
  Einheitenfehler - beides ist das erwartbare Symptom.

Bei Vorschlaegen ist die Sektor-Vergleichsgruppe **die Trefferliste selbst**,
nicht die Watchlist - sie stammt aus derselben Suche.

**`views/investieren.py`** ist derselbe zweistufige Ablauf, aber als ein
einzelner Knopf statt eines mehrstufigen Assistenten: Betrag eingeben, Profil
waehlen, fertig. Zwei Unterschiede zu Vorschlaegen/Aufteilung:

- **Auswahl nach fundamentalem Teilscore, nicht nach Gesamtscore.** Sortiert
  wird nach `scored.categories["fundamental"].score` - das ist die
  ausdrueckliche Anforderung an diese Seite (Fundamentalanalyse als
  Auswahlkriterium), nicht nur als Anzeige danach.
- **Feste Anzahl von fuenf Titeln**, gleichgewichtet ueber `scoring/allocation.py`
  verteilt (`AllocationConstraints(max_positions=5)`). Reicht die Marktsuche
  keine fuenf Titel mit berechenbarem Fundamental-Score her, wird das benannt,
  nicht mit weniger aussagekraeftigen Titeln aufgefuellt.

Die REGIONS-Zuordnung fuer den Regionsfilter liegt in `screening/profiles.py`,
weil sie von mehreren Seiten (Vorschlaege, Investieren) genutzt wird.

## Aufteilungsrechner

`scoring/allocation.py` verteilt einen Betrag nach vorgegebenen Regeln. Zwei
Dinge, die man beim Aendern nicht verlieren darf:

- **Unerfuellbare Deckel werden benannt, nicht still aufgeloest.** Positions- und
  Branchengrenze koennen sich widersprechen (vier von sechs Titeln in einer
  Branche). `_capacity` prueft das vorab, `_cap_violations` kontrolliert nach.
- **Die Mindestabdeckung liegt bei 35 %, nicht hoeher.** Die sektorrelativen
  Regeln machen rund 47 % der Fundamentalgewichtung aus und fallen ohne
  Vergleichsgruppe weg - ohne Branchengruppen sind hoechstens etwa 53 %
  erreichbar. Eine Schwelle von 50 % wuerde fast jeden Titel ausschliessen.

Der Rechner beurteilt nichts. Er kennt weder Korrelationen noch die uebrige
Vermoegenslage; das steht so auf der Seite.

## Kosten und Steuern (Trade Republic)

`costs/model.py` ist netzfrei und UI-frei wie `metrics/`/`scoring/`. Zwei
Klassen, die getrennt bleiben:

- **`BrokerCosts`** bildet die Orderkosten ab: 1 EUR Fremdkostenpauschale je
  Order (Sparplaene kostenlos), plus die halbe Geld-Brief-Spanne als Naeherung
  fuer den Spread. `cost_share` macht sichtbar, dass viele kleine Positionen
  ueberproportional teuer sind - das ist der Kernpunkt fuer Einsteiger mit
  kleinen Betraegen.
- **`TaxSettings`/`tax_on_gain`** bilden die deutsche Kapitalertragsteuer ab:
  25 % KESt plus Soli (effektiv 26,375 % ohne Kirchensteuer), Sparerpauschbetrag
  (1.000 EUR ledig / 2.000 EUR zusammen veranlagt) vor der Teilfreistellung
  abgezogen, danach 30 % Teilfreistellung fuer Aktienfonds/ETFs nach §20 InvStG.

`break_even_return` rechnet Hin- und Rueckweg (Kauf plus Verkauf) zusammen -
eine Position muss beide Ordergebuehren erst wieder einspielen, bevor ueberhaupt
ein Gewinn entsteht.

## Benchmark-Vergleich

`benchmark/compare.py` ist ebenfalls netzfrei und UI-frei. Er stellt einem
Titel eine Referenz gegenueber - Vorgabe: `EUNL.DE` (iShares Core MSCI World,
Xetra), ueber `BENCHMARK_TICKER` änderbar. Die Kurshistorie kommt ueber
`StockDataService.get_benchmark_bars()` und laeuft durch denselben
Cache/Token-Bucket wie jeder andere Titel.

Eine Einschraenkung wird ueberall mitgefuehrt, wo der Vergleich erscheint:
verglichen werden **Kursrenditen**, keine um Ausschuettungen bereinigten. Bei
einem ausschuettenden Referenz-ETF verzerrt das zulasten der Benchmark - die
tatsaechliche Differenz faellt real etwas kleiner aus. `ui/benchmark.py`
buendelt die Darstellung: `render_comparison` fuer einen einzelnen Titel
(Detailansicht), `render_portfolio_comparison` fuer eine gewichtete
Positionsliste (Aufteilung), bei der fehlende Kurshistorien einzelner Titel
das Gewicht der uebrigen fuer diesen Zeitraum neu normieren statt sie mit 0 zu
werten.

## Entscheidungstagebuch

`storage/journal.py` (Tabelle `decision_journal`, Migration v3) haelt eigene
Kauf-/Verkaufsentscheidungen fest: Ticker, Aktion, Datum, Kurs, Betrag,
Stueckzahl, der Gesamtscore zum Eintragungszeitpunkt und eine **eigene**
Begruendung. Anders als `score_history` schreibt sich hier nichts
automatisch fort - ein Eintrag entsteht ausschliesslich durch Eingabe auf
der Seite **Tagebuch**.

Wichtig beim Aendern: die Begruendung ist die Einschaetzung des Nutzers zum
Zeitpunkt der Entscheidung. Sie darf nicht nachtraeglich generiert oder von
einem Sprachmodell verfasst werden - ein Tagebuch, das sich im Nachhinein
selbst rechtfertigt, verfehlt seinen Zweck (Rueckschaufehler vermeiden).

Die Seite vergleicht jede Entscheidung rueckblickend mit der Benchmark: die
eigene Kursentwicklung misst vom eingetragenen Kurs zum aktuellen Kurs, die
Referenz laeuft ueber `benchmark.compare.return_between` vom
Entscheidungsdatum bis heute - bewusst zwei verschiedene Berechnungswege,
weil der eigene Kurs eine tatsaechliche Transaktion ist und die Referenz nur
ein hypothetischer Vergleich zum Schlusskurs jenes Tages.

## Backtest

`backtest/technical.py` ist ebenfalls netzfrei. Er testet **ausschliesslich
den technischen Teilscore** - das ist eine bewusste Einschraenkung, keine
Vereinfachung aus Bequemlichkeit: Fundamental-, Analysten- und
Sentiment-Kennzahlen liegen aus kostenlosen Quellen nicht als Zeitreihe vor
(yfinance liefert nur den *aktuellen* Bilanzstand). Ein Test dieser
Teilscores wuerde entweder heutiges Wissen in die Vergangenheit projizieren
(Lookahead) oder Werte erfinden - beides verletzt die zentrale Regel des
Projekts. Der technische Teilscore laesst sich dagegen an jedem Stichtag
ausschliesslich aus vorangegangenen Kursen neu berechnen.

`walk_forward()` berechnet den Teilscore an jedem ``step_days``-ten
Handelstag ausschliesslich aus ``bars`` bis einschliesslich dieses Tages und
misst danach die tatsaechliche Rendite der folgenden ``horizon_days``
Handelstage. **Kein Lookahead ist die wichtigste Eigenschaft dieses Moduls**
und hat einen eigenen Test (`test_backtest.py::TestKeinLookahead`), der
prueft, dass ein nachtraeglich an dieselbe Kursreihe angehaengter
Kursschock die bereits berechneten frueheren Stichtage unveraendert laesst.

`LIMITATIONS` fasst zusammen, was trotzdem ungeloest bleibt: Survivorship
Bias (nur die heutige Watchlist, keine historisch ausgeschiedenen Titel),
kleine und bei kurzem `step_days` ueberlappende Stichproben, keine
Transaktionskosten oder Steuern, keine Garantie fuer die Zukunft. Diese
Liste erscheint woertlich als Warnhinweis auf der Backtest-Seite - sie darf
beim Aendern nicht stillschweigend verkuerzt werden.

## Sentiment

`sentiment/classifier.py` ordnet Schlagzeilen über die Anthropic-API ein
(`output_config.format` als JSON-Schema, `effort: low`). Vorgabemodell
`claude-opus-5`, über `ANTHROPIC_MODEL` änderbar.

**Jede Einordnung wird je Schlagzeile dauerhaft zwischengespeichert** — Folgeläufe
kosten nichts, und `cache_only` kommt ganz ohne API-Aufruf aus.

Kein Pfad darf zu einem geratenen Wert führen: fehlendes Urteil, ungültiges JSON,
unbekanntes Label, Index außerhalb des Bündels und Ablehnungen lassen die Meldung
**unbewertet** statt sie auf „neutral" zu setzen. `available` prüft Schlüssel
**und** installiertes Paket.

## Tests

338 Tests, alle ohne Netzzugriff. Jeder rechnet gegen handgerechnete Werte; die
Herleitung steht als Kommentar am Test — bei Änderungen bitte beibehalten.

`tests/test_pages.py` führt jede Seite mit Streamlits eigenem Testläufer
(`AppTest`) gegen eine temporäre Datenbank mit synthetischen Titeln aus. Die
Fixture `seeded_app` liegt in `tests/conftest.py`. Diese Durchläufe fangen, was
Unit-Tests nicht sehen: umbenannte Funktionen, fehlerhafte Spaltenkonfiguration,
Tippfehler in einer Seite.

Testticker heißen bewusst `TEST*`, damit sie nie mit echten Werten zu
verwechseln sind.

## Oberfläche für Einsteiger

Elf Seiten sind fuer einen Einsteiger auf einen Blick zu viel. `app.py`
gruppiert sie deshalb in `st.navigation` nach Sektionen (Einstieg, Titel
pruefen, Neue Ideen, Geld anlegen, Vertiefung, Verwaltung) statt einer
flachen Liste. Bei einer leeren Watchlist zeigt die Uebersicht zusaetzlich
eine Schritt-fuer-Schritt-Anleitung, welche Seiten fuer den Einstieg
tatsaechlich noetig sind (Watchlist, Uebersicht, Detailansicht, Aufteilung,
Tagebuch) und welche bewusst fuer spaeter sind (Vergleich, Backtest,
Datenquellen, Einstellungen).

## Gehosteter Betrieb

`ui/auth.py` **verweigert den Start**, wenn ein Hoster erkannt wird (`PORT` oder
`RAILWAY_*` gesetzt) und `AKTIENMONITOR_APP_PASSWORD` leer ist — sonst könnte
jeder mit der URL die hinterlegten API-Schlüssel verbrauchen. Lokal bleibt die
App ohne Passwort nutzbar. `Dockerfile` und `railway.toml` sind vorbereitet;
`/data` ist der Einhängepunkt für das persistente Volume.

## Stand und offene Punkte

Phasen 0–4 sind fertig (Datenabruf, Kennzahlen, Scoring, Übersicht, Sentiment).

**Bisher wurde nie ein echter Datenabruf ausgeführt.** Die gesamte Entwicklung
lief in einer Umgebung ohne Netzzugang zu Yahoo, Finnhub und der Anthropic-API.
Alles ist gegen fixe Testdaten und synthetische Cache-Einträge geprüft. Ungeprüft
sind damit vor allem:

- ob die yfinance-Feldnamen bei echten Titeln so heißen wie die Aliaslisten
  annehmen — bei **nicht-amerikanischen Titeln** der wahrscheinlichste
  Stolperstein
- welche Finnhub-Endpunkte der Schlüssel des Nutzers tatsächlich freigibt
- ob `output_config.format` mit dem Sentiment-Schema die erwartete Antwort liefert
- ob das Docker-Abbild baut (kein Docker-Daemon in der Entwicklungsumgebung)
- ob `EUNL.DE` unter yfinance tatsächlich eine Kurshistorie liefert — der
  Benchmark-Vergleich (`benchmark/`) ist nur gegen synthetische Kursreihen
  getestet

Erster sinnvoller Schritt lokal: **Seite „Datenquellen" → „Check jetzt
ausführen"**. Sie ruft jeden Endpunkt einmal auf und schreibt fest, was
funktioniert — das ist die Grundlage für alles Weitere.
