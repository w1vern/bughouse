from __future__ import annotations

import argparse
import asyncio
import contextlib
import http.cookiejar
import json
import os
import random
import secrets
import ssl
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeAlias

import chess
import chess.variant
from dotenv import load_dotenv
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from shared.events import WsMsgType

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]
JsonPredicate: TypeAlias = Callable[[JsonObject], bool]


class ScenarioError(RuntimeError):
    pass


@dataclass(slots=True)
class HttpResponse:
    method: str
    url: str
    status: int
    body: JsonValue | str | None


@dataclass(slots=True)
class Timing:
    name: str
    seconds: float


@dataclass(slots=True)
class ScenarioResult:
    unit_id: int
    ok: bool
    seconds: float
    users: list[str]
    moves: int = 0
    error: str | None = None
    timings: list[Timing] = field(default_factory=list)


@dataclass(slots=True)
class E2EConfig:
    api_url: str
    ws_url: str
    clock_time_ms: int
    incr_ms: int
    moves: int
    timeout_s: float
    match_timeout_s: float
    run_id: str
    insecure_tls: bool
    seed: int
    touch_debug_endpoints: bool
    ws_connect_concurrency: int
    ws_connect_retries: int


@dataclass(slots=True)
class LoadConfig:
    games: int
    users: int
    concurrency: int
    ramp_delay_s: float


@dataclass(slots=True)
class UserCreds:
    username: str
    email: str
    password: str


@dataclass(slots=True)
class TestUser:
    creds: UserCreds
    http: HttpSession
    id: str | None = None


@dataclass(slots=True)
class PlayerSession:
    user: TestUser
    client: WsClient


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def _build_api_url() -> str:
    domain = os.environ.get("DOMAIN", "").strip()
    subdomain = os.environ.get("SUBDOMAIN", "bughouse").strip()
    if not domain:
        raise ScenarioError("DOMAIN is not set in .env")
    if not subdomain:
        raise ScenarioError("SUBDOMAIN is not set in .env")
    domain = domain.removeprefix("https://").removeprefix("http://").strip("/")
    return f"https://{subdomain}.{domain}/api"


def _build_ws_url(api_url: str) -> str:
    return f"{api_url.rstrip('/')}/ws".replace("https://", "wss://", 1).replace(
        "http://", "ws://", 1
    )


def _ssl_context(insecure_tls: bool) -> ssl.SSLContext | None:
    if not insecure_tls:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def load_config(args: argparse.Namespace) -> tuple[E2EConfig, LoadConfig]:
    env_file = Path(args.env_file)
    load_dotenv(dotenv_path=env_file, override=False)

    api_url = _build_api_url()
    run_id = args.run_id or os.getenv("LOADTEST_RUN_ID") or secrets.token_hex(4)
    seed = args.seed if args.seed is not None else _env_int("LOADTEST_SEED", 1)

    e2e = E2EConfig(
        api_url=api_url,
        ws_url=_build_ws_url(api_url),
        clock_time_ms=args.clock_time_ms
        if args.clock_time_ms is not None
        else _env_int("LOADTEST_CLOCK_TIME_MS", 60_000),
        incr_ms=args.incr_ms
        if args.incr_ms is not None
        else _env_int("LOADTEST_INCR_MS", 1_000),
        moves=args.moves
        if args.moves is not None
        else _env_int("LOADTEST_MOVES", 8),
        timeout_s=args.timeout
        if args.timeout is not None
        else _env_float("LOADTEST_TIMEOUT_S", 15.0),
        match_timeout_s=args.match_timeout
        if args.match_timeout is not None
        else _env_float("LOADTEST_MATCH_TIMEOUT_S", 30.0),
        run_id=run_id,
        insecure_tls=args.insecure_tls or _env_bool("LOADTEST_INSECURE_TLS"),
        seed=seed,
        touch_debug_endpoints=args.touch_debug_endpoints
        or _env_bool("LOADTEST_TOUCH_DEBUG_ENDPOINTS"),
        ws_connect_concurrency=args.connect_concurrency
        if args.connect_concurrency is not None
        else _env_int("LOADTEST_CONNECT_CONCURRENCY", 4),
        ws_connect_retries=args.connect_retries
        if args.connect_retries is not None
        else _env_int("LOADTEST_CONNECT_RETRIES", 3),
    )
    concurrency = (
        args.concurrency
        if args.concurrency is not None
        else _env_int("LOADTEST_CONCURRENCY", 1)
    )
    games = (
        args.games
        if args.games is not None
        else args.units
        if args.units is not None
        else _env_int("LOADTEST_GAMES", _env_int("LOADTEST_UNITS", 1))
    )
    default_users = max(4, min(games * 4, max(1, concurrency) * 4))
    users = (
        args.users
        if args.users is not None
        else _env_int("LOADTEST_USERS", default_users)
    )
    load = LoadConfig(
        games=games,
        users=users,
        concurrency=concurrency,
        ramp_delay_s=args.ramp_delay
        if args.ramp_delay is not None
        else _env_float("LOADTEST_RAMP_DELAY_S", 0.0),
    )
    if load.games <= 0:
        raise ScenarioError("games must be positive")
    if load.users < 4:
        raise ScenarioError("users must be at least 4")
    if load.concurrency <= 0:
        raise ScenarioError("concurrency must be positive")
    if e2e.clock_time_ms <= 0:
        raise ScenarioError("clock_time_ms must be positive")
    if e2e.incr_ms < 0:
        raise ScenarioError("incr_ms must be non-negative")
    if e2e.ws_connect_concurrency <= 0:
        raise ScenarioError("connect_concurrency must be positive")
    if e2e.ws_connect_retries <= 0:
        raise ScenarioError("connect_retries must be positive")
    return e2e, load


class HttpSession:
    def __init__(self, api_url: str, timeout_s: float, insecure_tls: bool) -> None:
        self._api_url = api_url.rstrip("/")
        self._timeout_s = timeout_s
        self._cookie_jar = http.cookiejar.CookieJar()
        handlers: list[urllib.request.BaseHandler] = [
            urllib.request.HTTPCookieProcessor(self._cookie_jar)
        ]
        context = _ssl_context(insecure_tls)
        if context is not None:
            handlers.append(urllib.request.HTTPSHandler(context=context))
        self._opener = urllib.request.build_opener(*handlers)

    def cookie_header(self) -> str:
        return "; ".join(f"{cookie.name}={cookie.value}" for cookie in self._cookie_jar)

    async def request(
        self,
        method: str,
        path: str,
        *,
        body: JsonObject | None = None,
        query: Mapping[str, str | int | bool | None] | None = None,
    ) -> HttpResponse:
        return await asyncio.to_thread(
            self._request_sync, method.upper(), path, body, query
        )

    async def expect(
        self,
        method: str,
        path: str,
        *,
        body: JsonObject | None = None,
        query: Mapping[str, str | int | bool | None] | None = None,
        statuses: Iterable[int] = (200,),
    ) -> HttpResponse:
        response = await self.request(method, path, body=body, query=query)
        expected = set(statuses)
        if response.status not in expected:
            raise ScenarioError(
                f"{method.upper()} {path} returned {response.status}, "
                f"expected {sorted(expected)}: {response.body}"
            )
        return response

    def _request_sync(
        self,
        method: str,
        path: str,
        body: JsonObject | None,
        query: Mapping[str, str | int | bool | None] | None,
    ) -> HttpResponse:
        url = f"{self._api_url}{path}"
        if query:
            clean_query = {k: v for k, v in query.items() if v is not None}
            url = f"{url}?{urllib.parse.urlencode(clean_query)}"

        payload: bytes | None = None
        headers = {"Accept": "application/json"}
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url=url,
            data=payload,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(request, timeout=self._timeout_s) as response:
                raw = response.read()
                return HttpResponse(method, url, response.status, _decode_body(raw))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            return HttpResponse(method, url, exc.code, _decode_body(raw))
        except urllib.error.URLError as exc:
            raise ScenarioError(f"{method} {url} failed: {exc.reason}") from exc


def _decode_body(raw: bytes) -> JsonValue | str | None:
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return text
    return value


class WsClient:
    def __init__(
        self,
        username: str,
        ws_url: str,
        cookie_header: str,
        timeout_s: float,
        insecure_tls: bool,
    ) -> None:
        self.username = username
        self._ws_url = ws_url
        self._cookie_header = cookie_header
        self._timeout_s = timeout_s
        self._ssl_context = _ssl_context(insecure_tls)
        self._conn: ClientConnection | None = None
        self._receiver: asyncio.Task[None] | None = None
        self._messages: asyncio.Queue[JsonObject] = asyncio.Queue()
        self._backlog: deque[JsonObject] = deque()

    async def connect(self) -> None:
        headers = {"Cookie": self._cookie_header}
        self._messages = asyncio.Queue()
        self._backlog = deque()
        kwargs: dict[str, Any] = {
            "additional_headers": headers,
            "open_timeout": self._timeout_s,
            "ping_interval": 20,
        }
        if self._ws_url.startswith("wss://") and self._ssl_context is not None:
            kwargs["ssl"] = self._ssl_context
        self._conn = await connect(self._ws_url, **kwargs)
        self._receiver = asyncio.create_task(
            self._recv_loop(), name=f"ws-recv-{self.username}"
        )

    async def close(self) -> None:
        receiver = self._receiver
        if receiver is not None:
            if not receiver.done():
                receiver.cancel()
            try:
                await receiver
            except (asyncio.CancelledError, ConnectionClosed):
                pass
            except Exception:
                pass
        if self._conn is not None:
            await self._conn.close()
        self._receiver = None
        self._conn = None

    async def send(self, msg_type: WsMsgType, data: JsonValue | None = None) -> None:
        conn = self._require_conn()
        payload: JsonObject = {"type": msg_type.value, "data": data or {}}
        await conn.send(json.dumps(payload, separators=(",", ":")))

    async def wait_for(
        self,
        msg_type: WsMsgType,
        *,
        timeout_s: float | None = None,
        predicate: JsonPredicate | None = None,
        allow_error: bool = False,
    ) -> JsonObject:
        deadline = time.monotonic() + (timeout_s if timeout_s is not None else self._timeout_s)
        while True:
            found = self._pop_backlog(msg_type, predicate, allow_error=allow_error)
            if found is not None:
                return found

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ScenarioError(
                    f"{self.username} timed out waiting for ws type {msg_type.value}"
                )
            self._raise_receiver_error()
            try:
                msg = await asyncio.wait_for(self._messages.get(), timeout=remaining)
            except TimeoutError as exc:
                raise ScenarioError(
                    f"{self.username} timed out waiting for ws type {msg_type.value}"
                ) from exc
            if self._is_error(msg) and not allow_error:
                raise ScenarioError(f"{self.username} received ws error: {msg['data']}")
            if self._matches(msg, msg_type, predicate):
                return msg
            self._backlog.append(msg)

    async def _recv_loop(self) -> None:
        conn = self._require_conn()
        try:
            while True:
                raw = await conn.recv()
                if not isinstance(raw, str):
                    continue
                msg = json.loads(raw)
                if isinstance(msg, dict):
                    self._messages.put_nowait(msg)
        except (asyncio.CancelledError, ConnectionClosed):
            raise
        except Exception as exc:
            self._messages.put_nowait(
                {"type": WsMsgType.ERROR.value, "data": {"code": "client", "message": str(exc)}}
            )

    def _require_conn(self) -> ClientConnection:
        if self._conn is None:
            raise ScenarioError(f"{self.username} websocket is not connected")
        return self._conn

    def _raise_receiver_error(self) -> None:
        task = self._receiver
        if task is None or not task.done() or task.cancelled():
            return
        exc = task.exception()
        if exc is not None and not isinstance(exc, ConnectionClosed):
            raise ScenarioError(f"{self.username} websocket receiver failed: {exc}") from exc

    def _pop_backlog(
        self,
        msg_type: WsMsgType,
        predicate: JsonPredicate | None,
        *,
        allow_error: bool,
    ) -> JsonObject | None:
        for index, msg in enumerate(self._backlog):
            if self._is_error(msg) and not allow_error:
                del self._backlog[index]
                raise ScenarioError(f"{self.username} received ws error: {msg['data']}")
            if self._matches(msg, msg_type, predicate):
                del self._backlog[index]
                return msg
        return None

    @staticmethod
    def _matches(
        msg: JsonObject,
        msg_type: WsMsgType,
        predicate: JsonPredicate | None,
    ) -> bool:
        if msg.get("type") != msg_type.value:
            return False
        return predicate is None or predicate(msg)

    @staticmethod
    def _is_error(msg: JsonObject) -> bool:
        return msg.get("type") == WsMsgType.ERROR.value


class UnitScenario:
    def __init__(self, unit_id: int, config: E2EConfig) -> None:
        self.unit_id = unit_id
        self.config = config
        self.rng = random.Random(config.seed + unit_id)
        self.timings: list[Timing] = []

    async def run(self) -> ScenarioResult:
        started = time.perf_counter()
        users = self._make_users()
        clients: list[WsClient] = []
        moves = 0
        try:
            await self._timed("register_and_login", self._register_and_login(users))
            await self._timed("http_preflight", self._probe_http_before_game(users))
            clients = await self._timed("websocket_connect", self._connect_ws(users))
            game_data = await self._timed("lobby_flow", self._run_lobby_flow(users, clients))
            moves = await self._timed("game_flow", self._run_game_flow(clients, game_data))
            await self._timed("http_after_game", self._probe_http_after_game(users))
            return ScenarioResult(
                unit_id=self.unit_id,
                ok=True,
                seconds=time.perf_counter() - started,
                users=[user.creds.username for user in users],
                moves=moves,
                timings=self.timings,
            )
        except Exception as exc:
            return ScenarioResult(
                unit_id=self.unit_id,
                ok=False,
                seconds=time.perf_counter() - started,
                users=[user.creds.username for user in users],
                moves=moves,
                error=str(exc),
                timings=self.timings,
            )
        finally:
            await asyncio.gather(*(client.close() for client in clients), return_exceptions=True)
            await self._cleanup(users)

    async def _timed[T](self, name: str, awaitable: Awaitable[T]) -> T:
        started = time.perf_counter()
        result = await awaitable
        self.timings.append(Timing(name=name, seconds=time.perf_counter() - started))
        return result

    def _make_users(self) -> list[TestUser]:
        token = f"{self.config.run_id}_{self.unit_id:05d}".replace("-", "_")
        password = f"Load-{secrets.token_urlsafe(12)}-1a"
        users: list[TestUser] = []
        for idx in range(4):
            username = f"lt_{token}_{idx}"
            users.append(
                TestUser(
                    creds=UserCreds(
                        username=username,
                        email=f"{username}@load.local",
                        password=password,
                    ),
                    http=HttpSession(
                        self.config.api_url,
                        self.config.timeout_s,
                        self.config.insecure_tls,
                    ),
                )
            )
        return users

    async def _register_and_login(self, users: list[TestUser]) -> None:
        await asyncio.gather(*(self._register_user(user) for user in users))
        await asyncio.sleep(0.2)
        await asyncio.gather(*(self._login_user(user) for user in users))

    async def _register_user(self, user: TestUser) -> None:
        creds = user.creds
        register_body: JsonObject = {
            "username": creds.username,
            "email": creds.email,
            "password": creds.password,
            "repeat_password": creds.password,
        }
        response = await user.http.request("POST", "/auth/register", body=register_body)
        if response.status not in {200, 409}:
            raise ScenarioError(
                f"register {creds.username} returned {response.status}: {response.body}"
            )

    async def _login_user(self, user: TestUser) -> None:
        creds = user.creds
        login_body: JsonObject = {"email": creds.email, "password": creds.password}
        response: HttpResponse | None = None
        for attempt in range(6):
            response = await user.http.request("POST", "/auth/login", body=login_body)
            if response.status == 200:
                break
            if response.status != 404 or attempt == 5:
                raise ScenarioError(
                    f"login {creds.username} returned {response.status}: {response.body}"
                )
            await asyncio.sleep(0.25 * (attempt + 1))
        if response is None or response.status != 200:
            raise ScenarioError(f"login {creds.username} failed")
        me = await user.http.expect("GET", "/users/me")
        if not isinstance(me.body, dict) or not isinstance(me.body.get("id"), str):
            raise ScenarioError(f"unexpected /users/me body for {creds.username}: {me.body}")
        user.id = me.body["id"]

    async def _probe_http_before_game(self, users: list[TestUser]) -> None:
        primary = users[0]
        assert primary.id is not None
        await primary.http.expect("GET", "/health")
        await primary.http.expect("GET", "/openapi.json")
        await primary.http.expect("GET", "/ws-docs.json")
        await primary.http.expect("POST", "/auth/refresh")
        await primary.http.expect("GET", "/stats")
        await primary.http.expect("GET", "/users/active")
        await primary.http.expect("GET", f"/users/{primary.id}")
        await primary.http.expect(
            "PATCH",
            f"/users/{primary.id}",
            body={
                "email": primary.creds.email,
                "username": primary.creds.username,
                "password": primary.creds.password,
                "repeat_password": primary.creds.password,
            },
        )
        await primary.http.expect("GET", "/games/count")
        await primary.http.expect("GET", "/games", query={"limit": 1, "offset": 0})
        if self.config.touch_debug_endpoints:
            await primary.http.expect(
                "PATCH",
                f"/users/add_active_player/lt_debug_{self.config.run_id}_{self.unit_id}",
                statuses=(200, 404),
            )

    async def _probe_http_after_game(self, users: list[TestUser]) -> None:
        primary = users[0]
        await primary.http.expect("GET", "/stats")
        await primary.http.expect("GET", "/games/count")
        games = await primary.http.expect("GET", "/games", query={"limit": 1, "offset": 0})
        if isinstance(games.body, list) and games.body:
            first = games.body[0]
            if isinstance(first, dict) and isinstance(first.get("id"), str):
                await primary.http.expect("GET", f"/games/{first['id']}")

    async def _connect_ws(self, users: list[TestUser]) -> list[WsClient]:
        clients = [
            WsClient(
                user.creds.username,
                self.config.ws_url,
                user.http.cookie_header(),
                self.config.timeout_s,
                self.config.insecure_tls,
            )
            for user in users
        ]
        semaphore = asyncio.Semaphore(self.config.ws_connect_concurrency)

        async def connect_one(client: WsClient) -> None:
            async with semaphore:
                attempts = self.config.ws_connect_retries
                last_error: Exception | None = None
                for attempt in range(attempts):
                    try:
                        await client.connect()
                        await client.wait_for(
                            WsMsgType.SYNC,
                            timeout_s=self.config.timeout_s,
                        )
                        return
                    except Exception as exc:
                        last_error = exc
                        await client.close()
                        if attempt + 1 < attempts:
                            await asyncio.sleep(0.5 * (attempt + 1))
                raise ScenarioError(
                    f"{client.username} ws connect failed after "
                    f"{attempts} attempts: {last_error}"
                ) from last_error

        try:
            await asyncio.gather(*(connect_one(client) for client in clients))
        except Exception:
            await asyncio.gather(
                *(client.close() for client in clients),
                return_exceptions=True,
            )
            raise
        return clients

    async def _run_lobby_flow(
        self,
        users: list[TestUser],
        clients: list[WsClient],
    ) -> JsonObject:
        leader = clients[0]
        pre_queue_clock = 7_200_000 + self.unit_id

        await leader.send(WsMsgType.PING)
        await leader.wait_for(WsMsgType.PONG)
        await leader.send(WsMsgType.REQ_SYNC)
        await leader.wait_for(WsMsgType.SYNC)

        await leader.send(
            WsMsgType.LOBBY_CREATE,
            {"clockTime": pre_queue_clock, "incr": self.config.incr_ms},
        )
        await leader.wait_for(WsMsgType.LOBBY_JOIN)

        await leader.send(WsMsgType.START_MM)
        await leader.wait_for(WsMsgType.LOBBY_START_MM)
        await leader.send(WsMsgType.CANCEL_MM)
        await leader.wait_for(WsMsgType.LOBBY_CANCEL_MM)
        await leader.send(
            WsMsgType.LOBBY_CONFIG,
            {
                "clockTime": self.config.clock_time_ms,
                "incr": self.config.incr_ms,
                "rated": False,
            },
        )
        await leader.wait_for(WsMsgType.LOBBY_CONFIG_UPDATE)

        await self._reject_invite(leader, clients[1], users[1].creds.username, 1)
        await self._accept_invite(leader, clients[1], users[1].creds.username, 1)
        await clients[1].send(WsMsgType.LOBBY_LEAVE)
        await leader.wait_for(
            WsMsgType.LOBBY_PLAYER_LEAVE,
            predicate=lambda msg: _data_field(msg, "idx") == 1,
        )
        await clients[1].send(WsMsgType.REQ_SYNC)
        await clients[1].wait_for(
            WsMsgType.SYNC,
            predicate=lambda msg: _data_field(msg, "state") == "IDLE",
        )

        await self._accept_invite(leader, clients[1], users[1].creds.username, 1)
        await leader.send(WsMsgType.LOBBY_KICK, users[1].creds.username)
        await clients[1].wait_for(WsMsgType.LOBBY_KICKED)
        await leader.wait_for(
            WsMsgType.LOBBY_PLAYER_LEAVE,
            predicate=lambda msg: _data_field(msg, "idx") == 1,
        )
        await clients[1].send(WsMsgType.REQ_SYNC)
        await clients[1].wait_for(
            WsMsgType.SYNC,
            predicate=lambda msg: _data_field(msg, "state") == "IDLE",
        )

        await self._accept_invite(leader, clients[1], users[1].creds.username, 1)
        await self._accept_invite(leader, clients[2], users[2].creds.username, 2)
        await self._accept_invite(leader, clients[3], users[3].creds.username, 3)

        await leader.send(WsMsgType.START_MM)
        game_messages = await asyncio.gather(
            *(
                client.wait_for(
                    WsMsgType.GAME_JOIN,
                    timeout_s=self.config.match_timeout_s,
                )
                for client in clients
            )
        )
        game_data = game_messages[0].get("data")
        if not isinstance(game_data, dict):
            raise ScenarioError(f"unexpected GAME_JOIN payload: {game_messages[0]}")
        return game_data

    async def _reject_invite(
        self,
        leader: WsClient,
        receiver: WsClient,
        receiver_username: str,
        idx: int,
    ) -> None:
        await leader.send(
            WsMsgType.INVITE_SEND,
            {"idx": idx, "username": receiver_username},
        )
        await receiver.wait_for(
            WsMsgType.INVITE_RECEIVE,
            predicate=lambda msg: _data_field(msg, "idx") == idx,
        )
        await receiver.send(WsMsgType.INVITE_REJECT, leader.username)
        await leader.wait_for(
            WsMsgType.LOBBY_INVITE_REJECTED,
            predicate=lambda msg: _data_field(msg, "idx") == idx,
        )

    async def _accept_invite(
        self,
        leader: WsClient,
        receiver: WsClient,
        receiver_username: str,
        idx: int,
    ) -> None:
        await leader.send(
            WsMsgType.INVITE_SEND,
            {"idx": idx, "username": receiver_username},
        )
        await receiver.wait_for(
            WsMsgType.INVITE_RECEIVE,
            predicate=lambda msg: _data_field(msg, "idx") == idx,
        )
        await receiver.send(WsMsgType.INVITE_ACCEPT, leader.username)
        await receiver.wait_for(WsMsgType.LOBBY_JOIN)
        await leader.wait_for(
            WsMsgType.LOBBY_PLAYER_JOIN,
            predicate=lambda msg: _data_field(msg, "idx") == idx,
        )

    async def _run_game_flow(self, clients: list[WsClient], game_data: JsonObject) -> int:
        await clients[0].send(WsMsgType.GAME_CHAT_MSG_SEND, "load test: ready")
        await clients[1].wait_for(
            WsMsgType.GAME_CHAT_MSG_RECEIVE,
            predicate=lambda msg: _data_field(msg, "username") == clients[0].username,
        )
        moves = await self._play_moves(clients, game_data)
        await clients[0].send(WsMsgType.GAME_RESIGN)
        await asyncio.gather(
            *(
                client.wait_for(
                    WsMsgType.GAME_END,
                    timeout_s=self.config.match_timeout_s,
                )
                for client in clients
            )
        )
        return moves

    async def _play_moves(self, clients: list[WsClient], game_data: JsonObject) -> int:
        boards_payload = game_data.get("boards")
        if not isinstance(boards_payload, list) or len(boards_payload) != 2:
            raise ScenarioError(f"unexpected boards payload: {boards_payload}")

        boards: list[chess.variant.CrazyhouseBoard] = []
        player_by_board_color: list[dict[chess.Color, str]] = []
        for board_payload in boards_payload:
            if not isinstance(board_payload, dict):
                raise ScenarioError(f"unexpected board payload: {board_payload}")
            fen = board_payload.get("fen")
            players = board_payload.get("players")
            if not isinstance(fen, str) or not isinstance(players, list):
                raise ScenarioError(f"unexpected board payload: {board_payload}")
            boards.append(chess.variant.CrazyhouseBoard(fen))
            player_by_board_color.append(_players_by_color(players))

        client_by_name = {client.username: client for client in clients}
        target_moves = max(0, self.config.moves)
        board_order = [0, 1, 0, 1]
        completed = 0

        while completed < target_moves:
            board_idx = board_order[completed] if completed < len(board_order) else completed % 2
            board = boards[board_idx]
            move = self._choose_move(board)
            if move is None:
                other_idx = 1 - board_idx
                board = boards[other_idx]
                move = self._choose_move(board)
                if move is None:
                    break
                board_idx = other_idx

            mover_name = player_by_board_color[board_idx][board.turn]
            mover = client_by_name[mover_name]
            move_uci = move.uci()
            await mover.send(WsMsgType.GAME_MOVE, {"idx": board_idx, "move": move_uci})

            observer = next(client for client in clients if client.username != mover_name)
            await observer.wait_for(
                WsMsgType.GAME_MOVE_RECEIVE,
                predicate=lambda msg, idx=board_idx, uci=move_uci: (
                    _data_field(msg, "idx") == idx and _data_field(msg, "move") == uci
                ),
            )
            board.push(move)
            completed += 1
        return completed

    def _choose_move(self, board: chess.variant.CrazyhouseBoard) -> chess.Move | None:
        legal = sorted(
            (move for move in board.legal_moves if move.drop is None),
            key=lambda move: move.uci(),
        )
        if not legal:
            return None
        quiet = [
            move
            for move in legal
            if not board.is_capture(move) and not board.gives_check(move)
        ]
        return self.rng.choice(quiet or legal)

    async def _cleanup(self, users: list[TestUser]) -> None:
        if not users:
            return
        cleanup_calls = [
            users[0].http.expect("POST", "/auth/logout", statuses=(200, 401)),
            users[1].http.expect("POST", "/auth/logout_all", statuses=(200, 401)),
        ]
        await asyncio.gather(*cleanup_calls, return_exceptions=True)


class QueueLoadRunner:
    def __init__(self, config: E2EConfig, load: LoadConfig) -> None:
        self.config = config
        self.load = load
        self._helper = UnitScenario(0, config)
        self._pool: asyncio.Queue[PlayerSession] = asyncio.Queue()
        self._pool_lock = asyncio.Lock()

    async def run(self) -> list[ScenarioResult]:
        users = self._make_users()
        clients: list[WsClient] = []
        setup_started = time.perf_counter()
        try:
            try:
                await self._helper._timed(  # noqa: SLF001
                    "register_and_login",
                    self._helper._register_and_login(users),  # noqa: SLF001
                )
                await self._helper._timed(  # noqa: SLF001
                    "http_preflight",
                    self._helper._probe_http_before_game(users),  # noqa: SLF001
                )
                clients = await self._helper._timed(  # noqa: SLF001
                    "websocket_connect",
                    self._helper._connect_ws(users),  # noqa: SLF001
                )
                sessions = [
                    PlayerSession(user=user, client=client)
                    for user, client in zip(users, clients)
                ]
                await self._helper._timed(  # noqa: SLF001
                    "solo_lobbies", self._create_solo_lobbies(sessions)
                )
                for session in sessions:
                    self._pool.put_nowait(session)
                setup_seconds = time.perf_counter() - setup_started
                print(
                    f"setup users={len(users)} sockets={len(clients)} "
                    f"seconds={setup_seconds:.2f}"
                )
            except Exception as exc:
                return [
                    ScenarioResult(
                        unit_id=-1,
                        ok=False,
                        seconds=time.perf_counter() - setup_started,
                        users=[user.creds.username for user in users],
                        error=f"setup failed: {exc}",
                        timings=self._helper.timings,
                    )
                ]
            results = await self._run_games()
            try:
                await self._helper._probe_http_after_game(users)  # noqa: SLF001
            except Exception as exc:
                print(f"post_game_probe failed: {exc}")
            return results
        finally:
            await asyncio.gather(
                *(client.close() for client in clients), return_exceptions=True
            )
            await asyncio.gather(
                *(
                    user.http.expect(
                        "POST", "/auth/logout_all", statuses=(200, 401)
                    )
                    for user in users
                ),
                return_exceptions=True,
            )

    def _make_users(self) -> list[TestUser]:
        token = f"{self.config.run_id}_pool".replace("-", "_")
        password = f"Load-{secrets.token_urlsafe(12)}-1a"
        users: list[TestUser] = []
        for idx in range(self.load.users):
            username = f"lt_{token}_{idx:05d}"
            users.append(
                TestUser(
                    creds=UserCreds(
                        username=username,
                        email=f"{username}@load.local",
                        password=password,
                    ),
                    http=HttpSession(
                        self.config.api_url,
                        self.config.timeout_s,
                        self.config.insecure_tls,
                    ),
                )
            )
        return users

    async def _create_solo_lobbies(self, sessions: list[PlayerSession]) -> None:
        async def create(session: PlayerSession) -> None:
            await session.client.send(
                WsMsgType.LOBBY_CREATE,
                {
                    "clockTime": self.config.clock_time_ms,
                    "incr": self.config.incr_ms,
                },
            )
            await session.client.wait_for(
                WsMsgType.LOBBY_JOIN,
                predicate=lambda msg, username=session.client.username: (
                    _data_field(msg, "leader") == username
                ),
            )

        await asyncio.gather(*(create(session) for session in sessions))

    async def _run_games(self) -> list[ScenarioResult]:
        results: list[ScenarioResult] = []
        next_game_id = 0
        max_games_per_wave = max(1, min(self.load.concurrency, self.load.users // 4))
        while next_game_id < self.load.games:
            if self.load.ramp_delay_s > 0 and next_game_id > 0:
                await asyncio.sleep(self.load.ramp_delay_s)
            wave_games = min(max_games_per_wave, self.load.games - next_game_id)
            players = await self._acquire_players(wave_games * 4)
            try:
                wave_results = await self._run_queued_wave(
                    first_game_id=next_game_id,
                    players=players,
                    expected_games=wave_games,
                )
                results.extend(wave_results)
                for result in wave_results:
                    status = "OK" if result.ok else "FAIL"
                    print(
                        f"[{status}] game={result.unit_id} seconds={result.seconds:.2f} "
                        f"moves={result.moves} users={','.join(result.users)}"
                    )
                    if result.error:
                        print(f"      error={result.error}")
                if any(not result.ok for result in wave_results):
                    break
            finally:
                await self._release_players(players)
            next_game_id += wave_games
        return sorted(results, key=lambda item: item.unit_id)

    async def _acquire_players(self, count: int) -> list[PlayerSession]:
        async with self._pool_lock:
            return [await self._pool.get() for _ in range(count)]

    async def _release_players(self, players: list[PlayerSession]) -> None:
        for player in players:
            self._pool.put_nowait(player)

    async def _run_queued_wave(
        self,
        first_game_id: int,
        players: list[PlayerSession],
        expected_games: int,
    ) -> list[ScenarioResult]:
        wave_started = time.perf_counter()
        clients = [player.client for player in players]
        lobby_started = time.perf_counter()
        try:
            await self._wait_players_lobby_idle(clients)
            lobby_timing = Timing(
                name="lobby_ready",
                seconds=time.perf_counter() - lobby_started,
            )
            matchmaking_started = time.perf_counter()
            matched_games = await self._start_solo_matches(players, expected_games)
            matchmaking_timing = Timing(
                name="matchmaking",
                seconds=time.perf_counter() - matchmaking_started,
            )
        except Exception as exc:
            await self._recover_players(clients)
            return [
                ScenarioResult(
                    unit_id=first_game_id + offset,
                    ok=False,
                    seconds=time.perf_counter() - wave_started,
                    users=[
                        player.client.username
                        for player in players[offset * 4:(offset + 1) * 4]
                    ],
                    error=str(exc),
                    timings=[],
                )
                for offset in range(expected_games)
            ]

        async def run_matched(
            offset: int,
            group_players: list[PlayerSession],
            game_data: JsonObject,
        ) -> ScenarioResult:
            return await self._run_matched_game(
                game_id=first_game_id + offset,
                players=group_players,
                game_data=game_data,
                started=wave_started,
                initial_timings=[lobby_timing, matchmaking_timing],
            )

        return await asyncio.gather(
            *(
                run_matched(offset, group_players, game_data)
                for offset, (group_players, game_data) in enumerate(matched_games)
            )
        )

    async def _start_solo_matches(
        self,
        players: list[PlayerSession],
        expected_games: int,
    ) -> list[tuple[list[PlayerSession], JsonObject]]:
        clients = [player.client for player in players]
        await asyncio.gather(*(client.send(WsMsgType.START_MM) for client in clients))
        await asyncio.gather(
            *(
                client.wait_for(WsMsgType.LOBBY_START_MM, timeout_s=self.config.timeout_s)
                for client in clients
            )
        )
        messages = await asyncio.gather(
            *(
                client.wait_for(
                    WsMsgType.GAME_JOIN,
                    timeout_s=self.config.match_timeout_s,
                )
                for client in clients
            )
        )
        players_by_name = {player.client.username: player for player in players}
        expected_usernames = set(players_by_name)
        games_by_users: dict[frozenset[str], JsonObject] = {}
        message_counts: dict[frozenset[str], int] = {}

        for msg in messages:
            game_data = msg.get("data")
            if not isinstance(game_data, dict):
                raise ScenarioError(f"unexpected GAME_JOIN payload: {msg}")
            usernames = frozenset(_game_usernames(game_data))
            if len(usernames) != 4:
                raise ScenarioError(f"unexpected queued game users: {sorted(usernames)}")
            if not usernames <= expected_usernames:
                raise ScenarioError(
                    f"queued game matched external users: expected subset of "
                    f"{sorted(expected_usernames)}, actual={sorted(usernames)}"
                )
            games_by_users[usernames] = game_data
            message_counts[usernames] = message_counts.get(usernames, 0) + 1

        if len(games_by_users) != expected_games:
            raise ScenarioError(
                f"expected {expected_games} queued games, got {len(games_by_users)}"
            )
        bad_counts = {
            tuple(sorted(usernames)): count
            for usernames, count in message_counts.items()
            if count != 4
        }
        if bad_counts:
            raise ScenarioError(f"incomplete GAME_JOIN fanout: {bad_counts}")

        return [
            ([players_by_name[username] for username in sorted(usernames)], game_data)
            for usernames, game_data in games_by_users.items()
        ]

    async def _run_matched_game(
        self,
        game_id: int,
        players: list[PlayerSession],
        game_data: JsonObject,
        started: float,
        initial_timings: list[Timing],
    ) -> ScenarioResult:
        clients = [player.client for player in players]
        usernames = [client.username for client in clients]
        timings = list(initial_timings)
        moves = 0

        async def timed[T](name: str, awaitable: Awaitable[T]) -> T:
            phase_started = time.perf_counter()
            result = await awaitable
            timings.append(Timing(name=name, seconds=time.perf_counter() - phase_started))
            return result

        try:
            moves = await timed("game_flow", self._run_game_flow(game_id, clients, game_data))
            await timed("return_to_lobby", self._wait_players_lobby_idle(clients))
            return ScenarioResult(
                unit_id=game_id,
                ok=True,
                seconds=time.perf_counter() - started,
                users=usernames,
                moves=moves,
                timings=timings,
            )
        except Exception as exc:
            await self._recover_players(clients)
            return ScenarioResult(
                unit_id=game_id,
                ok=False,
                seconds=time.perf_counter() - started,
                users=usernames,
                moves=moves,
                error=str(exc),
                timings=timings,
            )

    async def _run_game_flow(
        self,
        game_id: int,
        clients: list[WsClient],
        game_data: JsonObject,
    ) -> int:
        rng = random.Random(self.config.seed + game_id)
        await self._send_team_chat(clients)
        moves = await self._play_moves(clients, game_data, rng)
        await clients[0].send(WsMsgType.GAME_RESIGN)
        await asyncio.gather(
            *(
                client.wait_for(
                    WsMsgType.GAME_END,
                    timeout_s=self.config.match_timeout_s,
                )
                for client in clients
            )
        )
        return moves

    async def _send_team_chat(self, clients: list[WsClient]) -> None:
        sender = clients[0]
        await sender.send(WsMsgType.GAME_CHAT_MSG_SEND, "load test: ready")
        tasks = [
            asyncio.create_task(
                client.wait_for(
                    WsMsgType.GAME_CHAT_MSG_RECEIVE,
                    timeout_s=min(3.0, self.config.timeout_s),
                    predicate=lambda msg, username=sender.username: (
                        _data_field(msg, "username") == username
                    ),
                )
            )
            for client in clients[1:]
        ]
        done, pending = await asyncio.wait(
            tasks,
            timeout=min(3.0, self.config.timeout_s),
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            try:
                task.result()
                return
            except Exception:
                continue
        raise ScenarioError("team chat was not delivered to any teammate")

    async def _play_moves(
        self,
        clients: list[WsClient],
        game_data: JsonObject,
        rng: random.Random,
    ) -> int:
        boards_payload = game_data.get("boards")
        if not isinstance(boards_payload, list) or len(boards_payload) != 2:
            raise ScenarioError(f"unexpected boards payload: {boards_payload}")

        boards: list[chess.variant.CrazyhouseBoard] = []
        player_by_board_color: list[dict[chess.Color, str]] = []
        for board_payload in boards_payload:
            if not isinstance(board_payload, dict):
                raise ScenarioError(f"unexpected board payload: {board_payload}")
            fen = board_payload.get("fen")
            players = board_payload.get("players")
            if not isinstance(fen, str) or not isinstance(players, list):
                raise ScenarioError(f"unexpected board payload: {board_payload}")
            boards.append(chess.variant.CrazyhouseBoard(fen))
            player_by_board_color.append(_players_by_color(players))

        client_by_name = {client.username: client for client in clients}
        completed = 0
        while completed < max(0, self.config.moves):
            board_idx = completed % 2
            board = boards[board_idx]
            move = _choose_move(board, rng)
            if move is None:
                other_idx = 1 - board_idx
                board = boards[other_idx]
                move = _choose_move(board, rng)
                if move is None:
                    break
                board_idx = other_idx

            mover_name = player_by_board_color[board_idx][board.turn]
            mover = client_by_name[mover_name]
            move_uci = move.uci()
            await mover.send(WsMsgType.GAME_MOVE, {"idx": board_idx, "move": move_uci})

            observer = next(client for client in clients if client.username != mover_name)
            await observer.wait_for(
                WsMsgType.GAME_MOVE_RECEIVE,
                predicate=lambda msg, idx=board_idx, uci=move_uci: (
                    _data_field(msg, "idx") == idx and _data_field(msg, "move") == uci
                ),
            )
            board.push(move)
            completed += 1
        return completed

    async def _wait_players_lobby_idle(self, clients: list[WsClient]) -> None:
        await asyncio.gather(*(self._wait_lobby_idle(client) for client in clients))

    async def _wait_lobby_idle(self, client: WsClient) -> None:
        for attempt in range(8):
            await client.send(WsMsgType.REQ_SYNC)
            msg = await client.wait_for(WsMsgType.SYNC, timeout_s=self.config.timeout_s)
            data = msg.get("data")
            if isinstance(data, dict) and data.get("state") == "LOBBY":
                lobby = data.get("lobby")
                if isinstance(lobby, dict) and lobby.get("inQueue") is False:
                    return
            await asyncio.sleep(0.1 * (attempt + 1))
        raise ScenarioError(f"{client.username} did not return to idle lobby")

    async def _recover_players(self, clients: list[WsClient]) -> None:
        async def recover(client: WsClient) -> None:
            try:
                await client.send(WsMsgType.REQ_SYNC)
                msg = await client.wait_for(WsMsgType.SYNC, timeout_s=3.0)
                data = msg.get("data")
                if not isinstance(data, dict):
                    return
                if data.get("state") == "GAME":
                    await client.send(WsMsgType.GAME_RESIGN)
                elif data.get("state") == "LOBBY":
                    lobby = data.get("lobby")
                    if isinstance(lobby, dict) and lobby.get("inQueue") is True:
                        await client.send(WsMsgType.CANCEL_MM)
            except Exception:
                return

        await asyncio.gather(*(recover(client) for client in clients))


def _data_field(msg: JsonObject, key: str) -> JsonValue:
    data = msg.get("data")
    if isinstance(data, dict):
        return data.get(key)
    return None


def _players_by_color(players: list[JsonValue]) -> dict[chess.Color, str]:
    out: dict[chess.Color, str] = {}
    for player in players:
        if not isinstance(player, dict):
            continue
        name = player.get("name")
        color = player.get("color")
        if isinstance(name, str) and color == "white":
            out[chess.WHITE] = name
        elif isinstance(name, str) and color == "black":
            out[chess.BLACK] = name
    if chess.WHITE not in out or chess.BLACK not in out:
        raise ScenarioError(f"cannot map players by color: {players}")
    return out


def _game_usernames(game_data: JsonObject) -> set[str]:
    boards = game_data.get("boards")
    names: set[str] = set()
    if not isinstance(boards, list):
        return names
    for board in boards:
        if not isinstance(board, dict):
            continue
        players = board.get("players")
        if not isinstance(players, list):
            continue
        for player in players:
            if isinstance(player, dict) and isinstance(player.get("name"), str):
                names.add(player["name"])
    return names


def _choose_move(
    board: chess.variant.CrazyhouseBoard,
    rng: random.Random,
) -> chess.Move | None:
    legal = sorted(
        (move for move in board.legal_moves if move.drop is None),
        key=lambda move: move.uci(),
    )
    if not legal:
        return None
    quiet = [
        move
        for move in legal
        if not board.is_capture(move) and not board.gives_check(move)
    ]
    return rng.choice(quiet or legal)


async def run_single(config: E2EConfig) -> ScenarioResult:
    return await UnitScenario(0, config).run()


async def run_load(config: E2EConfig, load: LoadConfig) -> list[ScenarioResult]:
    return await QueueLoadRunner(config, load).run()


def print_summary(results: list[ScenarioResult]) -> None:
    ok = [result for result in results if result.ok]
    failed = [result for result in results if not result.ok]
    durations = [result.seconds for result in results]
    print("")
    print("Summary")
    print(f"  runs: {len(results)}")
    print(f"  ok: {len(ok)}")
    print(f"  failed: {len(failed)}")
    if durations:
        print(f"  min: {min(durations):.2f}s")
        print(f"  avg: {statistics.fmean(durations):.2f}s")
        print(f"  max: {max(durations):.2f}s")
    phase_names = sorted({timing.name for result in results for timing in result.timings})
    if phase_names:
        print("")
        print("Phases")
        for name in phase_names:
            values = [
                timing.seconds
                for result in results
                for timing in result.timings
                if timing.name == name
            ]
            print(
                f"  {name}: avg={statistics.fmean(values):.2f}s "
                f"max={max(values):.2f}s"
            )
    if failed:
        print("")
        print("Failures")
        for result in failed:
            print(f"  unit {result.unit_id}: {result.error}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="E2E and load test runner for the deployed Bughouse backend."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(target: argparse.ArgumentParser) -> None:
        target.add_argument("--env-file", default=".env")
        target.add_argument("--run-id")
        target.add_argument("--seed", type=int)
        target.add_argument("--clock-time-ms", type=int)
        target.add_argument("--incr-ms", type=int)
        target.add_argument("--moves", type=int)
        target.add_argument("--timeout", type=float)
        target.add_argument("--match-timeout", type=float)
        target.add_argument("--insecure-tls", action="store_true")
        target.add_argument("--touch-debug-endpoints", action="store_true")
        target.add_argument("--connect-concurrency", type=int)
        target.add_argument("--connect-retries", type=int)

    single = subparsers.add_parser("single", help="run one full e2e scenario")
    add_common(single)
    single.set_defaults(games=1, users=4, units=None, concurrency=1, ramp_delay=0.0)

    load = subparsers.add_parser("load", help="run queued solo-player games")
    add_common(load)
    load.add_argument("--games", type=int, help="total games to complete")
    load.add_argument("--users", type=int, help="registered WebSocket users in the pool")
    load.add_argument("--units", type=int, help="deprecated alias for --games")
    load.add_argument("--concurrency", type=int)
    load.add_argument("--ramp-delay", type=float)

    return parser


async def async_main(args: argparse.Namespace) -> int:
    e2e_config, load_config_value = load_config(args)
    print(f"target api: {e2e_config.api_url}")
    print(f"target ws:  {e2e_config.ws_url}")

    if args.command == "single":
        result = await run_single(e2e_config)
        print_summary([result])
        return 0 if result.ok else 1

    print(
        f"load games={load_config_value.games} users={load_config_value.users} "
        f"concurrency={load_config_value.concurrency} "
        f"connect_concurrency={e2e_config.ws_connect_concurrency}"
    )
    results = await run_load(e2e_config, load_config_value)
    print_summary(results)
    return 0 if all(result.ok for result in results) else 1


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(async_main(args)))
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
