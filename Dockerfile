# Calm Trader (Binance Demo) - small, non-root image.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    JOURNAL_PATH=/data/journal.db

WORKDIR /app

# Install dependencies first so this layer is cached between code changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY static ./static
COPY tests ./tests

# Run as an unprivileged user; /data holds the SQLite journal (mounted as a volume).
RUN useradd --create-home --uid 1000 trader \
    && mkdir -p /data \
    && chown -R trader:trader /app /data
USER trader
VOLUME ["/data"]

EXPOSE 8000

# No curl in the slim image, so probe with Python.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4).status == 200 else 1)"

# Bind to all interfaces INSIDE the container. docker-compose.yml publishes the
# port only on the host's 127.0.0.1, so it is still reachable from your laptop only.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
