from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import routes_climatology, routes_health, routes_optimize, routes_simulate
from .config import settings


def create_app() -> FastAPI:
    app = FastAPI(title="Falling-position-simulator Backend", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(routes_health.router)
    app.include_router(routes_simulate.router)
    app.include_router(routes_optimize.router)
    app.include_router(routes_climatology.router)
    return app


app = create_app()
