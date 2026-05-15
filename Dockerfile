FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libgl1 libglib2.0-0 libgomp1 curl ca-certificates bash \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY src ./src
COPY scripts ./scripts
COPY docs ./docs
COPY *.md ./
RUN chmod +x /app/scripts/railway_start.sh /app/scripts/local_dev.sh || true

EXPOSE 8080
CMD ["/app/scripts/railway_start.sh"]
