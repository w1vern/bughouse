# Bughouse E2E Load Test

The runner uses the deployed backend as a frontend substitute:

- registers and logs in a configurable pool of users;
- touches safe HTTP endpoints;
- opens authenticated WebSocket connections;
- `single` creates one full 4-player lobby and exercises invite/reject/accept/leave/kick/config/queue/cancel;
- `load` creates solo lobbies for the user pool, starts matchmaking from solo players, plays queued games, reuses users across games, sends chat, plays legal non-drop moves, resigns, then checks game HTTP endpoints.

Target URL is built from `.env` as:

```text
https://{SUBDOMAIN}.{DOMAIN}/api
```

Run one full scenario:

```bash
uv run python -m load_tests.bughouse_e2e single
```

Run a load profile:

```bash
uv run python -m load_tests.bughouse_e2e load --games 100 --users 80 --concurrency 20 --moves 8
```

If the proxy rejects WebSocket handshakes under bursty setup load, reduce or
increase the connection ramp independently from game concurrency:

```bash
uv run python -m load_tests.bughouse_e2e load --games 100 --users 80 --concurrency 20 --connect-concurrency 4 --connect-retries 5
```

Useful environment overrides:

```text
LOADTEST_GAMES=100
LOADTEST_USERS=80
LOADTEST_CONCURRENCY=20
LOADTEST_MOVES=8
LOADTEST_CLOCK_TIME_MS=60000
LOADTEST_INCR_MS=1000
LOADTEST_TIMEOUT_S=15
LOADTEST_MATCH_TIMEOUT_S=30
LOADTEST_INSECURE_TLS=false
LOADTEST_CONNECT_CONCURRENCY=4
LOADTEST_CONNECT_RETRIES=3
```

`--touch-debug-endpoints` also calls the debug-only active-player endpoint. It is off by default because it mutates Redis state outside the normal user flow.
