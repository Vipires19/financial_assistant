# Dockerfile da aplicação principal - usado também por celery_worker e celery_beat
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Porta padrão da aplicação web (Gunicorn)
EXPOSE 8000

# Comando padrão (sobrescrito no docker-compose para web, celery_worker, celery_beat)
CMD ["gunicorn", "dashboard.wsgi:application", "--bind", "0.0.0.0:8000"]
