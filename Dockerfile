# Storm Readiness (Dallas) - one container: React UI + FastAPI + ADK agent.
# Build: gcloud builds submit --tag us-central1-docker.pkg.dev/<project>/storm-agent/app
# Data is not baked in (except the Census county boundaries): the app reads processed data from
# GCS at startup (store.py) and refuses to start if it can't.

FROM node:20-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
# County centroids for the outage model (models/pipeline.py reads them from data/raw/census/counties).
COPY data/raw/census/counties/ data/raw/census/counties/
COPY --from=ui /ui/dist frontend/dist
WORKDIR /app/backend
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
