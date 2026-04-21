
import grpc
from grpc import aio

from shared.infrastructure import env_config, setup_logger
from shared.protobuf import process_pb2_grpc

logger = setup_logger(__name__)

_channel: aio.Channel | None = None
_stub: process_pb2_grpc.ProcessServiceStub | None = None


async def init_grpc_channel() -> None:
    global _channel, _stub
    target = f"{env_config.process.grpc_host}:{env_config.process.grpc_port}"
    _channel = aio.insecure_channel(target)
    _stub = process_pb2_grpc.ProcessServiceStub(_channel)
    logger.info("gRPC channel to process opened: %s", target)


async def close_grpc_channel() -> None:
    global _channel, _stub
    if _channel is not None:
        await _channel.close(grace=None)
        logger.info("gRPC channel to process closed")
    _channel = None
    _stub = None


def get_process_stub() -> process_pb2_grpc.ProcessServiceStub:
    if _stub is None:
        raise RuntimeError("gRPC channel is not initialized")
    return _stub
