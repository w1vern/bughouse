from pydantic import BaseModel


class StatsSchema(BaseModel):
    online_users: int
    available_players: int
    queued_players: int
    queued_lobbies: int
    active_games: int
