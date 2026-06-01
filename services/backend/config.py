
from shared.infrastructure import BootLevel, env_config, setup_logger

logger = setup_logger(__name__)

SECRET = env_config.backend.secret
SECURE_COOKIES = True if env_config.boot_level.value == BootLevel.RELEASE.value else False


class Config:
    access_token_lifetime = 60 * 100
    refresh_token_lifetime = 3600 * 24 * 30
    algorithm = "HS256"
    oauth_state_lifetime = 60 * 10
    oauth_registration_token_lifetime = 60 * 15
