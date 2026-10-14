# --- Build the React app ---------------------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Django API + static SPA ----------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=false \
    FRONTEND_DIST=/app/frontend/dist \
    PORT=8000
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist
EXPOSE 8000
# One process with threads: the in-memory cache (routes, forecasts) is shared
# by all requests, and requests mostly wait on third-party APIs.
CMD gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} \
    --workers 1 --worker-class gthread --threads 16 --timeout 180
