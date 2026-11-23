FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY alembic ./alembic
COPY tests ./tests

ARG PIP_EXTRA_ARGS=""
RUN pip install --no-cache-dir $PIP_EXTRA_ARGS .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
