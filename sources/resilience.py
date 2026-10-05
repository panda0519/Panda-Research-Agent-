"""Shared resilience wrapper: Circuit breaker (trip on 3 consecutive 5xx/timeouts) and 429 exponential backoff."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar, Union

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Global registry of circuit breakers by service name
_CIRCUIT_BREAKERS: Dict[str, "CircuitBreaker"] = {}


class CircuitBreakerOpenError(Exception):
    """Raised when a request is attempted against an open circuit breaker."""

    def __init__(self, service_name: str, failure_count: int, reason: str = ""):
        self.service_name = service_name
        self.failure_count = failure_count
        self.reason = reason
        super().__init__(
            f"Circuit breaker is OPEN for service '{service_name}' ({failure_count} consecutive failures). Request blocked. {reason}".strip()
        )


class CircuitBreaker:
    """Tracks consecutive failures (5xx or timeouts) and trips if threshold is reached."""

    def __init__(
        self,
        service_name: str,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failure_count: int = 0
        self.is_tripped: bool = False
        self.last_failure_reason: Optional[str] = None
        self.last_failure_time: Optional[float] = None
        self.total_failures: int = 0
        self.total_successes: int = 0

    def record_success(self) -> None:
        """Records a successful operation, resetting consecutive failure count and closing circuit."""
        if self.is_tripped:
            logger.info("Circuit breaker for service '%s' RESET to CLOSED on successful response.", self.service_name)
        self.failure_count = 0
        self.is_tripped = False
        self.last_failure_reason = None
        self.total_successes += 1

    def record_failure(self, reason: str = "") -> None:
        """Records a 5xx server error or timeout. Trips circuit if threshold reached."""
        self.failure_count += 1
        self.total_failures += 1
        self.last_failure_reason = reason
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold and not self.is_tripped:
            self.is_tripped = True
            logger.warning(
                "Circuit breaker TRIPPED for service '%s' after %d consecutive failures. Reason: %s",
                self.service_name,
                self.failure_count,
                reason,
            )

    def can_execute(self) -> bool:
        """Returns True if the circuit allows execution."""
        if not self.is_tripped:
            return True
        if self.last_failure_time and (time.time() - self.last_failure_time) > self.cooldown_seconds:
            logger.info("Circuit breaker cooldown elapsed for '%s'. Allowing probe request.", self.service_name)
            return True
        return False

    def reset(self) -> None:
        """Explicitly resets the circuit breaker to closed state."""
        self.failure_count = 0
        self.is_tripped = False
        self.last_failure_reason = None
        self.last_failure_time = None


def get_circuit_breaker(service_name: str, failure_threshold: int = 3, cooldown_seconds: float = 60.0) -> CircuitBreaker:
    """Retrieves or creates a named circuit breaker singleton."""
    if service_name not in _CIRCUIT_BREAKERS:
        _CIRCUIT_BREAKERS[service_name] = CircuitBreaker(
            service_name=service_name,
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )
    return _CIRCUIT_BREAKERS[service_name]




async def execute_resilient_async(
    service_name: str,
    request_func: Callable[[], Any],
    max_429_retries: int = 2,
    initial_backoff: float = 1.0,
    backoff_factor: float = 2.0,
    circuit_breaker: Optional[CircuitBreaker] = None,
) -> Any:
    """Asynchronously executes an HTTP request with circuit breaker protection and 429 exponential backoff."""
    cb = circuit_breaker or get_circuit_breaker(service_name)

    if not cb.can_execute():
        logger.warning(
            "Skipping request to '%s': Circuit breaker is OPEN (%d consecutive failures: %s)",
            service_name,
            cb.failure_count,
            cb.last_failure_reason,
        )
        return None

    attempt = 0
    while attempt <= max_429_retries:
        try:
            resp = await request_func()
            if resp is None:
                return None

            status_code = getattr(resp, "status_code", 200)

            # Handle 429 Rate Limit with exponential backoff
            if status_code == 429:
                if attempt < max_429_retries:
                    delay = initial_backoff * (backoff_factor ** attempt)
                    retry_after = getattr(resp, "headers", {}).get("Retry-After")
                    if retry_after:
                        try:
                            delay = max(delay, float(retry_after))
                        except (ValueError, TypeError):
                            pass
                    logger.warning(
                        "Rate limited (429) by '%s'. Backing off for %.2fs (attempt %d/%d)...",
                        service_name,
                        delay,
                        attempt + 1,
                        max_429_retries,
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                else:
                    logger.warning("Rate limit (429) retries exhausted for '%s'.", service_name)
                    return resp

            # Handle 5xx Server Errors
            if 500 <= status_code < 600:
                cb.record_failure(f"HTTP {status_code}")
                return resp

            # Successful response
            cb.record_success()
            return resp

        except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
            cb.record_failure(f"Timeout: {type(exc).__name__}")
            logger.warning("Request to '%s' timed out (failure count: %d)", service_name, cb.failure_count)
            return None
        except httpx.ConnectError as exc:
            cb.record_failure(f"ConnectError: {exc}")
            logger.warning("Connection error to '%s': %s (failure count: %d)", service_name, exc, cb.failure_count)
            return None
        except Exception as exc:
            logger.warning("Request to '%s' failed unexpectedly: %s", service_name, exc)
            return None

    return None


def execute_resilient_sync(
    service_name: str,
    request_func: Callable[[], Any],
    max_429_retries: int = 2,
    initial_backoff: float = 1.0,
    backoff_factor: float = 2.0,
    circuit_breaker: Optional[CircuitBreaker] = None,
) -> Any:
    """Synchronously executes an HTTP request with circuit breaker protection and 429 exponential backoff."""
    cb = circuit_breaker or get_circuit_breaker(service_name)

    if not cb.can_execute():
        logger.warning(
            "Skipping sync request to '%s': Circuit breaker is OPEN (%d consecutive failures: %s)",
            service_name,
            cb.failure_count,
            cb.last_failure_reason,
        )
        return None

    attempt = 0
    while attempt <= max_429_retries:
        try:
            resp = request_func()
            if resp is None:
                return None

            status_code = getattr(resp, "status_code", 200)

            # Handle 429 Rate Limit
            if status_code == 429:
                if attempt < max_429_retries:
                    delay = initial_backoff * (backoff_factor ** attempt)
                    retry_after = getattr(resp, "headers", {}).get("Retry-After")
                    if retry_after:
                        try:
                            delay = max(delay, float(retry_after))
                        except (ValueError, TypeError):
                            pass
                    logger.warning(
                        "Rate limited (429) by '%s'. Backing off for %.2fs (attempt %d/%d)...",
                        service_name,
                        delay,
                        attempt + 1,
                        max_429_retries,
                    )
                    time.sleep(delay)
                    attempt += 1
                    continue
                else:
                    logger.warning("Rate limit (429) retries exhausted for '%s'.", service_name)
                    return resp

            # Handle 5xx Server Errors
            if 500 <= status_code < 600:
                cb.record_failure(f"HTTP {status_code}")
                return resp

            cb.record_success()
            return resp

        except httpx.TimeoutException as exc:
            cb.record_failure(f"Timeout: {type(exc).__name__}")
            logger.warning("Sync request to '%s' timed out (failure count: %d)", service_name, cb.failure_count)
            return None
        except httpx.ConnectError as exc:
            cb.record_failure(f"ConnectError: {exc}")
            logger.warning("Connection error to '%s': %s (failure count: %d)", service_name, exc, cb.failure_count)
            return None
        except Exception as exc:
            logger.warning("Sync request to '%s' failed unexpectedly: %s", service_name, exc)
            return None

    return None

def reset_all_circuit_breakers() -> None:
    """Resets all registered circuit breakers."""
    for cb in _CIRCUIT_BREAKERS.values():
        cb.reset()
