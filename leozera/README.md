# Leozera 2.0

Fundação técnica: FastAPI, Next.js, PostgreSQL e Docker. Sem módulos financeiros nesta fase.

## Ambiente

```bash
cd leozera
cp .env.example .env
```

O `.env.example` já traz valores locais. Eles não são segredos de produção.

## Subir

A migration não roda junto com a API. Execute nesta ordem, com o Docker no ar:

```bash
docker compose up -d postgres
docker compose run --rm backend alembic upgrade head
docker compose up -d backend frontend
```

- Interface: http://localhost:3000
- API direta, só no desenvolvimento: http://localhost:8000
- O browser usa `/api`, encaminhado pelo Next.js ao backend.

Produção, sem publicar o PostgreSQL nem a API:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d postgres
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build backend frontend
```

Defina `ENVIRONMENT=production`, `CORS_ORIGINS` e `FRONTEND_ORIGIN` com a origem pública. Cookies saem com `Secure`.

## Testes

```bash
docker compose run --rm backend pytest
```

Os testes usam o PostgreSQL do Compose, no banco `leozera_test`.

Se um antivírus interceptar HTTPS, o build do Docker falha ao validar o certificado de PyPI ou do npm. Neste caso, o `.env` local pode definir `PIP_EXTRA_ARGS=--trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org` e `NPM_CONFIG_STRICT_SSL=false`. Esses valores não entram no `.env.example`.
