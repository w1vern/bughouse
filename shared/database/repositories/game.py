
from sqlalchemy import select
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
        users: tuple[User, User, User, User],
        diffs: tuple[float, float, float, float],
        moves: list[tuple[str, float, int]]
    ) -> Game:
        game = await self._create(
            result=result,
            game_time=game_time,
            increment=increment
        )
        for index in range(4):
            gu = GameUser(
                user_id=users[index].id,
                game_id=game.id,
                board=index > 1,
                color=index % 2,
                rating=users[index].rating,
                diff=diffs[index]
            )
            self.session.add(gu)
        for index, (notation, time_to_move, board_number) in enumerate(moves):
            move = Move(
                notation=notation,
                time_to_move=time_to_move,
                board_number=board_number,
                index=index,
                game_id=game.id,
                user_id=users[board_number*2+index % 2].id
            )
            self.session.add(move)
        await self.session.flush()
        return game

    async def get_by_user(
        self,
        user: User
    ) -> list[Game]:
        stmt = (
            select(self.model)
            .join(GameUser)
            .where(GameUser.user_id == user.id)
            .order_by(self.model.created_date.desc())
        )
        return list((await self.session.scalars(stmt)).all())
