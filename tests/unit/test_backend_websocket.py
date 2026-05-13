from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import services.backend.websocket.main as ws_main


class FakeSessionManager:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False
        self.session = SimpleNamespace(name="session")

    def context_session(self) -> FakeSessionManager:
        return self

    async def __aenter__(self) -> SimpleNamespace:
        self.entered = True
        return self.session

    async def __aexit__(self, *exc_info: object) -> None:
        self.exited = True


class FakeUserRepository:
    def __init__(self, session: SimpleNamespace) -> None:
        self.session = session

    async def get_by_id(self, user_id: object) -> SimpleNamespace:
        return SimpleNamespace(id=user_id, username="alice")


class WebsocketAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_ws_db_user_closes_db_session_after_lookup(self) -> None:
        user_id = uuid4()
        session_manager = FakeSessionManager()
        fake_redis = SimpleNamespace(name="redis")

        async def fake_get_user(
            access_token: str | None,
            redis: object,
        ) -> SimpleNamespace:
            self.assertEqual(access_token, "token")
            self.assertIs(redis, fake_redis)
            return SimpleNamespace(id=user_id)

        with (
            patch.object(ws_main, "get_user", fake_get_user),
            patch.object(ws_main, "session_manager", session_manager),
            patch.object(ws_main, "UserRepository", FakeUserRepository),
        ):
            user = await ws_main.get_ws_db_user(
                access_token="token",
                redis=fake_redis,
            )

        self.assertEqual(user.username, "alice")
        self.assertTrue(session_manager.entered)
        self.assertTrue(session_manager.exited)


if __name__ == "__main__":
    unittest.main()
