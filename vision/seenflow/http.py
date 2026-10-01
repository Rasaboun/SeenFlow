"""HTTP input validation and presentation; no concrete device/OCR adapters."""
import secrets
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from seenflow.application import contracts
from seenflow.application.errors import CaptureFailed, RunContextMissing, VisualError
from seenflow.application.visual import VisualService
from seenflow.serialization import find_result_json, item_json

MAX_REQUEST_BYTES = 16_384


class DetectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    platform: Literal["ios", "android"]
    device_id: str = Field(alias="deviceId", pattern=r"^[A-Za-z0-9._:-]{1,128}$")


class AnchorSelector(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1)
    match: Literal["exact", "contains", "fuzzy"] = "exact"
    threshold: float = Field(default=0.85, ge=0, le=1)
    occurrence: int = Field(default=0, ge=0)

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


class SpatialSelector(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    relation: Literal["near", "above", "below", "leftOf", "rightOf"]
    anchor: AnchorSelector
    max_distance: float = Field(alias="maxDistance", gt=0, le=100)


class VisualCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1)
    state: Literal["visible", "not-visible"]

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


class FindRequest(DetectRequest):
    text: str = Field(min_length=1)
    match: Literal["exact", "contains", "fuzzy"] = "exact"
    threshold: float = Field(default=0.85, ge=0, le=1)
    occurrence: int = Field(default=0, ge=0)
    spatial: SpatialSelector | None = None
    precondition: VisualCondition | None = None
    diagnostics: bool = False
    context: Literal["target", "precondition", "postcondition"] | None = None
    state: Literal["visible", "not-visible"] | None = None
    attempt: int | None = Field(default=None, ge=1)
    run_id: str | None = Field(
        default=None,
        alias="runId",
        pattern=r"^[A-Za-z0-9_-]{1,64}$",
    )
    step: int | None = Field(default=None, ge=1)
    action: str | None = Field(default=None, min_length=1, max_length=512)

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value

    @field_validator("action")
    @classmethod
    def reject_blank_action(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("action must not be blank")
        return value

    @model_validator(mode="after")
    def require_complete_journal_context(self) -> "FindRequest":
        values = (self.run_id, self.step, self.action)
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError("runId, step, and action must be provided together")
        if self.run_id is not None and (self.context is None or self.attempt is None):
            raise ValueError("journaled requests require context and attempt")
        return self


class FinalDiagnosticRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    run_id: str = Field(alias="runId", pattern=r"^[A-Za-z0-9_-]{1,64}$")


def application_request(request: FindRequest) -> contracts.FindText:
    values = request.model_dump(exclude={"spatial", "precondition"})
    spatial = request.spatial
    return contracts.FindText(
        **values,
        spatial=contracts.SpatialSelector(
            spatial.relation,
            contracts.TextSelector(**spatial.anchor.model_dump()),
            spatial.max_distance,
        ) if spatial else None,
        precondition=contracts.VisualCondition(**request.precondition.model_dump()) if request.precondition else None,
    )


def create_http_app(session_token: str, service: VisualService) -> FastAPI:
    if not session_token:
        raise ValueError("session token must not be empty")

    async def authenticate(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {session_token}"
        if authorization is None or not secrets.compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="Invalid session token", headers={"WWW-Authenticate": "Bearer"})

    app = FastAPI(dependencies=[Depends(authenticate)], docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(VisualError)
    async def application_failure(_request: Request, error: VisualError):
        if isinstance(error, RunContextMissing):
            return JSONResponse(status_code=404, content={"detail": str(error)})
        detail = {"code": error.code, "message": str(error)}
        if error.artifacts is not None:
            detail["artifacts"] = error.artifacts
        return JSONResponse(status_code=502 if isinstance(error, CaptureFailed) else 500, content={"detail": detail})

    @app.middleware("http")
    async def limit_request_body(request: Request, call_next):
        body = await request.body()
        if len(body) > MAX_REQUEST_BYTES:
            return JSONResponse(status_code=413, content={"detail": "Request body too large"})
        request._body = body
        return await call_next(request)

    @app.get("/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/text/detect")
    async def detect(request: DetectRequest) -> dict[str, object]:
        result = service.detect(request.platform, request.device_id)
        return {"width": result.width, "height": result.height, "items": [item_json(item) for item in result.items]}

    @app.post("/v1/text/find")
    async def find(request: FindRequest) -> dict[str, object]:
        return find_result_json(service.find(application_request(request)))

    @app.post("/v1/diagnostics/final")
    async def final_diagnostic(request: FinalDiagnosticRequest) -> dict[str, object]:
        return {"artifacts": service.final_diagnostic(request.run_id)}

    return app
