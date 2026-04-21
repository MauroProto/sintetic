from __future__ import annotations

import base64
import io
import json
import logging
import mimetypes
import time
from pathlib import Path
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

from synthetic_ds.circuit import CircuitBreaker, CircuitOpenError
from synthetic_ds.obs import get_logger, log_event


logger = get_logger("inference")


# Límite conservador de bytes crudos por imagen antes de enviar al LLM.
# OpenAI Vision acepta hasta 20MB; Groq ~5MB; Fireworks ~10MB.
# Usamos 4MB para garantizar compatibilidad entre proveedores.
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_DIMENSION = 1568  # Tamaño "large" de la guía Anthropic/OpenAI


class RetryableInferenceError(RuntimeError):
    """Retryable inference failure."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class PermanentInferenceError(RuntimeError):
    """Fallo permanente: autenticación, schema inválido, parámetros fuera de rango."""


def _downscale_image(data: bytes, *, max_dim: int = MAX_IMAGE_DIMENSION) -> tuple[bytes, str]:
    """Redimensiona una imagen preservando aspecto. Devuelve (bytes, mime).

    Si Pillow no está disponible se devuelve el blob original — garantiza que
    nunca se rompa por una dependencia opcional.
    """
    try:
        from PIL import Image  # pillow
    except ImportError:  # pragma: no cover
        return data, "image/png"

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:  # pragma: no cover
        return data, "image/png"

    original_mode = image.mode
    if original_mode not in ("RGB", "RGBA", "L"):
        image = image.convert("RGB")

    width, height = image.size
    longest = max(width, height)
    if longest > max_dim:
        ratio = max_dim / float(longest)
        image = image.resize((max(1, int(width * ratio)), max(1, int(height * ratio))), Image.LANCZOS)

    buffer = io.BytesIO()
    save_format = "JPEG" if image.mode in ("RGB", "L") else "PNG"
    save_kwargs: dict[str, Any] = {"format": save_format, "optimize": True}
    if save_format == "JPEG":
        save_kwargs.update(quality=88)
    image.save(buffer, **save_kwargs)
    mime = "image/jpeg" if save_format == "JPEG" else "image/png"
    return buffer.getvalue(), mime


class OpenAICompatibleInferenceBackend:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        max_tokens: int,
        temperature: float,
        concurrency: int,
        extra_headers: dict[str, str] | None = None,
        strict_json: bool = True,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.concurrency = concurrency
        self.extra_headers = extra_headers or {}
        self.max_attempts = 6
        self.max_retry_wait = 30.0
        self.retry_backoff_initial = 0.25
        self.retry_backoff_multiplier = 2.0
        self.strict_json = strict_json
        self.circuit = circuit_breaker or CircuitBreaker(name=f"llm:{model.split('/')[-1]}")
        self.client = self._build_client()

    @property
    def circuit_snapshot(self) -> dict:
        return self.circuit.snapshot()

    def _build_client(self) -> OpenAI:
        return OpenAI(api_key=self.api_key, base_url=self.base_url)

    def _invoke(self, payload: dict[str, Any], extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
        request_headers = dict(self.extra_headers)
        if extra_headers:
            request_headers.update(extra_headers)
        self.circuit.before_call()  # Puede elevar CircuitOpenError
        started = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                **payload,
                extra_headers=request_headers or None,
            )
        except RateLimitError as exc:
            self.circuit.on_failure()
            retry_after = None
            if exc.response is not None:
                header = exc.response.headers.get("retry-after")
                if header:
                    try:
                        retry_after = float(header)
                    except ValueError:
                        retry_after = None
            raise RetryableInferenceError(str(exc), retry_after=retry_after) from exc
        except (APIConnectionError, APITimeoutError) as exc:
            self.circuit.on_failure()
            raise RetryableInferenceError(str(exc)) from exc
        except (AuthenticationError, PermissionDeniedError) as exc:
            # No cuenta como "fallo de disponibilidad" para circuit breaker,
            # es problema de credenciales que ningún retry arregla.
            raise PermanentInferenceError(f"auth error: {exc}") from exc
        except BadRequestError as exc:
            # Ídem: problema de payload, no del proveedor.
            raise PermanentInferenceError(f"bad request: {exc}") from exc
        except APIError as exc:
            self.circuit.on_failure()
            raise RetryableInferenceError(str(exc)) from exc

        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        content = response.choices[0].message.content or "{}"
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            self.circuit.on_failure()
            preview = content[:200] if isinstance(content, str) else str(content)[:200]
            log_event(
                logger,
                logging.WARNING,
                "malformed_json_from_llm",
                model=self.model,
                preview=preview,
                exc=str(exc),
            )
            raise RetryableInferenceError(f"malformed JSON: {exc}") from exc

        self.circuit.on_success()
        log_event(
            logger,
            logging.DEBUG,
            "llm_request_ok",
            model=self.model,
            elapsed_ms=elapsed_ms,
            multimodal=isinstance(payload["messages"][-1].get("content"), list),
        )
        return parsed

    def _normalize_user_parts(self, user_parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for part in user_parts:
            part_type = part.get("type")
            if part_type == "image_path":
                image_path = Path(str(part["path"]))
                if not image_path.exists():
                    log_event(
                        logger,
                        logging.WARNING,
                        "image_path_missing",
                        path=str(image_path),
                    )
                    continue
                data = image_path.read_bytes()
                mime_type, _enc = mimetypes.guess_type(image_path.name)
                mime_type = mime_type or "image/png"
                if len(data) > MAX_IMAGE_BYTES or mime_type == "image/png":
                    # PNG suele pesar más que JPEG; re-encodear a JPEG baja mucho
                    data, mime_type = _downscale_image(data)
                if len(data) > MAX_IMAGE_BYTES:
                    log_event(
                        logger,
                        logging.WARNING,
                        "image_too_large_skipped",
                        path=str(image_path),
                        size=len(data),
                    )
                    continue
                encoded = base64.b64encode(data).decode("ascii")
                normalized.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                    }
                )
                continue
            normalized.append(part)
        return normalized

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        session_id: str,
        user_parts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        user_content: str | list[dict[str, Any]] = user_prompt
        if user_parts:
            user_content = self._normalize_user_parts(user_parts)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if self.strict_json:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "synthetic_ds_response",
                    "strict": True,
                    "schema": json_schema,
                },
            }
        else:
            payload["response_format"] = {"type": "json_object"}
        last_error: RetryableInferenceError | None = None
        strict_disabled = False
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self._invoke(payload, extra_headers={"x-session-affinity": session_id})
            except CircuitOpenError as exc:
                # Cooldown: esperamos que se cierre (o caemos al último intento)
                delay = min(self.circuit.cooldown_seconds, self.max_retry_wait)
                log_event(
                    logger,
                    logging.WARNING,
                    "llm_circuit_open_wait",
                    attempt=attempt,
                    delay_s=delay,
                    model=self.model,
                    snapshot=self.circuit_snapshot,
                )
                last_error = RetryableInferenceError(str(exc))
                if attempt >= self.max_attempts:
                    break
                time.sleep(delay)
                continue
            except PermanentInferenceError as exc:
                message = str(exc).lower()
                # Algunos proveedores (Groq, OpenRouter) no soportan strict=true;
                # detectamos el error y caemos a json_object para el resto de la corrida.
                if (
                    self.strict_json
                    and not strict_disabled
                    and ("response_format" in message or "strict" in message or "schema" in message)
                ):
                    log_event(
                        logger,
                        logging.WARNING,
                        "strict_json_not_supported_fallback",
                        model=self.model,
                    )
                    self.strict_json = False
                    payload["response_format"] = {"type": "json_object"}
                    strict_disabled = True
                    continue
                raise
            except RetryableInferenceError as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    break
                delay = (
                    exc.retry_after
                    if exc.retry_after is not None
                    else min(
                        self.retry_backoff_initial * (self.retry_backoff_multiplier ** (attempt - 1)),
                        self.max_retry_wait,
                    )
                )
                log_event(
                    logger,
                    logging.WARNING,
                    "llm_retry",
                    attempt=attempt,
                    delay_s=round(delay, 2),
                    model=self.model,
                    exc=str(exc)[:200],
                )
                time.sleep(delay)
        assert last_error is not None
        raise last_error


class FireworksInferenceBackend(OpenAICompatibleInferenceBackend):
    pass
