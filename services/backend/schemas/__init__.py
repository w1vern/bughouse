
from .game import GameSchema, GameUserSchema, MoveSchema
from .oauth import (
    OAuthCompleteSchema,
    OAuthLinkSchema,
    OAuthProviderSchema,
    OAuthRegistrationSchema
)
from .stats import (
    DailyRatingSchema,
    RatingExtremesSchema,
    RatingExtremumSchema,
    StatsSchema
)
from .user import (
    CreateUserSchema,
    EditUserSchema,
    LoginUserSchema,
    UserSchema,
    UserTokenSchema
)
