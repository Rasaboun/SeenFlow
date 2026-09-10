from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from seenflow import server
from seenflow.server import create_app


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


def test_server_startup_passes_localhost_to_uvicorn(monkeypatch) -> None:
    sidecar = app()
    run = Mock()
    monkeypatch.setenv("SEENFLOW_PORT", "43210")
    monkeypatch.setenv("SEENFLOW_SESSION_TOKEN", TOKEN)
    monkeypatch.setattr(server, "create_app", Mock(return_value=sidecar))
    monkeypatch.setattr(server.uvicorn, "run", run)

    server.main()

    run.assert_called_once_with(sidecar, host="127.0.0.1", port=43210)


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
