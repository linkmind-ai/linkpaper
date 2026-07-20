from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from linkpaper.api.router import api_router
from linkpaper.core.config import settings
from linkpaper.core.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()

