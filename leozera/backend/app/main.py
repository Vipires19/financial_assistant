from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import accounts, auth, categories, health, payables, summary, transactions, transfers
from app.auth.csrf import origin_is_allowed
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging

configure_logging()
settings = get_settings()

app = FastAPI(title="Leozera", version="2.0.0")
register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Content-Type", "Idempotency-Key", "X-CSRF-Token"],
)


@app.middleware("http")
async def enforce_origin(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not origin_is_allowed(request):
        return JSONResponse(status_code=403, content={"detail": "Origem não permitida."})
    return await call_next(request)


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(categories.router)
app.include_router(transactions.router)
app.include_router(transfers.router)
app.include_router(summary.router)
app.include_router(payables.router)
