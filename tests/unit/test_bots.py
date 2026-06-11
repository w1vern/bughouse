from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from shared.infrastructure import BotConfig

from services.core.bots import BotRegistry
from services.core.invites import InviteManager
from services.core.lobby.errors import (
    ERR_BOT_ALREADY_SEATED,
    ERR_INVITE_TARGET_OFFLINE,
    ERR_RATED_WITH_BOT,
    LobbyError,
)
from services.core.lobby.manager import LobbyManager
from services.core.lobby.models import Lobby, LobbyConfig, LobbyState, Seat
from services.core.queue.errors import (
    ERR_BOTS_REQUIRE_FULL_LOBBY,
    ERR_BOTS_UNRATED_ONLY,
    QueueError,
)
from services.core.queue.manager import QueueManager
from shared.infrastructure import RankingParams


def ranking_params() -> RankingParams:
    return RankingParams(mu=25.0, sigma=8.333, beta=4.166, tau=0.083, epsilon=0.0)


def registry() -> BotRegistry:
    return BotRegistry([
        BotConfig(name="bot1", skill_level=3, mu=1500.0, sigma=350.0),
        BotConfig(name="bot2", skill_level=10, mu=1800.0, sigma=300.0),
    ])


def make_user(username: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), username=username, rating=25.0, sigma=8.333,
        color=0, is_bot=False,
    )


class FakeUserRepoFactory:
    def __init__(self, users: dict[str, SimpleNamespace]) -> None:
        self.users = users

    def __call__(self) -> "FakeUserRepoFactory":
        return self

    async def __aenter__(self) -> "FakeUserRepoFactory":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def get_by_username(self, username: str) -> SimpleNamespace | None:
        return self.users.get(username)


class FakeQueueLobbyManager:
    def __init__(self) -> None:
        self.in_queue: list[UUID] = []
        self._lobbies: dict[UUID, Lobby] = {}

    def get(self, lobby_id: UUID) -> Lobby | None:
        return self._lobbies.get(lobby_id)

    def mark_in_queue(self, lobby_id: UUID) -> None:
        self.in_queue.append(lobby_id)

    def mark_idle(self, lobby_id: UUID) -> None:
        pass

    def mark_in_game(self, lobby_id: UUID) -> None:
        pass


def bot_lobby(seats: list[Seat | None], *, rated: bool = False) -> Lobby:
    return Lobby(
        id=uuid4(),
        leader="alice",
        seats=seats,
        config=LobbyConfig(clock_time=60_000, incr=1_000, rated=rated),
        state=LobbyState.IDLE,
    )


class LobbyBotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.users = {"alice": make_user("alice"), "bob": make_user("bob")}
        self.repo = FakeUserRepoFactory(self.users)
        self.notifier = AsyncMock()
        self.manager = LobbyManager(
            notifier=self.notifier,  # type: ignore[arg-type]
            user_repo_factory=self.repo,  # type: ignore[arg-type]
            bots=registry(),
        )

    async def test_add_bot_seats_from_env_without_busy_bookkeeping(self) -> None:
        lobby = await self.manager.create("alice")

        await self.manager.add_bot(lobby.id, "bot1", 1)

        seat = lobby.seats[1]
        assert seat is not None
        self.assertEqual(seat.username, "bot1")
        self.assertTrue(seat.is_bot)
        self.assertEqual(seat.rating, 1500.0)  # from env mu
        self.assertNotIn("bot1", self.manager._user_to_lobby)

    async def test_same_bot_in_two_lobbies_at_once(self) -> None:
        lobby_a = await self.manager.create("alice")
        lobby_b = await self.manager.create("bob")

        await self.manager.add_bot(lobby_a.id, "bot1", 1)
        await self.manager.add_bot(lobby_b.id, "bot1", 1)

        self.assertEqual(lobby_a.seats[1].username, "bot1")  # type: ignore[union-attr]
        self.assertEqual(lobby_b.seats[1].username, "bot1")  # type: ignore[union-attr]

    async def test_add_bot_rejects_duplicate_in_one_lobby(self) -> None:
        lobby = await self.manager.create("alice")
        await self.manager.add_bot(lobby.id, "bot1", 1)

        with self.assertRaises(LobbyError) as err:
            await self.manager.add_bot(lobby.id, "bot1", 2)

        self.assertEqual(err.exception.code, ERR_BOT_ALREADY_SEATED)

    async def test_add_bot_rejected_in_rated_lobby(self) -> None:
        lobby = await self.manager.create("alice")
        lobby.config.rated = True

        with self.assertRaises(LobbyError) as err:
            await self.manager.add_bot(lobby.id, "bot1", 1)

        self.assertEqual(err.exception.code, ERR_RATED_WITH_BOT)

    async def test_kick_removes_bot_keeps_lobby(self) -> None:
        lobby = await self.manager.create("alice")
        await self.manager.add_bot(lobby.id, "bot1", 1)

        await self.manager.kick("alice", "bot1")

        self.assertIsNone(lobby.seats[1])
        self.assertIsNotNone(self.manager.get(lobby.id))

    async def test_lobby_dissolves_when_last_human_leaves(self) -> None:
        lobby = await self.manager.create("alice")
        await self.manager.add_bot(lobby.id, "bot1", 1)
        await self.manager.add_bot(lobby.id, "bot2", 2)

        result = await self.manager.leave("alice")

        self.assertIsNone(result)
        self.assertIsNone(self.manager.get(lobby.id))

    async def test_evict_bot_from_all_idle_lobbies(self) -> None:
        lobby_a = await self.manager.create("alice")
        lobby_b = await self.manager.create("bob")
        await self.manager.add_bot(lobby_a.id, "bot1", 1)
        await self.manager.add_bot(lobby_b.id, "bot1", 1)

        await self.manager.evict_bot_from_all_lobbies("bot1")

        self.assertIsNone(lobby_a.seats[1])
        self.assertIsNone(lobby_b.seats[1])


class InviteBotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.users = {"alice": make_user("alice")}
        self.repo = FakeUserRepoFactory(self.users)
        self.notifier = AsyncMock()
        self.lobbies = LobbyManager(
            notifier=self.notifier,  # type: ignore[arg-type]
            user_repo_factory=self.repo,  # type: ignore[arg-type]
            bots=registry(),
        )
        self.games = SimpleNamespace(get_game_by_user=lambda _u: None)
        self.redis = AsyncMock()
        # bot1 enabled (in active_player), bot2 not.
        self.redis.sismember = AsyncMock(
            side_effect=lambda _key, name: name == "bot1")
        self.redis.exists = AsyncMock(return_value=0)
        self.invites = InviteManager(
            lobbies=self.lobbies,
            games=self.games,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
            redis=self.redis,
            bots=registry(),
        )

    async def test_invite_enabled_bot_auto_seats_without_accept(self) -> None:
        lobby = await self.lobbies.create("alice")

        await self.invites.send("alice", "bot1", 1)

        seat = lobby.seats[1]
        assert seat is not None
        self.assertEqual(seat.username, "bot1")
        self.assertTrue(seat.is_bot)
        self.assertEqual(self.invites._invites, {})

    async def test_invite_disabled_bot_falls_through_to_offline(self) -> None:
        await self.lobbies.create("alice")

        with self.assertRaises(LobbyError) as err:
            await self.invites.send("alice", "bot2", 1)

        self.assertEqual(err.exception.code, ERR_INVITE_TARGET_OFFLINE)


class QueueBotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # has_bot is driven by Seat.is_bot, so the repo only needs humans here.
        self.users = {
            "alice": make_user("alice"),
            "carol": make_user("carol"),
        }
        self.repo = FakeUserRepoFactory(self.users)
        self.lobby_mgr = FakeQueueLobbyManager()
        self.notifier = AsyncMock()
        self.game_mgr = AsyncMock()
        self.game_mgr.create_game = AsyncMock(return_value=uuid4())
        self.manager = QueueManager(
            lobby_mgr=self.lobby_mgr,  # type: ignore[arg-type]
            game_mgr=self.game_mgr,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
            user_repo_factory=self.repo,  # type: ignore[arg-type]
            tick=999_000.0,
            ranking=ranking_params(),
            bots=registry(),
        )

    async def asyncTearDown(self) -> None:
        await self.manager.stop_loop()

    async def test_enqueue_rejects_partial_lobby_with_bot(self) -> None:
        lobby = bot_lobby([
            Seat("alice", 25.0), Seat("bot1", 1500.0, True),
            Seat("carol", 25.0), None,
        ])

        with self.assertRaises(QueueError) as err:
            await self.manager.enqueue(lobby)

        self.assertEqual(err.exception.code, ERR_BOTS_REQUIRE_FULL_LOBBY)

    async def test_enqueue_rejects_rated_full_lobby_with_bot(self) -> None:
        lobby = bot_lobby(
            [
                Seat("alice", 25.0), Seat("bot1", 1500.0, True),
                Seat("carol", 25.0), Seat("bot2", 1800.0, True),
            ],
            rated=True,
        )

        with self.assertRaises(QueueError) as err:
            await self.manager.enqueue(lobby)

        self.assertEqual(err.exception.code, ERR_BOTS_UNRATED_ONLY)

    async def test_enqueue_allows_full_unrated_lobby_with_bots(self) -> None:
        lobby = bot_lobby([
            Seat("alice", 25.0), Seat("bot1", 1500.0, True),
            Seat("carol", 25.0), Seat("bot2", 1800.0, True),
        ])

        await self.manager.enqueue(lobby)

        self.assertIsNotNone(self.manager.get(lobby.id))
        self.assertEqual(self.lobby_mgr.in_queue, [lobby.id])


if __name__ == "__main__":
    unittest.main()
