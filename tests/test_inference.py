from collections.abc import Callable

from synthetic_ds.inference import FireworksInferenceBackend, RetryableInferenceError


class DummyBackend(FireworksInferenceBackend):
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        super().__init__(
            api_key="test",
            base_url="https://api.fireworks.ai/inference/v1",
            model="accounts/fireworks/routers/kimi-k2p5-turbo",
            max_tokens=512,
            temperature=0.2,
            concurrency=1,
        )

    def _build_client(self) -> object:
        return object()

    def _invoke(self, payload: dict, extra_headers: dict[str, str] | None = None) -> dict:
        attempt = str(len(self._calls) + 1)
        self._calls.append(attempt)
        if len(self._calls) < 3:
            raise RetryableInferenceError("rate limited")
        return {"question": "hola"}


def test_inference_backend_retries_retryable_errors() -> None:
    calls: list[str] = []
    backend = DummyBackend(calls)

    result = backend.generate_structured(
        system_prompt="system",
        user_prompt="user",
        json_schema={"type": "object"},
        session_id="run-1",
    )

    assert result == {"question": "hola"}
    assert len(calls) == 3


class ExtendedRetryBackend(FireworksInferenceBackend):
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        super().__init__(
            api_key="test",
            base_url="https://api.fireworks.ai/inference/v1",
            model="accounts/fireworks/routers/kimi-k2p5-turbo",
            max_tokens=512,
            temperature=0.2,
            concurrency=1,
        )

    def _build_client(self) -> object:
        return object()

    def _invoke(self, payload: dict, extra_headers: dict[str, str] | None = None) -> dict:
        attempt = str(len(self._calls) + 1)
        self._calls.append(attempt)
        if len(self._calls) < 6:
            raise RetryableInferenceError("rate limited")
        return {"question": "hola"}


def test_inference_backend_supports_longer_retries_for_rate_limits() -> None:
    calls: list[str] = []
    backend = ExtendedRetryBackend(calls)

    result = backend.generate_structured(
        system_prompt="system",
        user_prompt="user",
        json_schema={"type": "object"},
        session_id="run-2",
    )

    assert result == {"question": "hola"}
    assert len(calls) == 6
