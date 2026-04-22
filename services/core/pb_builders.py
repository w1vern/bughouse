from __future__ import annotations

import json
from uuid import UUID

import chess

from shared.protobuf import process_pb2 as pb

from .game.models import GameObj
from .lobby.models import Lobby, LobbyState


def build_lobby_state(lobby: Lobby) -> pb.LobbyState:
    seats_pb: list[pb.Seat] = []
    for seat in lobby.seats:
        if seat is None:
            seats_pb.append(pb.Seat(empty=True))
        else:
            seats_pb.append(pb.Seat(
                empty=False,
                user_id=str(seat.user_id),
                username=seat.username,
                rating=seat.rating,
            ))
    state_str = "IN_QUEUE" if lobby.state == LobbyState.IN_QUEUE else "IDLE"
    return pb.LobbyState(
        id=str(lobby.id),
        leader_id=str(lobby.leader_id),
        seats=seats_pb,
        config=pb.LobbyConfig(
            initial_ms=lobby.config.initial_ms,
            increment_ms=lobby.config.increment_ms,
            rated=lobby.config.rated,
        ),
        state=state_str,
    )


def build_game_state(game: GameObj, user_id: UUID) -> pb.GameState:
    pos = game.pos_of(user_id)
    board_idx = pos // 2
    partner_idx = 1 - board_idx
    color = chess.WHITE if pos % 2 == 0 else chess.BLACK
    snap = game.boards.to_snapshot(board_idx)
    clocks = game.clocks.snapshot()
    pockets_payload = snap["pockets"]
    last_move = snap["last_move"] or ""
    return pb.GameState(
        game_id=str(game.id),
        board=board_idx,
        color=int(color),
        partner_id=str(game.partner_of(user_id)),
        opponents=[str(uid) for uid in game.opponents_of(user_id)],
        fen=game.boards.fen(board_idx),
        mate_fen=game.boards.fen(partner_idx),
        pockets=pb.Pockets(json=json.dumps(pockets_payload)),
        last_move=last_move,
        clocks=pb.Clocks(
            b0w=clocks["b0w"],
            b0b=clocks["b0b"],
            b1w=clocks["b1w"],
            b1b=clocks["b1b"],
        ),
        your_turn=game.is_turn_of(user_id),
        winner=game.winner_str(),
    )
