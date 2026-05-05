from __future__ import annotations

import unittest
from types import SimpleNamespace

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


class CoreStatsTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_stats_returns_current_core_counts(self) -> None:
        service = CoreServiceServicer(
            SimpleNamespace(),
            SimpleNamespace(queued_players_count=8, queued_lobbies_count=3),
            SimpleNamespace(active_games_count=4),
            SimpleNamespace(),
            FakeNotifier(),  # type: ignore[arg-type]
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
        service = StatsService(stub)  # type: ignore[arg-type]

        stats = await service.get()

        self.assertIsInstance(stub.request, pb.StatsReq)
        self.assertEqual(stats.online_users, 12)
        self.assertEqual(stats.available_players, 5)
        self.assertEqual(stats.queued_players, 8)
        self.assertEqual(stats.queued_lobbies, 3)
        self.assertEqual(stats.active_games, 4)


if __name__ == "__main__":
    unittest.main()
