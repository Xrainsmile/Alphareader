FROM python:3.12-slim

# Prevent Python from writing .pyc and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps for asyncpg, lxml (akshare), etc.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc g++ libpq-dev curl \
        libxml2-dev libxslt1-dev zlib1g-dev libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-"]
