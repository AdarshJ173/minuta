FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src/ ./src/
COPY migrations/ ./migrations/
ENV PYTHONPATH=/srv/src
CMD ["uvicorn", "minuta.api:app", "--host", "0.0.0.0", "--port", "8080"]
