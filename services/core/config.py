from __future__ import annotations

from shared.infrastructure import BootLevel, env_config


class Config:
    abort_timeout: float = 30000.0 + (env_config.boot_level == BootLevel.DEBUG) * 1e9
    invite_ttl = 60_000.0
    queue_tick = 2_000.0
    # Delay before a bot plays its move, in milliseconds (uniform random).
    bot_move_delay_min = 400.0
    bot_move_delay_max = 1200.0
