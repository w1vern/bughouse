
from datetime import date, datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Game, GameUser, Move, User
from .base import BaseRepository


class GameRepository(BaseRepository[Game]):
    def __init__(
        self,
        session: AsyncSession
    ) -> None:
        super().__init__(
            session=session,
            model=Game
        )

    async def create(
        self,
        *,
        result: int,
        game_time: float,
        increment: float,
        rated: bool,
        end_reason: str | None,
        users: tuple[User, User, User, User],
        board_numbers: tuple[int, int, int, int],
        colors: tuple[int, int, int, int],
        ratings: tuple[float, float, float, float],
        diffs: tuple[float, float, float, float],
        moves: list[tuple[str, int, int, UUID]]
    ) -> Game:
        game = await self._create(
            result=result,
            game_time=game_time,
            increment=increment,
            rated=rated,
            end_reason=end_reason
        )
        for index in range(4):
            gu = GameUser(
                user_id=users[index].id,
                game_id=game.id,
                board_number=board_numbers[index],
                color=colors[index],
                rating=ratings[index],
                diff=diffs[index]
            )
            self.session.add(gu)
        for index, (notation, time_to_move, board_number, user_id) in enumerate(moves):
            move = Move(
                notation=notation,
                time_to_move=time_to_move,
                board_number=board_number,
                index=index,
                game_id=game.id,
                user_id=user_id
            )
            self.session.add(move)
        await self.session.flush()
        return game

    async def get_all(
        self,
        limit: int | None = None,
        offset: int | None = None,
        **kwargs: Any | None
    ) -> list[Game]:
        user_id = kwargs.pop("user_id", None)
        if kwargs:
            return await super().get_all(limit, offset, **kwargs)
        if user_id is None:
            return await super().get_all(limit, offset)

        stmt = (
            select(self.model)
            .join(GameUser)
            .where(self.model.deleted_date.is_(None))
            .where(GameUser.deleted_date.is_(None))
            .where(GameUser.user_id == user_id)
            .limit(limit)
            .offset(offset)
            .order_by(self.model.created_date.desc(), self.model.id.asc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def count(
        self,
        **kwargs: Any
    ) -> int:
        user_id = kwargs.pop("user_id", None)
        if kwargs:
            return await super().count(**kwargs)
        if user_id is None:
            return await super().count()

        stmt = (
            select(func.count())
            .select_from(self.model)
            .join(GameUser)
            .where(self.model.deleted_date.is_(None))
            .where(GameUser.deleted_date.is_(None))
            .where(GameUser.user_id == user_id)
        )
        count = await self.session.scalar(stmt)
        if count is None:
            return 0
        return count

    async def get_by_user(
        self,
        user: User
    ) -> list[Game]:
        stmt = (
            select(self.model)
            .join(GameUser)
            .where(self.model.deleted_date.is_(None))
            .where(GameUser.deleted_date.is_(None))
            .where(GameUser.user_id == user.id)
            .order_by(self.model.created_date.desc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_user_rating_history(
        self,
        user_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None
    ) -> list[tuple[datetime, float, float]]:
        stmt = (
            select(
                self.model.created_date,
                GameUser.rating,
                GameUser.diff
            )
            .join(GameUser)
            .where(self.model.deleted_date.is_(None))
            .where(GameUser.deleted_date.is_(None))
            .where(self.model.rated.is_(True))
            .where(GameUser.user_id == user_id)
            .order_by(
                self.model.created_date.asc(),
                self.model.id.asc()
            )
        )
        if date_from is not None:
            stmt = stmt.where(
                self.model.created_date >= datetime.combine(
                    date_from,
                    time.min
                )
            )
        if date_to is not None:
            stmt = stmt.where(
                self.model.created_date <= datetime.combine(
                    date_to,
                    time.max
                )
            )

        rows = (await self.session.execute(stmt)).all()
        return [
            (created_date, rating, rating + diff)
            for created_date, rating, diff in rows
        ]
