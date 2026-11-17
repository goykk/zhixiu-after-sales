FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt "psycopg[binary]>=3.1"

COPY core ./core
COPY services ./services
COPY scripts ./scripts
COPY data ./data
COPY migrations ./migrations
COPY alembic.ini ./

RUN mkdir -p data/uploads data/traces data/reports

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# 初始化表结构与种子数据；种子失败只告警，不阻断 API 启动（README 要求人工排查）。
CMD ["sh", "-c", "python scripts/init_db.py && (python scripts/seed_demo.py || echo '[seed] failed, check logs') && exec uvicorn services.api.app.main:app --host 0.0.0.0 --port 8000"]