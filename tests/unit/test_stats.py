from __future__ import annotations

import unittest
from datetime import date, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException

from services.backend.schemas import RatingExtremesSchema
from services.backend.services.stats import StatsService
from services.core.main import CoreServiceServicer
from shared.protobuf import core_pb2 as pb


class FakeNotifier:
    async def count_online_users(self) -> int:
        return 12

    async def count_available_players(self) -> int:
        return 5


class FakeStatsStub:
    def __init__(self) -> None:
        self.request: pb.StatsReq | None = None

    async def GetStats(self, request: pb.StatsReq) -> pb.StatsResp:
        self.request = request
        return pb.StatsResp(
            ok=True,
            online_users=12,
            available_players=5,
            queued_players=8,
            queued_lobbies=3,
            active_games=4,
        )


class FakeUserRepo:
    def __init__(self, user: SimpleNamespace | None) -> None:
        self.user = user
        self.requested_id = None

    async def get_by_id(self, id):  # type: ignore[no-untyped-def]
        self.requested_id = id
        if self.user is not None and self.user.id == id:
            return self.user
        return None


class FakeGameRepo:
    def __init__(
        self,
        history: list[tuple[datetime, float, float]]
    ) -> None:
        self.history = history
        self.calls = []

    async def get_user_rating_history(
        self,
        user_id,
        date_from=None,
        date_to=None
    ):  # type: ignore[no-untyped-def]
        self.calls.append((user_id, date_from, date_to))
        return self.history


class CoreStatsTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_stats_returns_current_core_counts(self) -> None:
        service = CoreServiceServicer(
            SimpleNamespace(),
            SimpleNamespace(queued_players_count=8, queued_lobbies_count=3),
            SimpleNamespace(active_games_count=4),
            SimpleNamespace(),
            FakeNotifier(),  # type: ignore[arg-type]
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
        )

        resp = await service.GetStats(pb.StatsReq(), None)

        self.assertTrue(resp.ok)
        self.assertEqual(resp.online_users, 12)
        self.assertEqual(resp.available_players, 5)
        self.assertEqual(resp.queued_players, 8)
        self.assertEqual(resp.queued_lobbies, 3)
        self.assertEqual(resp.active_games, 4)


class BackendStatsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_maps_core_stats_response_to_schema(self) -> None:
        stub = FakeStatsStub()
        user_schema = SimpleNamespace(username="alice")
        service = StatsService(user_schema, stub)  # type: ignore[arg-type]

        stats = await service.get()

        self.assertIsInstance(stub.request, pb.StatsReq)
        self.assertEqual(stats.online_users, 12)
        self.assertEqual(stats.available_players, 5)
        self.assertEqual(stats.queued_players, 8)
        self.assertEqual(stats.queued_lobbies, 3)
        self.assertEqual(stats.active_games, 4)

    async def test_get_rating_extremes_returns_min_max_with_dates(
        self
    ) -> None:
        user_id = uuid4()
        user = SimpleNamespace(
            id=user_id,
            rating=30.0,
            created_date=datetime(2026, 1, 1, 12)
        )
        history = [
            (datetime(2026, 1, 2, 10), 25.0, 27.0),
            (datetime(2026, 1, 3, 10), 27.0, 22.0),
            (datetime(2026, 1, 4, 10), 22.0, 30.0),
            (datetime(2026, 1, 5, 10), 30.0, 30.0)
        ]
        gr = FakeGameRepo(history)
        service = StatsService(
            SimpleNamespace(id=user_id, username="alice"),
            FakeStatsStub(),
            FakeUserRepo(user),  # type: ignore[arg-type]
            gr  # type: ignore[arg-type]
        )

        extremes = await service.get_rating_extremes()

        self.assertIsInstance(extremes, RatingExtremesSchema)
        assert extremes.minimum is not None
        assert extremes.maximum is not None
        self.assertEqual(extremes.minimum.rating, 22.0)
        self.assertEqual(
            extremes.minimum.dates,
            [datetime(2026, 1, 3, 10)]
        )
        self.assertEqual(extremes.maximum.rating, 30.0)
        self.assertEqual(
            extremes.maximum.dates,
            [
                datetime(2026, 1, 4, 10),
                datetime(2026, 1, 5, 10)
            ]
        )
        self.assertEqual(gr.calls, [(user_id, None, None)])

    async def test_get_rating_extremes_uses_current_rating_without_games(
        self
    ) -> None:
        user_id = uuid4()
        user = SimpleNamespace(
            id=user_id,
            rating=25.0,
            created_date=datetime(2026, 1, 1, 12)
        )
        service = StatsService(
            SimpleNamespace(id=user_id, username="alice"),
            FakeStatsStub(),
            FakeUserRepo(user),  # type: ignore[arg-type]
            FakeGameRepo([])  # type: ignore[arg-type]
        )

        extremes = await service.get_rating_extremes()

        assert extremes.minimum is not None
        assert extremes.maximum is not None
        self.assertEqual(extremes.minimum.rating, 25.0)
        self.assertEqual(extremes.maximum.rating, 25.0)
        self.assertEqual(
            extremes.minimum.dates,
            [datetime(2026, 1, 1, 12)]
        )

    async def test_get_daily_ratings_returns_last_rating_per_day(
        self
    ) -> None:
        user_id = uuid4()
        user = SimpleNamespace(
            id=user_id,
            rating=27.0,
            created_date=datetime(2026, 1, 1, 12)
        )
        gr = FakeGameRepo([
            (datetime(2026, 1, 1, 20), 25.0, 24.0),
            (datetime(2026, 1, 2, 9), 24.0, 26.0),
            (datetime(2026, 1, 2, 20), 26.0, 28.0),
            (datetime(2026, 1, 3, 10), 28.0, 27.0)
        ])
        service = StatsService(
            SimpleNamespace(id=user_id, username="alice"),
            FakeStatsStub(),
            FakeUserRepo(user),  # type: ignore[arg-type]
            gr  # type: ignore[arg-type]
        )

        points = await service.get_daily_ratings(
            date_from=date(2026, 1, 2),
            date_to=date(2026, 1, 4)
        )

        self.assertEqual(gr.calls, [
            (user_id, None, date(2026, 1, 4))
        ])
        self.assertEqual([point.date for point in points], [
            date(2026, 1, 2),
            date(2026, 1, 3),
            date(2026, 1, 4)
        ])
        self.assertEqual(
            [point.rating for point in points],
            [28.0, 27.0, 27.0]
        )

    async def test_get_daily_ratings_rejects_invalid_interval(self) -> None:
        user_id = uuid4()
        service = StatsService(
            SimpleNamespace(id=user_id, username="alice"),
            FakeStatsStub(),
            FakeUserRepo(None),  # type: ignore[arg-type]
            FakeGameRepo([])  # type: ignore[arg-type]
        )

        with self.assertRaises(HTTPException) as ctx:
            await service.get_daily_ratings(
                date_from=date(2026, 1, 3),
                date_to=date(2026, 1, 2)
            )

        self.assertEqual(ctx.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
