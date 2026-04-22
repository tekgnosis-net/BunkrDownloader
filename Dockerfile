# syntax=docker/dockerfile:1

# Always build the frontend on the native host arch. The output (HTML/JS/CSS/
# woff2) is platform-neutral, so building it once under QEMU for each target
# arch of a multi-platform release turns a 30s Vite build into a 60+ minute
# emulated npm install + tsc + bundle. --platform=$BUILDPLATFORM pins the
# stage to the BUILDER's arch; BuildKit will still assemble the final image
# for each $TARGETPLATFORM from the same dist/.
FROM --platform=$BUILDPLATFORM node:20-alpine AS frontend-builder
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
