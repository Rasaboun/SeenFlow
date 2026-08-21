import pytest
from fastapi.testclient import TestClient

from maestro_vision.server import HOST, create_app


TOKEN = "test-session-token"


def app():
    return create_app(TOKEN, lambda: object())


def test_health_accepts_the_session_token() -> None:
    response = TestClient(app()).get(
        "/v1/health", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("authorization", [None, "Bearer wrong-token"])
def test_health_rejects_missing_or_invalid_tokens(authorization: str | None) -> None:
    headers = {"Authorization": authorization} if authorization else {}

    response = TestClient(app()).get("/v1/health", headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_empty_session_tokens_are_rejected() -> None:
    with pytest.raises(ValueError, match="session token"):
        create_app("", lambda: object())


def test_server_binds_to_localhost_only() -> None:
    assert HOST == "127.0.0.1"


def test_sidecar_initializes_one_ocr_provider_at_startup() -> None:
    provider = object()
    calls = 0

    def factory():
        nonlocal calls
        calls += 1
        return provider

    sidecar = create_app(TOKEN, factory)

    assert calls == 1
    assert sidecar.state.ocr_provider is provider
