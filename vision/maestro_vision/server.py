import os
import secrets
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException


HOST = "127.0.0.1"


def create_app(session_token: str) -> FastAPI:
    if not session_token:
        raise ValueError("session token must not be empty")

    async def authenticate(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {session_token}"
        if authorization is None or not secrets.compare_digest(
            authorization.encode(), expected.encode()
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid session token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    app = FastAPI(
        dependencies=[Depends(authenticate)],
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def main() -> None:
    port = int(os.environ["MAESTRO_VISION_PORT"])
    if not 0 < port < 65536:
        raise ValueError("MAESTRO_VISION_PORT must be between 1 and 65535")
    uvicorn.run(create_app(os.environ["MAESTRO_VISION_SESSION_TOKEN"]), host=HOST, port=port)
