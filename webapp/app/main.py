"""FastAPI app factory."""

from __future__ import annotations

from fastapi import Depends, FastAPI

from app.csrf import require_same_origin
from app.routes import account_routes, auth_routes, signin_routes


def create_app() -> FastAPI:
    app = FastAPI(title="Google Ads Agents - web backend",
                  dependencies=[Depends(require_same_origin)])
    app.include_router(signin_routes.router)
    app.include_router(auth_routes.router)
    app.include_router(account_routes.router)
    return app


app = create_app()
