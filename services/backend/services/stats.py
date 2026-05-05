import grpc
from fastapi import Depends, HTTPException

from shared.protobuf import core_pb2 as pb

from ..schemas import StatsSchema
from ..websocket.grpc_client import AsyncCoreServiceStub, get_core_stub


class StatsService:
    def __init__(self, stub: AsyncCoreServiceStub) -> None:
        self.stub = stub

    @classmethod
    def depends(
        cls,
        stub: AsyncCoreServiceStub = Depends(get_core_stub)
    ) -> 'StatsService':
        return StatsService(stub=stub)

    async def get(self) -> StatsSchema:
        try:
            resp: pb.StatsResp = await self.stub.GetStats(pb.StatsReq())
        except grpc.aio.AioRpcError as exc:
            raise HTTPException(
                status_code=503,
                detail=exc.details() or "Core service unavailable",
            ) from exc
        if not resp.ok:
            raise HTTPException(
                status_code=500,
                detail=resp.message or resp.error_code or "Stats unavailable",
            )
        return StatsSchema(
            online_users=resp.online_users,
            available_players=resp.available_players,
            queued_players=resp.queued_players,
            queued_lobbies=resp.queued_lobbies,
            active_games=resp.active_games,
        )
