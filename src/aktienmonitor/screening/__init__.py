"""Marktweite Vorauswahl von Kandidaten.

Das uebrige Werkzeug bewertet ein Universum, das der Nutzer selbst
zusammenstellt. Dieses Paket sucht Kandidaten *ausserhalb* davon: es formuliert
harte Filterkriterien, die eine Marktabfrage beantworten kann.

Zur Einordnung - der wichtigste Vorbehalt bei marktweiter Suche: wer Hunderte
Titel nach Schwellen durchsucht, die nie auf Prognosekraft geprueft wurden,
findet oben in der Liste mit hoher Wahrscheinlichkeit Zufall statt Signal. Je
groesser die durchsuchte Menge, desto staerker dieser Effekt. Deshalb arbeiten
die Profile mit *Mindestanforderungen an die Qualitaet* und nicht allein mit
einer Rangfolge.
"""
