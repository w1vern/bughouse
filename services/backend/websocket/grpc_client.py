
from grpc import aio

from shared.infrastructure import env_config, setup_logger
from shared.protobuf import core_pb2_grpc

logger = setup_logger(__name__)

_channel: aio.Channel | None = None
_stub: core_pb2_grpc.CoreServiceStub | None = None


async def init_grpc_channel() -> None:
    global _channel, _stub
    target = f"{env_config.core.host}:{env_config.core.port}"
    _channel = aio.insecure_channel(
        target,
        options=[("grpc.enable_http_proxy", 0)],
        )
    _stub = core_pb2_grpc.CoreServiceStub(_channel)
    logger.info("gRPC channel to core opened: %s", target)


async def close_grpc_channel() -> None:
    global _channel, _stub
    if _channel is not None:
        await _channel.close(grace=None)
        logger.info("gRPC channel to core closed")
    _channel = None
    _stub = None


def get_core_stub() -> core_pb2_grpc.CoreServiceStub:
    if _stub is None:
        raise RuntimeError("gRPC channel is not initialized")
    return _stub
