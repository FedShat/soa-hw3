import hmac
import logging

import grpc
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class BusinessError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


class ServerInterceptor(grpc.aio.ServerInterceptor):
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def intercept_service(self, continuation, handler_call_details):
        handler = await continuation(handler_call_details)
        if handler is None:
            return None

        async def invoke(request, context):
            metadata = dict(context.invocation_metadata())
            supplied = metadata.get("x-api-key", "")
            if not hmac.compare_digest(supplied.encode(), self.api_key.encode()):
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid service API key")
            try:
                return await handler.unary_unary(request, context)
            except BusinessError as error:
                await context.abort(error.code, error.message)
            except (ValueError, OverflowError) as error:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(error))
            except SQLAlchemyError:
                logger.exception("Flight database failure")
                await context.abort(grpc.StatusCode.UNAVAILABLE, "Flight database is unavailable")

        return grpc.unary_unary_rpc_method_handler(
            invoke,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
