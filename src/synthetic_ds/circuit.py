"""Circuit breaker con ventana deslizante para proveedores LLM.

Estados:
    closed    → normal, todas las calls pasan
    open      → rechaza inmediato durante ``cooldown_seconds`` tras X fallos
    half_open → deja pasar 1 call de prueba; si pasa → closed, si falla → open

Diseñado para la corrida masiva: si un proveedor empieza a tirar 429/503/500
arriba de un umbral (50% por defecto en los últimos 20 llamados), se abre el
circuito por 30s. Evita saturar al proveedor y darle tiempo de recuperarse.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Deque

from synthetic_ds.obs import get_logger, log_event


logger = get_logger("circuit")


class CircuitOpenError(RuntimeError):
    """Se intenta llamar con el circuito abierto."""


class CircuitBreaker:
    def __init__(
        self,
        *,
        name: str,
        window_size: int = 20,
        failure_threshold: float = 0.5,
        min_calls: int = 5,
        cooldown_seconds: float = 30.0,
        success_threshold: int = 2,
    ) -> None:
        self.name = name
        self.window_size = window_size
        self.failure_threshold = failure_threshold
        self.min_calls = min_calls
        self.cooldown_seconds = cooldown_seconds
        self.success_threshold = success_threshold
        self._window: Deque[bool] = deque(maxlen=window_size)
        self._state: str = "closed"
        self._opened_at: float | None = None
        self._half_open_successes: int = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        return self._state

    def snapshot(self) -> dict[str, float | int | str]:
        with self._lock:
            total = len(self._window)
            failures = sum(1 for ok in self._window if not ok)
            return {
                "name": self.name,
                "state": self._state,
                "window_size": total,
                "failures": failures,
                "failure_rate": round(failures / total, 3) if total else 0.0,
                "cooldown_remaining_s": round(
                    max(0.0, (self._opened_at or 0.0) + self.cooldown_seconds - time.time()), 2
                )
                if self._state == "open"
                else 0.0,
            }

    def before_call(self) -> None:
        with self._lock:
            if self._state == "open":
                elapsed = time.time() - (self._opened_at or 0.0)
                if elapsed >= self.cooldown_seconds:
                    self._state = "half_open"
                    self._half_open_successes = 0
                    log_event(logger, logging.INFO, "circuit_half_open", name=self.name)
                else:
                    raise CircuitOpenError(
                        f"circuit '{self.name}' open for {self.cooldown_seconds - elapsed:.0f}s more"
                    )

    def on_success(self) -> None:
        with self._lock:
            self._window.append(True)
            if self._state == "half_open":
                self._half_open_successes += 1
                if self._half_open_successes >= self.success_threshold:
                    self._state = "closed"
                    self._window.clear()
                    self._opened_at = None
                    log_event(logger, logging.INFO, "circuit_closed", name=self.name)
            elif self._state == "open":
                # Recuperación inesperada (no debería pasar)
                self._state = "closed"
                self._window.clear()
                self._opened_at = None

    def on_failure(self) -> None:
        with self._lock:
            self._window.append(False)
            if self._state == "half_open":
                self._trip_open()
                return
            if self._state == "closed" and len(self._window) >= self.min_calls:
                failures = sum(1 for ok in self._window if not ok)
                rate = failures / len(self._window)
                if rate >= self.failure_threshold:
                    self._trip_open()

    def _trip_open(self) -> None:
        self._state = "open"
        self._opened_at = time.time()
        log_event(
            logger,
            logging.WARNING,
            "circuit_opened",
            name=self.name,
            cooldown_s=self.cooldown_seconds,
            sample=list(self._window),
        )
