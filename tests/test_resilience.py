import asyncio
from unittest.mock import AsyncMock

import grpc
import pytest

from generated import flight_pb2 as pb
from services.booking.resilience import CircuitBreaker, CircuitOpenError, ResilienceInterceptor
from shared.config import Settings


def settings(**values):
    return Settings(
        database_url="postgresql+asyncpg://unused",
        grpc_api_key="test-service-api-key",
        **values,
    )


def rpc_error(code):
    return grpc.aio.AioRpcError(code, grpc.aio.Metadata(), grpc.aio.Metadata(), "test failure")


def call_details():
    return grpc.aio.ClientCallDetails(
        b"/flight.v1.FlightService/ReserveSeats", None, (), None, None
    )


def test_breaker_single_probe_and_recovery():
    now = [0.0]
    breaker = CircuitBreaker(2, 10, 30, clock=lambda: now[0])
    breaker.failure(breaker.acquire())
    breaker.failure(breaker.acquire())
    assert breaker.state == "OPEN"
    with pytest.raises(CircuitOpenError):
        breaker.acquire()
    now[0] = 10
    probe = breaker.acquire()
    assert breaker.state == "HALF_OPEN"
    with pytest.raises(CircuitOpenError):
        breaker.acquire()
    breaker.failure(probe)
    assert breaker.state == "OPEN"
    now[0] = 20
    breaker.success(breaker.acquire())
    assert breaker.state == "CLOSED"


def test_breaker_ignores_stale_results_and_expires_failures():
    now = [0.0]
    breaker = CircuitBreaker(2, 10, 5, clock=lambda: now[0])
    stale = breaker.acquire()
    breaker.failure(stale)
    now[0] = 6
    breaker.failure(breaker.acquire())
    assert breaker.state == "CLOSED"
    breaker.failure(breaker.acquire())
    breaker.success(stale)
    assert breaker.state == "OPEN"


@pytest.mark.parametrize("code", [grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED])
async def test_retry_limit_backoff_and_same_request(code, monkeypatch):
    interceptor = ResilienceInterceptor(settings())
    sleep = AsyncMock()
    monkeypatch.setattr("services.booking.resilience.asyncio.sleep", sleep)
    continuation = AsyncMock(side_effect=rpc_error(code))
    request = pb.ReserveSeatsRequest(booking_id="same-booking", seat_count=1)
    with pytest.raises(grpc.aio.AioRpcError):
        await interceptor.intercept_unary_unary(continuation, call_details(), request)
    assert continuation.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [0.1, 0.2]
    assert all(call.args[1] is request for call in continuation.await_args_list)
    assert continuation.await_args.args[0].metadata == (("x-api-key", "test-service-api-key"),)


@pytest.mark.parametrize(
    "code",
    [
        grpc.StatusCode.INVALID_ARGUMENT,
        grpc.StatusCode.NOT_FOUND,
        grpc.StatusCode.RESOURCE_EXHAUSTED,
    ],
)
async def test_business_errors_do_not_retry_or_open_circuit(code):
    interceptor = ResilienceInterceptor(settings(circuit_failure_threshold=1))
    continuation = AsyncMock(side_effect=rpc_error(code))
    with pytest.raises(grpc.aio.AioRpcError):
        await interceptor.intercept_unary_unary(
            continuation, call_details(), pb.ReserveSeatsRequest()
        )
    assert continuation.await_count == 1
    assert interceptor.breaker.state == "CLOSED"


async def test_retry_recovers_and_open_circuit_never_calls_transport(monkeypatch):
    interceptor = ResilienceInterceptor(settings(circuit_failure_threshold=1))
    monkeypatch.setattr("services.booking.resilience.asyncio.sleep", AsyncMock())
    response = pb.SeatReservation(booking_id="same-booking")
    future = asyncio.get_running_loop().create_future()
    future.set_result(response)
    continuation = AsyncMock(side_effect=[rpc_error(grpc.StatusCode.UNAVAILABLE), future])
    assert (
        await interceptor.intercept_unary_unary(
            continuation, call_details(), pb.ReserveSeatsRequest()
        )
        == response
    )
    assert continuation.await_count == 2
    interceptor.breaker.failure(interceptor.breaker.acquire())
    continuation.reset_mock()
    with pytest.raises(CircuitOpenError):
        await interceptor.intercept_unary_unary(
            continuation, call_details(), pb.ReserveSeatsRequest()
        )
    continuation.assert_not_called()
