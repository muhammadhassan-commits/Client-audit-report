FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# curl is used by 04_server_checks.py for the HTTP/2 and HTTP/3 probes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-web.txt ./
RUN pip install -r requirements.txt -r requirements-web.txt

# Chromium plus its system libraries, for the M-section rendering checks.
RUN playwright install --with-deps chromium

COPY . .

# Evidence and reports land here. Mount a disk at /data to keep them across
# deploys; without one they are lost when the instance restarts.
ENV AUDIT_OUT_DIR=/data/out
RUN mkdir -p /data/out

EXPOSE 8000
CMD ["sh", "-c", "uvicorn webapp.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
