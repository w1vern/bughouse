from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

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


def make_user(
    username: str,
    *,
    is_bot: bool = False,
    enabled: bool = False,
    rating: float = 25.0,
    sigma: float = 8.333,
    color: int = 0,
) -> SimpleNamespace:
    bot = SimpleNamespace(enabled=enabled) if is_bot else None
    return SimpleNamespace(
        id=uuid4(),
        username=username,
        rating=rating,
        sigma=sigma,
        color=color,
        is_bot=is_bot,
        bot=bot,
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

    def register(self, lobby: Lobby) -> None:
        self._lobbies[lobby.id] = lobby

    def get(self, lobby_id: UUID) -> Lobby | None:
        return self._lobbies.get(lobby_id)

    def mark_in_queue(self, lobby_id: UUID) -> None:
        self.in_queue.append(lobby_id)

    def mark_idle(self, lobby_id: UUID) -> None:
        pass

    def mark_in_game(self, lobby_id: UUID) -> None:
        pass


def bot_lobby(
    seats: list[Seat | None],
    *,
    rated: bool = False,
    leader: str = "alice",
) -> Lobby:
    return Lobby(
        id=uuid4(),
        leader=leader,
        seats=seats,
        config=LobbyConfig(clock_time=60_000, incr=1_000, rated=rated),
        state=LobbyState.IDLE,
    )


class LobbyBotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.users = {
            "alice": make_user("alice"),
            "bob": make_user("bob"),
            "bot1": make_user("bot1", is_bot=True, enabled=True),
            "bot2": make_user("bot2", is_bot=True, enabled=True),
        }
        self.repo = FakeUserRepoFactory(self.users)
        self.notifier = AsyncMock()
        self.manager = LobbyManager(
            notifier=self.notifier,  # type: ignore[arg-type]
            user_repo_factory=self.repo,  # type: ignore[arg-type]
        )

    async def test_add_bot_seats_a_bot_without_busy_bookkeeping(self) -> None:
        lobby = await self.manager.create("alice")

        await self.manager.add_bot(lobby.id, "bot1", 1)

        seat = lobby.seats[1]
        self.assertIsNotNone(seat)
        assert seat is not None
        self.assertEqual(seat.username, "bot1")
        self.assertTrue(seat.is_bot)
        # Bots never enter the single-lobby map.
        self.assertNotIn("bot1", self.manager._user_to_lobby)

    async def test_same_bot_can_be_seated_in_two_lobbies_at_once(self) -> None:
        lobby_a = await self.manager.create("alice")
        lobby_b = await self.manager.create("bob")

        await self.manager.add_bot(lobby_a.id, "bot1", 1)
        await self.manager.add_bot(lobby_b.id, "bot1", 1)

        self.assertEqual(lobby_a.seats[1].username, "bot1")  # type: ignore[union-attr]
        self.assertEqual(lobby_b.seats[1].username, "bot1")  # type: ignore[union-attr]

    async def test_add_bot_rejects_same_bot_twice_in_one_lobby(self) -> None:
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

    async def test_kick_removes_a_bot_seat(self) -> None:
        lobby = await self.manager.create("alice")
        await self.manager.add_bot(lobby.id, "bot1", 1)

        await self.manager.kick("alice", "bot1")

        self.assertIsNone(lobby.seats[1])
        # The lobby survives — its human leader is still seated.
        self.assertIsNotNone(self.manager.get(lobby.id))

    async def test_lobby_dissolves_when_last_human_leaves_even_with_bots(self) -> None:
        lobby = await self.manager.create("alice")
        await self.manager.add_bot(lobby.id, "bot1", 1)
        await self.manager.add_bot(lobby.id, "bot2", 2)

        result = await self.manager.leave("alice")

        self.assertIsNone(result)
        self.assertIsNone(self.manager.get(lobby.id))


class InviteBotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.users = {
            "alice": make_user("alice"),
            "bot1": make_user("bot1", is_bot=True, enabled=True),
            "bot_off": make_user("bot_off", is_bot=True, enabled=False),
        }
        self.repo = FakeUserRepoFactory(self.users)
        self.notifier = AsyncMock()
        self.lobbies = LobbyManager(
            notifier=self.notifier,  # type: ignore[arg-type]
            user_repo_factory=self.repo,  # type: ignore[arg-type]
        )
        self.games = SimpleNamespace(get_game_by_user=lambda _u: None)
        self.redis = AsyncMock()
        self.redis.exists = AsyncMock(return_value=0)
        self.invites = InviteManager(
            lobbies=self.lobbies,
            games=self.games,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
            redis=self.redis,
            user_repo_factory=self.repo,  # type: ignore[arg-type]
        )

    async def test_invite_to_enabled_bot_auto_seats_without_accept(self) -> None:
        lobby = await self.lobbies.create("alice")

        await self.invites.send("alice", "bot1", 1)

        seat = lobby.seats[1]
        self.assertIsNotNone(seat)
        assert seat is not None
        self.assertEqual(seat.username, "bot1")
        self.assertTrue(seat.is_bot)
        # No pending invite was stored — the bot is seated immediately.
        self.assertEqual(self.invites._invites, {})

    async def test_invite_to_disabled_bot_falls_through_to_offline(self) -> None:
        await self.lobbies.create("alice")

        with self.assertRaises(LobbyError) as err:
            await self.invites.send("alice", "bot_off", 1)

        self.assertEqual(err.exception.code, ERR_INVITE_TARGET_OFFLINE)


class QueueBotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.users = {
            "alice": make_user("alice"),
            "carol": make_user("carol"),
            "bot1": make_user("bot1", is_bot=True, enabled=True),
            "bot2": make_user("bot2", is_bot=True, enabled=True),
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
        )

    async def asyncTearDown(self) -> None:
        await self.manager.stop_loop()

    async def test_enqueue_rejects_partial_lobby_with_bot(self) -> None:
        lobby = bot_lobby([
            Seat("alice", 25.0), Seat("bot1", 25.0, True), Seat("carol", 25.0), None,
        ])

        with self.assertRaises(QueueError) as err:
            await self.manager.enqueue(lobby)

        self.assertEqual(err.exception.code, ERR_BOTS_REQUIRE_FULL_LOBBY)

    async def test_enqueue_rejects_rated_full_lobby_with_bot(self) -> None:
        lobby = bot_lobby(
            [
                Seat("alice", 25.0), Seat("bot1", 25.0, True),
                Seat("carol", 25.0), Seat("bot2", 25.0, True),
            ],
            rated=True,
        )

        with self.assertRaises(QueueError) as err:
            await self.manager.enqueue(lobby)

        self.assertEqual(err.exception.code, ERR_BOTS_UNRATED_ONLY)

    async def test_enqueue_allows_full_unrated_lobby_with_bots(self) -> None:
        lobby = bot_lobby([
            Seat("alice", 25.0), Seat("bot1", 25.0, True),
            Seat("carol", 25.0), Seat("bot2", 25.0, True),
        ])

        await self.manager.enqueue(lobby)

        self.assertIsNotNone(self.manager.get(lobby.id))
        self.assertEqual(self.lobby_mgr.in_queue, [lobby.id])


if __name__ == "__main__":
    unittest.main()
