"""FastAPI service entrypoint."""

from fastapi import FastAPI
from pydantic import BaseModel

from control_plane import __version__
from control_plane.config import Settings


class Health(BaseModel):
    status: str
    version: str


class Status(BaseModel):
    environment: str
    aws_bedrock_enabled: bool
    aws_session_budget_usd: str


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    app = FastAPI(title="Adaptive AI Inference Control Plane", version=__version__)

    @app.get("/health/live", response_model=Health, tags=["health"])
    async def live() -> Health:
        return Health(status="alive", version=__version__)

    @app.get("/health/ready", response_model=Health, tags=["health"])
    async def ready() -> Health:
        return Health(status="ready", version=__version__)

    @app.get("/v1/system/status", response_model=Status, tags=["system"])
    async def status() -> Status:
        return Status(
            environment=config.environment,
            aws_bedrock_enabled=config.aws_bedrock_enabled,
            aws_session_budget_usd=str(config.aws_session_budget_usd),
        )

    return app


app = create_app()
