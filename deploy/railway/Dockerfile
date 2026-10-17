# Build the UI once, serve static files without a Node server at runtime.
FROM node:22-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ENV NEXT_PUBLIC_API_URL=/api STUDIO_STATIC_EXPORT=1 NEXT_TELEMETRY_DISABLED=1
RUN npm run build -- --no-lint

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak-ng fonts-dejavu-core nginx supervisor && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt
COPY backend/app ./app
COPY --from=frontend /frontend/out /srv/lecture-ui
COPY deploy/railway/nginx.conf /etc/nginx/nginx.conf
COPY deploy/railway/supervisord.conf /etc/supervisor/lecture.conf
COPY deploy/railway/start.py /app/start.py
ENV STORAGE_ROOT=/data PORT=8080 MAX_UPLOAD_BYTES=52428800 MAX_LECTURE_SECONDS=120 MAX_LECTURES=1
EXPOSE 8080
CMD ["python", "/app/start.py"]
