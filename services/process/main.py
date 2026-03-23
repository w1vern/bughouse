
from shared.protobuf import process_pb2, process_pb2_grpc

from concurrent import futures

from grpc import aio

from shared.infrastructure import setup_logger

logger = setup_logger(__name__)


class ProcessServiceServicer(process_pb2_grpc.ProcessServiceServicer):

    async def CreateLobby(self, request, context) -> process_pb2.LobbyResponse:
        logger.info("CreateLobby user_id=%s", request.user_id)
        return process_pb2.LobbyResponse(ok=True, lobby_id="", error="")

    async def JoinLobby(self, request, context) -> process_pb2.LobbyResponse:
        logger.info("JoinLobby lobby_id=%s user_id=%s",
                    request.lobby_id, request.user_id)
        return process_pb2.LobbyResponse(ok=True, lobby_id=request.lobby_id, error="")

    async def LeaveLobby(self, request, context) -> process_pb2.LobbyResponse:
        logger.info("LeaveLobby lobby_id=%s user_id=%s",
                    request.lobby_id, request.user_id)
        return process_pb2.LobbyResponse(ok=True, lobby_id=request.lobby_id, error="")

    async def GetLobby(self, request, context) -> process_pb2.LobbyResponse:
        logger.info("GetLobby lobby_id=%s", request.lobby_id)
        return process_pb2.LobbyResponse(ok=True, lobby_id=request.lobby_id, error="")

    async def StartMatchmaking(self, request, context) -> process_pb2.StatusResponse:
        logger.info("StartMatchmaking lobby_id=%s", request.lobby_id)
        return process_pb2.StatusResponse(ok=True, error="")

    async def CancelMatchmaking(self, request, context) -> process_pb2.StatusResponse:
        logger.info("CancelMatchmaking lobby_id=%s", request.lobby_id)
        return process_pb2.StatusResponse(ok=True, error="")

    async def GetGameState(self, request, context) -> process_pb2.GameStateResponse:
        logger.info("GetGameState game_id=%s", request.game_id)
        return process_pb2.GameStateResponse(ok=True, json_state="{}", error="")


async def serve() -> None:
    server = aio.server(futures.ThreadPoolExecutor(max_workers=10))
    process_pb2_grpc.add_ProcessServiceServicer_to_server(
        ProcessServiceServicer(), server
    )
    server.add_insecure_port("0.0.0.0:50051")
    await server.start()
    logger.info("gRPC сервер запущен на 0.0.0.0:50051")
    await server.wait_for_termination()
