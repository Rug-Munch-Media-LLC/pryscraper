# Pry — Multi-stage Docker build
# Stage 1: Build deps + Playwright + Tesseract
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS builder

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget=1.25.0-2 \
    curl=8.14.1-2+deb13u4 \
    gnupg=2.4.7-21+deb13u1 \
    ca-certificates=20250419 \
    libnss3=2:3.110-1+deb13u3 \
    libnspr4=2:4.36-1 \
    libatk1.0-0t64=2.56.2-1+deb13u1 \
    libatk-bridge2.0-0t64=2.56.2-1+deb13u1 \
    libcups2t64=2.4.10-3+deb13u2 \
    libdrm2=2.4.124-2 \
    libdbus-1-3=1.16.2-2 \
    libxcb1=1.17.0-2+b1 \
    libxkbcommon0=1.7.0-2 \
    libxcomposite1=1:0.4.6-1 \
    libxdamage1=1:1.1.6-1+b2 \
    libxrandr2=2:1.5.4-1+b3 \
    libgbm1=25.0.7-2+deb13u1 \
    libpango-1.0-0=1.56.3-1 \
    libcairo2=1.18.4-1+b1 \
    libasound2t64=1.2.14-1 \
    tesseract-ocr=5.5.0-1+b1 \
    tesseract-ocr-eng=1:4.1.0-2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python3 -m playwright install chromium 2>&1 | tail -1

# Stage 2: Runtime
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3=2:3.110-1+deb13u3 \
    libnspr4=2:4.36-1 \
    libatk1.0-0t64=2.56.2-1+deb13u1 \
    libatk-bridge2.0-0t64=2.56.2-1+deb13u1 \
    libcups2t64=2.4.10-3+deb13u2 \
    libdrm2=2.4.124-2 \
    libdbus-1-3=1.16.2-2 \
    libxcb1=1.17.0-2+b1 \
    libxkbcommon0=1.7.0-2 \
    libxcomposite1=1:0.4.6-1 \
    libxdamage1=1:1.1.6-1+b2 \
    libxrandr2=2:1.5.4-1+b3 \
    libgbm1=25.0.7-2+deb13u1 \
    libpango-1.0-0=1.56.3-1 \
    libcairo2=1.18.4-1+b1 \
    libasound2t64=1.2.14-1 \
    tesseract-ocr=5.5.0-1+b1 \
    tesseract-ocr-eng=1:4.1.0-2 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /root/.cache/ms-playwright /root/.cache/ms-playwright

WORKDIR /app
COPY *.py ./
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY alembic.ini ./alembic.ini
COPY alembic/ ./alembic/
COPY routers/ ./routers/
COPY llm_providers/ ./llm_providers/
COPY stealth_scripts/ ./stealth_scripts/
COPY templates/ ./templates/
COPY pry_mcp/ ./pry_mcp/
RUN mkdir -p /app/sessions /app/pry-data

RUN useradd --create-home --shell /bin/bash --uid 1000 pry && chown -R pry:pry /app
USER pry

EXPOSE 8002
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8002/health', timeout=2).status == 200 else 1)" || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8002", \
     "--workers", "1", "--timeout-keep-alive", "120", "--limit-concurrency", "20"]
