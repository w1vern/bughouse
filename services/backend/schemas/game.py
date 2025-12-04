
from uuid import UUID

from pydantic import BaseModel

from shared.database import Game, GameUser, Move

from .user import UserSchema


class MoveSchema(BaseModel):
    notation: str
    time_to_move: float
    board_number: int

    @classmethod
    def from_db(cls, move: Move) -> 'MoveSchema':
        return MoveSchema(
            notation=move.notation,
            time_to_move=move.time_to_move,
            board_number=move.board_number,
        )


class GameUserSchema(BaseModel):
    board: int
    color: int
    rating: float
    diff: float
    user: UserSchema

    @classmethod
    def from_db(cls, game_user: GameUser) -> 'GameUserSchema':
        return GameUserSchema(
            board=game_user.board,
            color=game_user.color,
            rating=game_user.rating,
            diff=game_user.diff,
            user=UserSchema.from_db(game_user.user)
        )


class GameSchema(BaseModel):
    id: UUID
    result: int
    game_time: float
    increment: float
    moves: list[MoveSchema]
    game_users: list[GameUserSchema]

    @classmethod
    def from_db(cls, game: Game) -> 'GameSchema':
        return GameSchema(
            id=game.id,
            result=game.result,
            game_time=game.game_time,
            increment=game.increment,
            moves=[MoveSchema.from_db(move)
                   for move in game.moves],
            game_users=[GameUserSchema.from_db(game_user)
                        for game_user in game.game_users]
        )
