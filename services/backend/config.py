
from shared.infrastructure import BootLevel, env_config, setup_logger

logger = setup_logger(__name__)

SECRET = env_config.backend.secret
SECURE_COOKIES = True if env_config.boot_level.value == BootLevel.RELEASE.value else False


class Config:
    access_token_lifetime = 60 * 10
    refresh_token_lifetime = 3600 * 24 * 30
    login_gap = 20
    ip_buffer = 100000  # 10
    ip_buffer_lifetime = 60*60*24
    algorithm = "HS256"
