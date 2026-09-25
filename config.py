from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "openrouter/free")
    database_path: str = os.getenv("DATABASE_PATH", "aksakal.db")
    default_roast_level: int = int(os.getenv("DEFAULT_ROAST_LEVEL", "3"))
    min_bot_interval_minutes: int = int(os.getenv("MIN_BOT_INTERVAL_MINUTES", "10"))
    default_response_delay_seconds: int = int(os.getenv("DEFAULT_RESPONSE_DELAY_SECONDS", "20"))
    silence_trigger_minutes: int = int(os.getenv("SILENCE_TRIGGER_MINUTES", "180"))
    context_message_limit: int = int(os.getenv("CONTEXT_MESSAGE_LIMIT", "40"))
    ai_enabled: bool = _bool("AI_ENABLED", True)
    auto_reply_every_message: bool = _bool("AUTO_REPLY_EVERY_MESSAGE", False)


config = Config()
