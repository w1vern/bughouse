from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Iterator
from uuid import UUID

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
Assignment = tuple[tuple[QueueEntry, ...], Placement, bool]

EXACT_SEARCH_ENTRY_LIMIT = 24
NEAREST_CANDIDATES_PER_BUCKET = 24


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

# Match shape priority for bounded matchmaking.
#
# Complete 4-player lobbies are handled by QueueManager before grouped
# matchmaking.  Inside a config group we prefer preserving larger
# premade lobbies first, then fall back to fully solo games:
#   3+1 -> 2+2 -> 2+1+1 -> 1+1+1+1.
_BOUNDED_PARTITION_PRIORITY: tuple[tuple[int, ...], ...] = (
    (3, 1),
    (2, 2),
    (2, 1, 1),
    (1, 1, 1, 1),
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


def _entries_by_size(
    entries: Iterable[QueueEntry],
) -> dict[int, list[QueueEntry]]:
    by_size: dict[int, list[QueueEntry]] = {1: [], 2: [], 3: [], 4: []}
    for entry in entries:
        by_size[entry.size].append(entry)
    return by_size


def _nearest_entries(
    entries: list[QueueEntry],
    target_mu: float,
    limit: int,
    *,
    exclude: set[UUID],
) -> tuple[QueueEntry, ...]:
    candidates = [entry for entry in entries if entry.lobby_id not in exclude]
    candidates.sort(
        key=lambda entry: (
            abs(entry.avg_mu - target_mu),
            entry.enqueued_at,
            str(entry.lobby_id),
        )
    )
    return tuple(candidates[:limit])


def _iter_completions(
    anchor: QueueEntry,
    required_counts: dict[int, int],
    by_size: dict[int, list[QueueEntry]],
    nearest_candidate_limit: int,
) -> Iterator[tuple[QueueEntry, ...]]:
    combo_groups: list[tuple[tuple[QueueEntry, ...], ...]] = []
    excluded: set[UUID] = {anchor.lobby_id}

    for size, count in sorted(required_counts.items()):
        if count == 0:
            continue
        pool = _nearest_entries(
            by_size[size],
            anchor.avg_mu,
            nearest_candidate_limit,
            exclude=excluded,
        )
        if len(pool) < count:
            return
        combo_groups.append(tuple(itertools.combinations(pool, count)))

    for grouped_choices in itertools.product(*combo_groups):
        completion: list[QueueEntry] = []
        for choices in grouped_choices:
            completion.extend(choices)
        yield tuple(completion)


def _iter_anchor_partitions_for_sizes(
    anchor: QueueEntry,
    sizes: tuple[int, ...],
    by_size: dict[int, list[QueueEntry]],
    nearest_candidate_limit: int,
) -> Iterator[tuple[QueueEntry, ...]]:
    if anchor.size not in sizes:
        return
    if sizes == (3, 1) and anchor.config.rated:
        return

    remaining_sizes = list(sizes)
    remaining_sizes.remove(anchor.size)
    required_counts: dict[int, int] = {}
    for size in remaining_sizes:
        required_counts[size] = required_counts.get(size, 0) + 1

    for completion in _iter_completions(
        anchor,
        required_counts,
        by_size,
        nearest_candidate_limit,
    ):
        entries = (anchor,) + completion
        if sizes == (3, 1) and any(entry.config.rated for entry in entries):
            continue
        yield entries


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


def _best_scored_assignment(
    partitions: Iterable[tuple[QueueEntry, ...]],
    now: float,
    params: RankingParams,
) -> Assignment | None:
    best: Assignment | None = None
    best_score = math.inf
    for entries in partitions:
        for placement in _iter_placements(entries):
            for color_flip in (False, True):
                s = score(entries, placement, color_flip, now, params)
                if s < best_score:
                    best_score = s
                    best = (entries, placement, color_flip)
    return best


def _find_best_assignment_exact(
    group: list[QueueEntry],
    now: float,
    params: RankingParams,
) -> Assignment | None:
    return _best_scored_assignment(_iter_partitions(group), now, params)


def _find_best_assignment_bounded(
    group: list[QueueEntry],
    now: float,
    params: RankingParams,
    nearest_candidate_limit: int,
) -> Assignment | None:
    by_size = _entries_by_size(group)
    anchors = sorted(
        group,
        key=lambda entry: (entry.enqueued_at, str(entry.lobby_id)),
    )

    for anchor in anchors:
        for sizes in _BOUNDED_PARTITION_PRIORITY:
            candidates = _iter_anchor_partitions_for_sizes(
                anchor,
                sizes,
                by_size,
                nearest_candidate_limit,
            )
            best = _best_scored_assignment(candidates, now, params)
            if best is not None:
                return best

    return None


def find_best_assignment(
    group: list[QueueEntry],
    now: float,
    params: RankingParams,
    *,
    exact_entry_limit: int = EXACT_SEARCH_ENTRY_LIMIT,
    nearest_candidate_limit: int = NEAREST_CANDIDATES_PER_BUCKET,
) -> Assignment | None:
    """Find the next match for one compatible config group.

    Strategy:
    - for small groups, keep the exact exhaustive search;
    - for larger groups, use anchor-first bounded matchmaking:
      scan oldest lobbies first, try match shapes in the order
      3+1, 2+2, 2+1+1, 1+1+1+1, and only score the nearest
      rating neighbours for the chosen anchor.

    This caps the 100-solo burst case without changing the final
    scoring formula for candidates that are inspected.
    """
    if sum(entry.size for entry in group) < 4:
        return None
    if len(group) <= exact_entry_limit:
        return _find_best_assignment_exact(group, now, params)
    return _find_best_assignment_bounded(
        group,
        now,
        params,
        nearest_candidate_limit,
    )
