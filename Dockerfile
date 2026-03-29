FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Environment
ENV PYTHONPATH=/app
ENV SHOPAI_ENV=production
ENV SHOPAI_LOG_LEVEL=INFO

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "from core.self_monitor import HealthChecker; h=HealthChecker().check_all(); exit(0 if h['status']=='healthy' else 1)"

# API server
EXPOSE 8080
CMD ["python", "-m", "api.server"]
