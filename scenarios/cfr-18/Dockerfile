FROM python:3.12-slim
WORKDIR /app
COPY services /app/services
COPY ci /app/ci
COPY tests /app/tests
RUN mkdir -p /data
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
