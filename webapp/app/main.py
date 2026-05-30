"""FastAPI app factory."""

from __future__ import annotations

from fastapi import FastAPI

from app.routes import account_routes, auth_routes


def create_app() -> FastAPI:
    app = FastAPI(title="Google Ads Agents - web backend")
    app.include_router(auth_routes.router)
    app.include_router(account_routes.router)
    return app


app = create_app()
