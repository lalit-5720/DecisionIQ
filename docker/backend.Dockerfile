FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DIQ_DATABASE_URL=sqlite:////srv/data/decisioniq.db

# libgomp: OpenMP runtime used by xgboost / scikit-learn; curl: container health check
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend backend
COPY ml ml

# Run as an unprivileged user. /srv/data is the volume (raw data, generated data, models, database, reports).
RUN useradd --create-home --uid 1000 app && mkdir -p /srv/data && chown -R app:app /srv
USER app

WORKDIR /srv/backend
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 CMD curl -fsS http://localhost:8000/api/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
