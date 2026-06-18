# ── Stage 1: Builder — compile C extensions & build wheels ──
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Install system deps needed to compile C extensions (asyncpg, lxml, scikit-learn, etc.)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc g++ libpq-dev \
        libxml2-dev libxslt1-dev zlib1g-dev libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Install production Python deps into a virtual-env so we can copy it cleanly
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
# Use a domestic PyPI mirror (server is in Guangzhou) with generous timeout/retries
# to avoid ReadTimeout against files.pythonhosted.org on slow links.
RUN pip install --no-cache-dir -r requirements.txt \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --timeout 120 --retries 10

# ── Stage 2: Runtime — lean production image ──
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Only the minimal runtime libraries — no gcc/g++/dev headers
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 libxml2 libxslt1.1 curl && \
    rm -rf /var/lib/apt/lists/*

# Copy pre-built virtual-env from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY . .

# Create non-root user for security
RUN adduser --disabled-password --gecos '' appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Production: gunicorn with uvicorn worker
# Single worker to avoid duplicate APScheduler instances across processes.
# Async I/O handles concurrency within the single worker — sufficient for
# our pipeline-heavy workload on a 2-core Lighthouse instance.
CMD ["python", "-m", "gunicorn", "app.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "1", \
     "--timeout", "1800", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-"]
