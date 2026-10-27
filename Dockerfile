# Zstock 预测分析平台
# 基础镜像服务器本地已有，无需外网拉取
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 代码
COPY config.py scrapers.py indicators.py analysis.py llm.py \
     db.py report_gen.py webapp.py run_pipeline.py ./
COPY templates/ ./templates/
COPY deploy/ ./deploy/

RUN mkdir -p /app/data/reports

# 默认起 Web；pipeline 由外层 cron 通过 docker compose exec 触发
EXPOSE 8501
CMD ["gunicorn", "-b", "0.0.0.0:8501", "-w", "1", "--threads", "4", \
     "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-", "webapp:app"]
