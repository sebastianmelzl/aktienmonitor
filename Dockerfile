# Container-Abbild fuer den gehosteten Betrieb (Railway, Fly, Render, ...).
# Lokal wird die App weiterhin einfach mit "streamlit run app.py" gestartet -
# dafuer wird dieses Abbild nicht gebraucht.

FROM python:3.11-slim

# Wartungsarm: keine .pyc-Dateien, ungepufferte Ausgabe fuer die Container-Logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Abhaengigkeiten zuerst: so bleibt die Ebene im Cache, solange sich
# pyproject.toml nicht aendert.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e "."

COPY app.py ./
COPY views/ ./views/
COPY .streamlit/ ./.streamlit/

# Nicht als root laufen. /data ist der Einhaengepunkt fuer das persistente
# Volume - ohne das waeren Watchlist und Cache bei jedem Neustart weg.
RUN useradd --create-home --uid 10001 aktienmonitor \
    && mkdir -p /data /app/logs \
    && chown -R aktienmonitor:aktienmonitor /data /app/logs
USER aktienmonitor

ENV AKTIENMONITOR_DB_PATH=/data/aktienmonitor.db \
    AKTIENMONITOR_LOG_DIR=/data/logs \
    PORT=8501

EXPOSE 8501

# Streamlits eigener Endpunkt fuer die Bereitschaftspruefung.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\",\"8501\")}/_stcore/health').read()" || exit 1

# PORT wird vom Hoster gesetzt; die Shell-Form loest die Variable auf.
CMD streamlit run app.py \
    --server.port=${PORT} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
