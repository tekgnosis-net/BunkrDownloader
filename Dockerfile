# syntax=docker/dockerfile:1

FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --frozen-lockfile
COPY frontend ./
RUN npm run build

FROM python:3.11-slim AS runtime
ARG APP_VERSION=dev
ARG APP_UID=1000
ARG APP_GID=1000
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	APP_VERSION=${APP_VERSION} \
	HOME=/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY downloader.py ./
COPY main.py ./
COPY src ./src
COPY assets ./assets
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

RUN chown -R ${APP_UID}:${APP_GID} /app

USER ${APP_UID}:${APP_GID}

EXPOSE 8000
CMD ["uvicorn", "src.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
