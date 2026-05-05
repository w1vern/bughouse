from __future__ import annotations

import itertools
import math
from collections.abc import Iterator

import chess
import trueskill

from shared.infrastructure.config import RankingParams

from ..game.models import pos_to_color
from ..lobby.models import Seat
from .models import QueueEntry

# A placement maps each entry's lobby positions to game positions.
# entry_mapping[i] = game_pos_for_lobby_pos_i  (or -1 if that lobby slot is empty).
# Placement covers all 4 game positions across all entries.
EntryMapping = tuple[int, int, int, int]
Placement = tuple[EntryMapping, ...]


# Automorphisms of the 4-position bughouse topology that preserve
# teammate / same-board / cross-board relations.
# Each automorphism is a permutation of positions {0,1,2,3}.
# Topology constraints:
#   teammate pairs: (0,1) and (2,3)
#   same-board   : (0,2) and (1,3)
#   cross-board  : (0,3) and (1,2)
_AUTOMORPHISMS: tuple[tuple[int, int, int, int], ...] = (
    (0, 1, 2, 3),  # identity
    (1, 0, 3, 2),  # swap within both teams (preserves teammates; swaps same-/cross-board pair labels self-consistently)
    (2, 3, 0, 1),  # swap teams
    (3, 2, 1, 0),  # swap teams + swap within
)


def to_rating(seat: Seat, sigma: float) -> trueskill.Rating:
    return trueskill.Rating(mu=seat.rating, sigma=sigma)


def compose_teams(
    slots: tuple[Seat, Seat, Seat, Seat],
) -> tuple[tuple[Seat, Seat], tuple[Seat, Seat]]:
    """Team A = (slot 0, slot 1); Team B = (slot 2, slot 3)."""
    team_a = (slots[0], slots[1])
    team_b = (slots[2], slots[3])
    return team_a, team_b


def _iter_partitions(group: list[QueueEntry]) -> Iterator[tuple[QueueEntry, ...]]:
    by_size: dict[int, list[QueueEntry]] = {1: [], 2: [], 3: [], 4: []}
    for e in group:
        by_size[e.size].append(e)

    size_partitions: list[tuple[int, ...]] = [
        (4,),
        (3, 1),
        (2, 2),
        (2, 1, 1),
        (1, 1, 1, 1),
    ]
    for sizes in size_partitions:
        if sizes == (3, 1):
            for e3, e1 in itertools.product(by_size[3], by_size[1]):
                if e3.config.rated or e1.config.rated:
                    continue
                yield (e3, e1)
            continue
        if sizes == (4,):
            for e in by_size[4]:
                yield (e,)
            continue
        if sizes == (2, 2):
            for a, b in itertools.combinations(by_size[2], 2):
                yield (a, b)
            continue
        if sizes == (2, 1, 1):
            for e2 in by_size[2]:
                for a, b in itertools.combinations(by_size[1], 2):
                    yield (e2, a, b)
            continue
        if sizes == (1, 1, 1, 1):
            for combo in itertools.combinations(by_size[1], 4):
                yield combo


def _entry_mappings(entry: QueueEntry) -> list[EntryMapping]:
    """All topology-preserving mappings of this entry's lobby positions to game positions.

    Returns a list of EntryMapping, where mapping[i] = game_pos for lobby pos i,
    or -1 if lobby slot i was empty.
    """
    out: list[EntryMapping] = []
    seen: set[EntryMapping] = set()
    for perm in _AUTOMORPHISMS:
        mapping = tuple(
            perm[i] if entry.seats[i] is not None else -1 for i in range(4)
        )
        if mapping in seen:
            continue
        seen.add(mapping)
        out.append(mapping)  # type: ignore[arg-type]
    return out


def _iter_placements(entries: tuple[QueueEntry, ...]) -> Iterator[Placement]:
    """Enumerate all valid topology-preserving placements covering positions {0,1,2,3}."""
    per_entry = [_entry_mappings(e) for e in entries]

    def recurse(i: int, used: int) -> Iterator[Placement]:
        if i == len(entries):
            if used == 0b1111:
                yield ()
            return
        for mapping in per_entry[i]:
            mask = 0
            ok = True
            for game_pos in mapping:
                if game_pos == -1:
                    continue
                bit = 1 << game_pos
                if used & bit or mask & bit:
                    ok = False
                    break
                mask |= bit
            if not ok:
                continue
            for tail in recurse(i + 1, used | mask):
                yield (mapping,) + tail

    yield from recurse(0, 0)


def _build_slots(
    entries: tuple[QueueEntry, ...],
    placement: Placement,
) -> tuple[tuple[Seat, Seat, Seat, Seat], tuple[float, float, float, float], tuple[int, int, int, int]]:
    seats: list[Seat | None] = [None, None, None, None]
    sigmas: list[float | None] = [None, None, None, None]
    colors: list[int | None] = [None, None, None, None]
    for entry, mapping in zip(entries, placement):
        for lobby_pos in range(4):
            game_pos = mapping[lobby_pos]
            if game_pos == -1:
                continue
            seat = entry.seats[lobby_pos]
            if seat is None:
                continue
            seats[game_pos] = seat
            sigmas[game_pos] = entry.sigmas[lobby_pos]
            colors[game_pos] = entry.colors[lobby_pos]
    return (
        (seats[0], seats[1], seats[2], seats[3]),  # type: ignore[return-value]
        (sigmas[0], sigmas[1], sigmas[2], sigmas[3]),  # type: ignore[return-value]
        (colors[0], colors[1], colors[2], colors[3]),  # type: ignore[return-value]
    )


def _color_imbalance(colors: tuple[int, int, int, int], color_flip: bool) -> float:
    """Penalise each player's projected color imbalance after this game.

    `user.color` accumulates +1 per game played as white, -1 as black.
    Per-slot weight is +1 for white and -1 for black.
    """
    weights = [
        1 if pos_to_color(pos, color_flip) == chess.WHITE else -1
        for pos in range(4)
    ]
    return sum(abs(color + weight) for color, weight in zip(colors, weights))


def score(
    entries: tuple[QueueEntry, ...],
    placement: Placement,
    color_flip: bool,
    now: float,
    params: RankingParams,
) -> float:
    seats, sigmas, colors = _build_slots(entries, placement)
    ratings = tuple(to_rating(s, sig) for s, sig in zip(seats, sigmas))
    team_a = (ratings[0], ratings[1])
    team_b = (ratings[2], ratings[3])
    quality = trueskill.quality([team_a, team_b])

    base = -quality
    color_penalty = _color_imbalance(colors, color_flip) * params.queue_color_weight
    wait_bonus = params.queue_wait_bonus * sum(now - e.enqueued_at for e in entries)
    return base + color_penalty - wait_bonus


def find_best_assignment(
    group: list[QueueEntry],
    now: float,
    params: RankingParams,
) -> tuple[tuple[QueueEntry, ...], Placement, bool] | None:
    best: tuple[tuple[QueueEntry, ...], Placement, bool] | None = None
    best_score = math.inf
    for entries in _iter_partitions(group):
        for placement in _iter_placements(entries):
            for color_flip in (False, True):
                s = score(entries, placement, color_flip, now, params)
                if s < best_score:
                    best_score = s
                    best = (entries, placement, color_flip)
    return best
