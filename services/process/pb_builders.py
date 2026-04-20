from __future__ import annotations

from typing import Any, Protocol

from shared.protobuf import process_pb2 as pb


class _SeatView(Protocol):
    user_id: str
    username: str
    rating: float


class _LobbyView(Protocol):
    id: str
    leader_id: str
    state: str
    initial_ms: int
    increment_ms: int
    rated: bool
    @property
    def seats(self) -> list[_SeatView | None]: ...


class _GameView(Protocol):
    game_id: str
    winner: str
    last_move: str

    def fen_for(self, user_id: str) -> str: ...
    def mate_fen_for(self, user_id: str) -> str: ...
    def pockets_json(self) -> str: ...
    def clocks_tuple(self) -> tuple[int, int, int, int]: ...
    def board_of(self, user_id: str) -> int: ...
    def color_of(self, user_id: str) -> int: ...
    def partner_of(self, user_id: str) -> str: ...
    def opponents_of(self, user_id: str) -> list[str]: ...
    def is_turn_of(self, user_id: str) -> bool: ...


def build_lobby_state(lobby: _LobbyView) -> pb.LobbyState:
    seats_pb: list[pb.Seat] = []
    for seat in lobby.seats:
        if seat is None:
            seats_pb.append(pb.Seat(empty=True))
        else:
            seats_pb.append(pb.Seat(
                empty=False,
                user_id=seat.user_id,
                username=seat.username,
                rating=seat.rating,
            ))
    return pb.LobbyState(
        id=lobby.id,
        leader_id=lobby.leader_id,
        seats=seats_pb,
        config=pb.LobbyConfig(
            initial_ms=lobby.initial_ms,
            increment_ms=lobby.increment_ms,
            rated=lobby.rated,
        ),
        state=lobby.state,
    )


def build_game_state(game: _GameView, user_id: str) -> pb.GameState:
    b0w, b0b, b1w, b1b = game.clocks_tuple()
    return pb.GameState(
        game_id=game.game_id,
        board=game.board_of(user_id),
        color=game.color_of(user_id),
        partner_id=game.partner_of(user_id),
        opponents=game.opponents_of(user_id),
        fen=game.fen_for(user_id),
        mate_fen=game.mate_fen_for(user_id),
        pockets=pb.Pockets(json=game.pockets_json()),
        last_move=game.last_move,
        clocks=pb.Clocks(b0w=b0w, b0b=b0b, b1w=b1w, b1b=b1b),
        your_turn=game.is_turn_of(user_id),
        winner=game.winner,
    )
