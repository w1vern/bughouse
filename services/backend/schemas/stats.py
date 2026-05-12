from datetime import date, datetime

from pydantic import BaseModel


class StatsSchema(BaseModel):
    online_users: int
    available_players: int
    queued_players: int
    queued_lobbies: int
    active_games: int


class RatingExtremumSchema(BaseModel):
    rating: float
    dates: list[datetime]


class RatingExtremesSchema(BaseModel):
    minimum: RatingExtremumSchema
    maximum: RatingExtremumSchema


class DailyRatingSchema(BaseModel):
    date: date
    rating: float
