"""Kennzahlenberechnung - unabhaengig von Datenabruf und Oberflaeche.

Die Funktionen dieses Pakets nehmen ausschliesslich einfache Datenstrukturen
entgegen (Listen, Dicts, DataFrames) und geben ``MetricValue``-Objekte zurueck.
Sie fuehren keine Netzwerkzugriffe aus und sind damit vollstaendig mit fixen
Testdaten pruefbar.
"""
