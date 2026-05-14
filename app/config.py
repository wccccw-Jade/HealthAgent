from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    database_url: str = "sqlite:///./health_agent.db"
    langgraph_checkpoint_db: str = "./langgraph_checkpoints.sqlite"
    openai_api_key: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_webhook_secret: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
