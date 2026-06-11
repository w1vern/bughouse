
from uuid import UUID

# Up to three bot seats can appear in a single game (the lobby leader is always
# human). These reserved User rows exist only as foreign-key targets so games
# involving bots can be persisted; they are never shown as available players and
# never seated. The k-th bot seat in a game is persisted under BOT_USER_IDS[k].

BOT_USER_COUNT = 3

BOT_USER_IDS: list[UUID] = [
    UUID("00000000-0000-0000-0000-0000000000b1"),
    UUID("00000000-0000-0000-0000-0000000000b2"),
    UUID("00000000-0000-0000-0000-0000000000b3"),
]

BOT_USER_USERNAMES: list[str] = ["__bot_1__", "__bot_2__", "__bot_3__"]

BOT_USER_EMAILS: list[str] = [
    "__bot_1__@bots.local",
    "__bot_2__@bots.local",
    "__bot_3__@bots.local",
]
