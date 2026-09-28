from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

# Стабильно загружаем .env независимо от того, из какой рабочей папки запущен bot.py.
_SCRIPT_ENV = Path(__file__).resolve().with_name(".env")
_CWD_ENV = Path.cwd() / ".env"

def _load_env_file(path: Path):
    if not path.exists():
        return
    # Сначала обычная загрузка: непустые переменные процесса/панели имеют приоритет.
    load_dotenv(path, override=False)
    # Но пустая переменная окружения не должна блокировать реальное значение из .env.
    for key, value in dotenv_values(path).items():
        if value is not None and not (os.getenv(key) or "").strip():
            os.environ[key] = value

_load_env_file(_SCRIPT_ENV)
if _CWD_ENV != _SCRIPT_ENV:
    _load_env_file(_CWD_ENV)


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    env_file_path: str = str(_SCRIPT_ENV)
    env_file_exists: bool = _SCRIPT_ENV.exists() or _CWD_ENV.exists()
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_models: str = os.getenv(
        "GROQ_MODELS",
        "openai/gpt-oss-120b,qwen/qwen3.8-27b,openai/gpt-oss-20b",
    )
    mistral_api_key: str = os.getenv("MISTRAL_API_KEY", "")
    mistral_model: str = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
    database_path: str = os.getenv("DATABASE_PATH", "aksakal.db")
    default_roast_level: int = int(os.getenv("DEFAULT_ROAST_LEVEL", "3"))
    min_bot_interval_minutes: int = int(os.getenv("MIN_BOT_INTERVAL_MINUTES", "10"))
    default_response_delay_seconds: int = int(os.getenv("DEFAULT_RESPONSE_DELAY_SECONDS", "20"))
    silence_trigger_minutes: int = int(os.getenv("SILENCE_TRIGGER_MINUTES", "180"))
    context_message_limit: int = int(os.getenv("CONTEXT_MESSAGE_LIMIT", "40"))
    ai_enabled: bool = _bool("AI_ENABLED", True)
    auto_reply_every_message: bool = _bool("AUTO_REPLY_EVERY_MESSAGE", False)


config = Config()
