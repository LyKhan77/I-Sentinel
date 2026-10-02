FROM python:3.12-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY backend/ /app/
RUN pip install --no-cache-dir -e "/app[face]"

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
ENV PATH=/opt/venv/bin:$PATH HOME=/tmp PYTHONUNBUFFERED=1
WORKDIR /app
COPY --chmod=755 docker/backend/entrypoint.sh /entrypoint.sh
USER 1000:1000
EXPOSE 7701
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7701"]
