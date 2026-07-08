# ── Stage 1: Builder — compile C extensions & build wheels ──
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Switch Debian bookworm apt sources to Tencent mirror (server is in Guangzhou)
# to avoid slow/timeout on deb.debian.org from mainland China networks.
# python:3.12-slim uses the new deb822 format at /etc/apt/sources.list.d/debian.sources.
RUN sed -i 's|http://deb.debian.org|http://mirrors.tencentyun.com|g; s|http://security.debian.org|http://mirrors.tencentyun.com|g' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|http://deb.debian.org|http://mirrors.tencentyun.com|g; s|http://security.debian.org|http://mirrors.tencentyun.com|g' \
        /etc/apt/sources.list 2>/dev/null || true

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

# Switch Debian bookworm apt sources to Tencent mirror (see builder stage).
RUN sed -i 's|http://deb.debian.org|http://mirrors.tencentyun.com|g; s|http://security.debian.org|http://mirrors.tencentyun.com|g' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|http://deb.debian.org|http://mirrors.tencentyun.com|g; s|http://security.debian.org|http://mirrors.tencentyun.com|g' \
        /etc/apt/sources.list 2>/dev/null || true

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
# 多 worker 提升 API 并发：pipeline 跑批（抓取/打分/去重）为 CPU 密集任务，
# 单 worker 时会在跑批期间阻塞事件循环，导致浏览器 API 请求 15s 超时（Nginx 499）。
# 多 worker 下，仅有持有 Redis 调度锁的 worker 跑 pipeline，其余 worker 专责 API，
# 避免全部 worker 被饿死。见 app/services/scheduler.py 的分布式锁逻辑。
CMD ["python", "-m", "gunicorn", "app.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "1800", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-"]
