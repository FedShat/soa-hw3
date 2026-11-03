import asyncio
import logging
import time
from collections import deque

import grpc

logger = logging.getLogger(__name__)
TRANSIENT_CODES = {grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED}


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    def __init__(self, threshold, reset_timeout, window, clock=time.monotonic):
        self.threshold = threshold
        self.reset_timeout = reset_timeout
        self.window = window
        self.clock = clock
        self.state = "CLOSED"
        self.failures = deque()
        self.opened_at = 0.0
        self.generation = 0

    def transition(self, state):
        logger.warning("circuit breaker %s -> %s", self.state, state)
        self.state = state
        self.generation += 1
        if state == "OPEN":
            self.opened_at = self.clock()

    def acquire(self):
        if self.state == "OPEN":
            if self.clock() - self.opened_at < self.reset_timeout:
                raise CircuitOpenError("Flight Service is temporarily unavailable; try again later")
            self.transition("HALF_OPEN")
            return self.generation
        if self.state == "HALF_OPEN":
            raise CircuitOpenError("Flight Service recovery check is in progress")
        return self.generation

    def success(self, generation):
        if generation != self.generation:
            return
        self.failures.clear()
        if self.state == "HALF_OPEN":
            self.transition("CLOSED")

    def failure(self, generation):
        if generation != self.generation:
            return
        now = self.clock()
        self.failures.append(now)
        while self.failures and now - self.failures[0] > self.window:
            self.failures.popleft()
        if self.state == "HALF_OPEN" or len(self.failures) >= self.threshold:
            self.transition("OPEN")


class ResilienceInterceptor(grpc.aio.UnaryUnaryClientInterceptor):
    def __init__(self, settings):
        self.api_key = settings.grpc_api_key.get_secret_value()
        self.timeout = settings.grpc_timeout
        self.max_attempts = settings.grpc_max_attempts
        self.backoff = settings.grpc_retry_backoff
        self.breaker = CircuitBreaker(
            settings.circuit_failure_threshold,
            settings.circuit_reset_timeout,
            settings.circuit_window,
        )

    async def intercept_unary_unary(self, continuation, client_call_details, request):
        generation = self.breaker.acquire()
        attempts = 1 if self.breaker.state == "HALF_OPEN" else self.max_attempts
        details = grpc.aio.ClientCallDetails(
            method=client_call_details.method,
            timeout=client_call_details.timeout or self.timeout,
            metadata=tuple(client_call_details.metadata or ()) + (("x-api-key", self.api_key),),
            credentials=client_call_details.credentials,
            wait_for_ready=False,
        )
        try:
            for attempt in range(attempts):
                try:
                    call = await continuation(details, request)
                    result = await call
                except grpc.aio.AioRpcError as error:
                    if error.code() not in TRANSIENT_CODES:
                        self.breaker.success(generation)
                        raise
                    if attempt + 1 == attempts:
                        self.breaker.failure(generation)
                        raise
                    delay = self.backoff * 2**attempt
                    logger.warning(
                        "grpc retry method=%s attempt=%s delay=%.3f code=%s",
                        details.method.decode(),
                        attempt + 2,
                        delay,
                        error.code().name,
                    )
                    await asyncio.sleep(delay)
                else:
                    self.breaker.success(generation)
                    return result
        except asyncio.CancelledError:
            if self.breaker.state == "HALF_OPEN":
                self.breaker.failure(generation)
            raise
