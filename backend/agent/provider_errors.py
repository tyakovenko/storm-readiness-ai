"""Translate known model-provider failures into safe, stable API errors."""

from __future__ import annotations

import logging
import math
from collections.abc import Iterator, Mapping

log = logging.getLogger(__name__)

_PROVIDER_MODULES = (
    "google.genai",
    "google.api_core",
    "litellm",
    "openai",
    "anthropic",
)


class ModelProviderError(Exception):
    def __init__(
        self, code: str, status_code: int, retry_after: int | None = None
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(code)


def _exception_chain(error: Exception) -> Iterator[Exception]:
    seen: set[int] = set()
    current: BaseException | None = error
    while isinstance(current, Exception) and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _status_code(error: Exception) -> int | None:
    status_names = {
        "RESOURCE_EXHAUSTED": 429,
        "UNAUTHENTICATED": 401,
        "PERMISSION_DENIED": 403,
    }
    for value in (
        getattr(error, "status_code", None),
        getattr(error, "code", None),
        getattr(error, "status", None),
        getattr(getattr(error, "response", None), "status_code", None),
    ):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if value is not None:
            name = str(value).rsplit(".", 1)[-1].upper()
            if name in status_names:
                return status_names[name]
    return None


def _retry_after(error: Exception) -> int | None:
    value = getattr(error, "retry_after", None)
    if value is None:
        headers = getattr(getattr(error, "response", None), "headers", None)
        if isinstance(headers, Mapping):
            value = headers.get("Retry-After") or headers.get("retry-after")
    if value is None:
        return None
    try:
        seconds = math.ceil(float(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return seconds if seconds >= 0 else None


def normalize_provider_error(
    error: Exception, *, allow_builtin_timeout: bool = False
) -> ModelProviderError | None:
    for cause in _exception_chain(error):
        name = type(cause).__name__.lower()
        module = type(cause).__module__
        provider_error = module.startswith(_PROVIDER_MODULES)
        is_timeout = "timeout" in name or "deadlineexceeded" in name
        if is_timeout and (
            provider_error
            or module.startswith("httpx")
            or (allow_builtin_timeout and isinstance(cause, TimeoutError))
        ):
            failure = ModelProviderError("model_timeout", 504)
        elif provider_error:
            status = _status_code(cause)
            if status == 429:
                failure = ModelProviderError(
                    "model_quota_exhausted", 503, _retry_after(cause)
                )
            elif status in (401, 403):
                failure = ModelProviderError("model_unavailable", 502)
            else:
                failure = ModelProviderError("model_unavailable", 502)
        else:
            continue

        log.error("Model provider request failed (%s): %s", failure.code, cause)
        return failure
    return None
