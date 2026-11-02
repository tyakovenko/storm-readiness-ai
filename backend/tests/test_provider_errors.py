"""Provider failures use a stable API contract and never expose provider details."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import NoReturn

import httpx
import litellm
import pytest
from agent import adk_runner, dallas_adk
from agent.llm import LiteLLMClient
from agent.provider_errors import ModelProviderError, normalize_provider_error
from fastapi.testclient import TestClient
from google.genai.errors import ClientError


def _genai_error(status: int, retry_after: str | None = None) -> ClientError:
    response = (
        httpx.Response(status, headers={"Retry-After": retry_after})
        if retry_after
        else None
    )
    return ClientError(
        status,
        {
            "error": {
                "code": status,
                "status": "PROVIDER_FAILURE",
                "message": "private provider detail",
            }
        },
        response,
    )


@pytest.mark.parametrize(
    ("provider_error", "status_code", "expected_body"),
    [
        (
            _genai_error(429, "17"),
            503,
            {"error": "model_quota_exhausted", "retry_after": 17},
        ),
        (_genai_error(401), 502, {"error": "model_unavailable"}),
        (_genai_error(403), 502, {"error": "model_unavailable"}),
        (httpx.ReadTimeout("provider timed out"), 504, {"error": "model_timeout"}),
        (RuntimeError("internal failure"), 500, None),
    ],
)
def test_chat_returns_safe_provider_error(
    monkeypatch: pytest.MonkeyPatch,
    provider_error: Exception,
    status_code: int,
    expected_body: dict[str, object] | None,
) -> None:
    import backend.app as app_module

    async def fail_request(*_args: object, **_kwargs: object) -> NoReturn:
        raise provider_error

    @asynccontextmanager
    async def no_lifespan(_app: object) -> AsyncIterator[None]:
        yield

    monkeypatch.setattr(app_module, "DOMAIN", "dallas")
    monkeypatch.setattr(dallas_adk, "entity_catalog", list)
    monkeypatch.setattr(adk_runner, "_run", fail_request)
    monkeypatch.setattr(app_module.app.router, "lifespan_context", no_lifespan)
    monkeypatch.setattr(
        app_module.app.state, "agent", SimpleNamespace(model="test"), raising=False
    )
    monkeypatch.setattr(app_module.app.state, "judge", None, raising=False)

    response = TestClient(app_module.app, raise_server_exceptions=False).post(
        "/api/chat", json={"message": "What should we do?"}
    )

    assert response.status_code == status_code, response.text
    if expected_body is None:
        assert "internal failure" not in response.text
        return
    assert response.json() == expected_body
    assert "private provider detail" not in response.text
    if status_code == 503:
        assert response.headers["retry-after"] == "17"


def test_unknown_exception_is_not_misreported_as_provider_failure() -> None:
    assert normalize_provider_error(RuntimeError("internal failure")) is None
    assert normalize_provider_error(TimeoutError("internal timeout")) is None


def test_litellm_boundary_normalizes_provider_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error_type = type(
        "RateLimitError", (Exception,), {"__module__": "litellm.exceptions"}
    )
    provider_error = error_type("private provider detail")
    provider_error.status_code = 429

    def fail_completion(**_kwargs: object) -> NoReturn:
        raise provider_error

    monkeypatch.setattr(litellm, "completion", fail_completion)
    client = LiteLLMClient("test-model")

    with pytest.raises(ModelProviderError) as raised:
        client.complete([], [])

    assert raised.value.code == "model_quota_exhausted"
    assert raised.value.status_code == 503


def test_litellm_boundary_normalizes_builtin_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_completion(**_kwargs: object) -> NoReturn:
        raise TimeoutError("provider timed out")

    monkeypatch.setattr(litellm, "completion", fail_completion)
    client = LiteLLMClient("test-model")

    with pytest.raises(ModelProviderError) as raised:
        client.complete([], [])

    assert raised.value.code == "model_timeout"
    assert raised.value.status_code == 504
