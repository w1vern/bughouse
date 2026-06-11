from __future__ import annotations

from shared.infrastructure import BotConfig


class BotRegistry:
    """The set of logical bots, defined statically in env config.

    Runtime state (availability, engine on/off) lives in Redis, not here.
    """

    def __init__(self, bots: list[BotConfig]) -> None:
        self._by_name: dict[str, BotConfig] = {b.name: b for b in bots}

    def is_bot(self, name: str) -> bool:
        return name in self._by_name

    def get(self, name: str) -> BotConfig | None:
        return self._by_name.get(name)

    def names(self) -> list[str]:
        return list(self._by_name)
