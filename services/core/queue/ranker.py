from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Iterator

import trueskill

from shared.infrastructure.config import RankingParams

from ..lobby.models import Seat
from .models import QueueEntry

Placement = tuple[tuple[int, ...], ...]


def to_rating(seat: Seat, sigma: float) -> trueskill.Rating:
    return trueskill.Rating(mu=seat.rating, sigma=sigma)


def compose_teams(
    slots: tuple[Seat, Seat, Seat, Seat],
) -> tuple[tuple[Seat, Seat], tuple[Seat, Seat]]:
    team_a = (slots[0], slots[3])
    team_b = (slots[1], slots[2])
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


def _iter_placements(entries: tuple[QueueEntry, ...]) -> Iterator[Placement]:
    def recurse(i: int, remaining: tuple[int, ...]) -> Iterator[Placement]:
        if i == len(entries):
            yield ()
            return
        sz = entries[i].size
        for combo in itertools.combinations(remaining, sz):
            rest = tuple(x for x in remaining if x not in combo)
            for tail in recurse(i + 1, rest):
                yield (combo,) + tail

    yield from recurse(0, (0, 1, 2, 3))


def _build_slots(
    entries: tuple[QueueEntry, ...],
    placement: Placement,
) -> tuple[tuple[Seat, Seat, Seat, Seat], tuple[float, float, float, float], tuple[int, int, int, int]]:
    seats: list[Seat | None] = [None, None, None, None]
    sigmas: list[float | None] = [None, None, None, None]
    colors: list[int | None] = [None, None, None, None]
    for entry, slot_indices in zip(entries, placement):
        positions = entry.positions
        for entry_pos, slot_idx in zip(positions, slot_indices):
            seats[slot_idx] = entry.seats[entry_pos]
            sigmas[slot_idx] = entry.sigmas[entry_pos]
            colors[slot_idx] = entry.colors[entry_pos]
    return (
        (seats[0], seats[1], seats[2], seats[3]),  # type: ignore[return-value]
        (sigmas[0], sigmas[1], sigmas[2], sigmas[3]),  # type: ignore[return-value]
        (colors[0], colors[1], colors[2], colors[3]),  # type: ignore[return-value]
    )


def score(
    entries: tuple[QueueEntry, ...],
    placement: Placement,
    now: float,
    params: RankingParams,
) -> float:
    seats, sigmas, colors = _build_slots(entries, placement)
    ratings = tuple(to_rating(s, sig) for s, sig in zip(seats, sigmas))
    team_a = (ratings[0], ratings[3])
    team_b = (ratings[1], ratings[2])
    quality = trueskill.quality([team_a, team_b])

    base = abs(quality - 0.5)

    color_a = colors[0] * 1 + colors[3] * (-1)
    color_b = colors[1] * (-1) + colors[2] * 1
    color_penalty = (abs(color_a) + abs(color_b)) * params.queue_color_weight

    wait_bonus = params.queue_wait_bonus * sum(now - e.enqueued_at for e in entries)

    return base + color_penalty - wait_bonus


def find_best_assignment(
    group: list[QueueEntry],
    now: float,
    params: RankingParams,
) -> tuple[tuple[QueueEntry, ...], Placement] | None:
    best: tuple[tuple[QueueEntry, ...], Placement] | None = None
    best_score = math.inf
    for entries in _iter_partitions(group):
        for placement in _iter_placements(entries):
            s = score(entries, placement, now, params)
            if s < best_score:
                best_score = s
                best = (entries, placement)
    return best
