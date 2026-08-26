#!/usr/bin/env bash
#
# Aktienmonitor starten.
#
#   ./start.sh            startet auf Port 8501
#   ./start.sh 8502       startet auf einem anderen Port
#
# Das Skript richtet beim ersten Lauf alles ein: virtuelle Umgebung,
# Abhaengigkeiten und Konfigurationsdatei. Danach startet es nur noch.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

PORT="${1:-8501}"
VENV=".venv"
MIN_PY_MINOR=11

rot()  { printf '\033[31m%s\033[0m\n' "$*"; }
gruen(){ printf '\033[32m%s\033[0m\n' "$*"; }
info() { printf '\033[36m%s\033[0m\n' "$*"; }

# --- 1. Passenden Python-Interpreter finden ---------------------------------
finde_python() {
    for kandidat in python3.13 python3.12 python3.11 python3 python; do
        if command -v "$kandidat" >/dev/null 2>&1; then
            if "$kandidat" -c "import sys; sys.exit(0 if sys.version_info >= (3, $MIN_PY_MINOR) else 1)" 2>/dev/null; then
                echo "$kandidat"
                return 0
            fi
        fi
    done
    return 1
}

if [ ! -x "$VENV/bin/python" ]; then
    info "Erster Start - die Umgebung wird eingerichtet. Das dauert ein bis zwei Minuten."

    if ! PYTHON="$(finde_python)"; then
        rot "Kein Python 3.$MIN_PY_MINOR oder neuer gefunden."
        echo
        echo "Installation:"
        echo "  macOS:          brew install python@3.12"
        echo "  Ubuntu/Debian:  sudo apt install python3.12 python3.12-venv"
        echo "  Windows:        https://www.python.org/downloads/"
        exit 1
    fi

    info "Verwende $($PYTHON --version)"
    "$PYTHON" -m venv "$VENV" || {
        rot "Die virtuelle Umgebung liess sich nicht anlegen."
        echo "Unter Debian/Ubuntu fehlt dafuer oft das Paket python3-venv:"
        echo "  sudo apt install python3-venv"
        exit 1
    }
fi

# --- 2. Abhaengigkeiten installieren, wenn noetig ---------------------------
# Der Marker haelt fest, fuer welchen Stand von pyproject.toml installiert
# wurde. Aendert sich die Datei, wird neu installiert - sonst nicht.
MARKER="$VENV/.installiert"
PROJEKT_HASH="$(cksum pyproject.toml | awk '{print $1}')"

if [ ! -f "$MARKER" ] || [ "$(cat "$MARKER" 2>/dev/null)" != "$PROJEKT_HASH" ]; then
    info "Abhaengigkeiten werden installiert ..."
    "$VENV/bin/python" -m pip install --quiet --upgrade pip
    "$VENV/bin/python" -m pip install --quiet -e ".[dev]" || {
        rot "Die Installation ist fehlgeschlagen."
        echo "Bitte die Ausgabe oben pruefen; haeufigste Ursache ist eine fehlende"
        echo "Internetverbindung oder ein Proxy."
        exit 1
    }
    echo "$PROJEKT_HASH" > "$MARKER"
    gruen "Abhaengigkeiten installiert."
fi

# --- 3. Konfigurationsdatei anlegen -----------------------------------------
if [ ! -f .env ]; then
    cp .env.example .env
    info "Datei .env aus der Vorlage angelegt."
    echo "   API-Schluessel koennen dort spaeter eingetragen werden - fuer den"
    echo "   ersten Start ist das nicht noetig."
fi

# --- 4. Starten --------------------------------------------------------------
echo
gruen "Aktienmonitor startet auf  http://localhost:$PORT"
echo "   Beenden mit Strg+C. Dieses Fenster muss offen bleiben."
echo

exec "$VENV/bin/streamlit" run app.py \
    --server.port "$PORT" \
    --browser.gatherUsageStats false
