from collections.abc import Iterable
from datetime import date, datetime, timedelta

import grpc
from fastapi import Depends, HTTPException

from shared.database import GameRepository, User, UserRepository
from shared.protobuf import core_pb2 as pb

from ..depends import get_game_repo, get_user, get_user_repo
from ..exceptions import (
    InvalidDateRangeException,
    UserNotFoundException
)
from ..schemas import (
    DailyRatingSchema,
    RatingExtremesSchema,
    RatingExtremumSchema,
    StatsSchema,
    UserTokenSchema
)
from ..websocket.grpc_client import (
    AsyncCoreServiceStub,
    get_core_stub
)


class StatsService:
    def __init__(
        self,
        user_schema: UserTokenSchema,
        stub: AsyncCoreServiceStub,
        ur: UserRepository | None = None,
        gr: GameRepository | None = None
    ) -> None:
        self.user_schema = user_schema
        self.stub = stub
        self.ur = ur
        self.gr = gr

    @classmethod
    def depends_core(
        cls,
        user_schema: UserTokenSchema = Depends(get_user),
        stub: AsyncCoreServiceStub = Depends(get_core_stub)
    ) -> 'StatsService':
        return StatsService(
            user_schema=user_schema,
            stub=stub
        )

    @classmethod
    def depends(
        cls,
        user_schema: UserTokenSchema = Depends(get_user),
        stub: AsyncCoreServiceStub = Depends(get_core_stub),
        ur: UserRepository = Depends(get_user_repo),
        gr: GameRepository = Depends(get_game_repo)
    ) -> 'StatsService':
        return StatsService(
            user_schema=user_schema,
            stub=stub,
            ur=ur,
            gr=gr
        )

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

    @staticmethod
    def _make_extremum(
        points: Iterable[tuple[datetime, float]],
        rating: float
    ) -> RatingExtremumSchema:
        return RatingExtremumSchema(
            rating=rating,
            dates=[
                point_date
                for point_date, point_rating in points
                if point_rating == rating
            ]
        )

    async def _get_current_user(self) -> User:
        assert self.ur is not None, "User repository cannot be None"
        user = await self.ur.get_by_id(self.user_schema.id)
        if user is None:
            raise UserNotFoundException()
        return user

    async def get_rating_extremes(self) -> RatingExtremesSchema:
        assert self.gr is not None, "Game repository cannot be None"
        user = await self._get_current_user()
        history = await self.gr.get_user_rating_history(user.id)
        points = [
            (created_date, rating_after)
            for created_date, _rating_before, rating_after in history
        ]
        if history:
            points.insert(
                0,
                (user.created_date, history[0][1])
            )
        else:
            points.append((user.created_date, user.rating))

        ratings = [rating for _created_date, rating in points]
        minimum = min(ratings)
        maximum = max(ratings)
        return RatingExtremesSchema(
            minimum=self._make_extremum(points, minimum),
            maximum=self._make_extremum(points, maximum)
        )

    async def get_daily_ratings(
        self,
        date_from: date,
        date_to: date
    ) -> list[DailyRatingSchema]:
        if date_from > date_to:
            raise InvalidDateRangeException()

        assert self.gr is not None, "Game repository cannot be None"
        user = await self._get_current_user()
        history = await self.gr.get_user_rating_history(
            user.id,
            date_to=date_to
        )
        current_rating = history[0][1] if history else user.rating
        daily_changes: dict[date, float] = {}
        for created_date, _rating_before, rating_after in history:
            rating_date = created_date.date()
            if rating_date < date_from:
                current_rating = rating_after
            else:
                daily_changes[rating_date] = rating_after

        daily_ratings: list[DailyRatingSchema] = []
        current_day = date_from
        while current_day <= date_to:
            if current_day in daily_changes:
                current_rating = daily_changes[current_day]
            daily_ratings.append(
                DailyRatingSchema(
                    date=current_day,
                    rating=current_rating
                )
            )
            current_day += timedelta(days=1)
        return daily_ratings
