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

zeige_installationshinweis() {
    echo
    echo "Benoetigt wird Python 3.$MIN_PY_MINOR oder neuer. Installation:"
    case "$(uname -s)" in
        Darwin)
            echo "  brew install python@3.12"
            echo "  (ohne Homebrew: https://www.python.org/downloads/macos/)"
            echo
            echo "  Hinweis: macOS bringt Python 3.9 mit. Das laesst sich nicht"
            echo "  aktualisieren - eine neuere Version wird daneben installiert."
            ;;
        Linux)
            echo "  sudo apt install python3.12 python3.12-venv    # Debian/Ubuntu"
            echo "  sudo dnf install python3.12                    # Fedora"
            ;;
        *)
            echo "  https://www.python.org/downloads/"
            ;;
    esac
}

# Eine vorhandene Umgebung kann von einem aelteren Python stammen. Das faellt
# sonst erst bei der Installation auf - und dann mit einer Fehlermeldung, die
# nicht nach dem eigentlichen Grund aussieht.
if [ -x "$VENV/bin/python" ]; then
    if ! "$VENV/bin/python" -c "import sys; sys.exit(0 if sys.version_info >= (3, $MIN_PY_MINOR) else 1)" 2>/dev/null; then
        VORHANDEN="$("$VENV/bin/python" --version 2>&1 || echo 'unbekannt')"
        rot "Die vorhandene Umgebung nutzt $VORHANDEN - zu alt fuer dieses Projekt."

        if ! PYTHON="$(finde_python)"; then
            zeige_installationshinweis
            echo
            echo "Danach dieses Skript erneut starten - die alte Umgebung wird"
            echo "dann automatisch ersetzt."
            exit 1
        fi

        # Nur entfernen, wenn es wirklich eine virtuelle Umgebung ist.
        if [ -f "$VENV/pyvenv.cfg" ]; then
            info "Wird durch $($PYTHON --version) ersetzt."
            rm -rf "$VENV"
        else
            rot "$VENV ist keine virtuelle Umgebung. Bitte von Hand pruefen."
            exit 1
        fi
    fi
fi

if [ ! -x "$VENV/bin/python" ]; then
    info "Die Umgebung wird eingerichtet. Das dauert ein bis zwei Minuten."

    if [ -z "${PYTHON:-}" ] && ! PYTHON="$(finde_python)"; then
        rot "Kein Python 3.$MIN_PY_MINOR oder neuer gefunden."
        zeige_installationshinweis
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
    if ! "$VENV/bin/python" -m pip install --quiet -e ".[dev]" 2>"$VENV/.install-fehler"; then
        rot "Die Installation ist fehlgeschlagen."
        echo
        sed 's/^/  /' "$VENV/.install-fehler" | tail -20
        echo
        if grep -q "requires a different Python" "$VENV/.install-fehler"; then
            echo "Die Python-Version passt nicht."
            zeige_installationshinweis
        else
            echo "Bitte die Meldung oben pruefen. Haeufig liegt es an einer"
            echo "unterbrochenen Internetverbindung oder einem Proxy."
        fi
        exit 1
    fi
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
