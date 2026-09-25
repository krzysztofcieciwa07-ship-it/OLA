FROM python:3.12-slim
WORKDIR /app
COPY scenarios/cfr-18/services /app/services
COPY scenarios/cfr-18/ci /app/ci
COPY scenarios/cfr-18/tests /app/tests
RUN mkdir -p /data
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
