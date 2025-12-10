# syntax=docker/dockerfile:1

# API container: serves the FastAPI backend and static files directly
FROM python:3.11-slim AS api

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install production dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . /app

# Expose the FastAPI/uvicorn port
EXPOSE 8000

# Start the web server (serves static frontend from /app/frontend as well)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# Frontend-only container: serves static HTML/JS via nginx
FROM nginx:alpine AS frontend

# Replace the default nginx static assets with the project's frontend
COPY frontend/ /usr/share/nginx/html/

EXPOSE 80
