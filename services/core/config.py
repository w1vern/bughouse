from __future__ import annotations

from shared.infrastructure import env_config, BootLevel


class Config:
    abort_timeout: float = 30000.0 + (env_config.boot_level == BootLevel.DEBUG) * 1e9
    invite_ttl = 60_000.0
