"""
StudyBuddy Configuration Module
Centralized configuration with environment variable support and runtime persistence
"""
from typing import Optional, Dict, Any
import os
import json
from pathlib import Path

try:
    from pydantic_settings import BaseSettings
except ImportError:
    from pydantic import BaseModel as BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Application
    APP_ENV: str = os.environ.get("APP_ENV", "development")
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
    DEBUG: bool = os.environ.get("DEBUG", "false").lower() == "true"
    
    # AWS
    AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")
    AWS_ACCESS_KEY_ID: Optional[str] = os.environ.get("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY: Optional[str] = os.environ.get("AWS_SECRET_ACCESS_KEY")
    
    # DynamoDB & Local Fallback
    DYNAMODB_ENDPOINT_URL: Optional[str] = os.environ.get("DYNAMODB_ENDPOINT_URL", "http://localhost:8000")
    DYNAMODB_TABLE_PREFIX: str = os.environ.get("DYNAMODB_TABLE_PREFIX", "StudyBuddy")
    LOCAL_DB_PATH: str = os.environ.get("LOCAL_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "studybuddy_local.db"))
    
    # A2A Wellness Worker
    WELLNESS_AGENT_URL: str = os.environ.get("WELLNESS_AGENT_URL", "http://localhost:8001")
    
    # Bedrock
    BEDROCK_MODEL_ID: str = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
    BEDROCK_REGION: str = os.environ.get("BEDROCK_REGION", "us-east-1")
    
    # Redis
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    
    # Study Limits
    DAILY_STUDY_CAP_MINUTES: int = int(os.environ.get("DAILY_STUDY_CAP_MINUTES", "240"))
    SLEEP_CUTOFF_HOUR: int = int(os.environ.get("SLEEP_CUTOFF_HOUR", "22"))
    ALLOW_LATE_NIGHT_OVERRIDE: bool = os.environ.get("ALLOW_LATE_NIGHT_OVERRIDE", "true").lower() == "true"
    
    # Voice
    ENABLE_VOICE: bool = os.environ.get("ENABLE_VOICE", "true").lower() == "true"
    TTS_ENGINE: str = os.environ.get("TTS_ENGINE", "auto")  # Options: auto, gtts, pyttsx3, offline_wav
    
    # Wellness Provider
    WELLNESS_PROVIDER: str = os.environ.get("WELLNESS_PROVIDER", "simulated")  # Options: fitbit, apple_health, simulated
    FITBIT_CLIENT_ID: Optional[str] = os.environ.get("FITBIT_CLIENT_ID")
    FITBIT_CLIENT_SECRET: Optional[str] = os.environ.get("FITBIT_CLIENT_SECRET")
    
    # Security
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "studybuddy-dev-secret-key")
    JWT_ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    
    # Proactive Agent
    ENABLE_PROACTIVE: bool = os.environ.get("ENABLE_PROACTIVE", "true").lower() == "true"
    CHECKIN_REMINDER_HOUR: int = int(os.environ.get("CHECKIN_REMINDER_HOUR", "19"))
    SLEEP_REMINDER_HOUR: int = int(os.environ.get("SLEEP_REMINDER_HOUR", "21"))
    
    class Config:
        env_file = ".env"
        case_sensitive = True

    def is_production(self) -> bool:
        """Check if running in production environment"""
        return self.APP_ENV.lower() == "production"

    def is_docker(self) -> bool:
        """Check if running inside Docker container"""
        return os.path.exists("/.dockerenv") or os.environ.get("DOCKER_CONTAINER", "false").lower() == "true"

    def update_runtime(self, **kwargs) -> Dict[str, Any]:
        """Update settings at runtime and persist to local runtime config"""
        for k, v in kwargs.items():
            if hasattr(self, k) and v is not None:
                setattr(self, k, v)
        try:
            cfg_path = Path(self.LOCAL_DB_PATH).parent / "runtime_settings.json"
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if cfg_path.exists():
                data = json.loads(cfg_path.read_text())
            data.update({k: v for k, v in kwargs.items() if v is not None})
            cfg_path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass
        return self.to_dict()

    def load_runtime(self):
        """Load persisted runtime overrides if present"""
        try:
            cfg_path = Path(self.LOCAL_DB_PATH).parent / "runtime_settings.json"
            if cfg_path.exists():
                data = json.loads(cfg_path.read_text())
                for k, v in data.items():
                    if hasattr(self, k):
                        setattr(self, k, v)
        except Exception:
            pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "APP_ENV": self.APP_ENV,
            "DAILY_STUDY_CAP_MINUTES": self.DAILY_STUDY_CAP_MINUTES,
            "SLEEP_CUTOFF_HOUR": self.SLEEP_CUTOFF_HOUR,
            "ENABLE_VOICE": self.ENABLE_VOICE,
            "TTS_ENGINE": self.TTS_ENGINE,
            "WELLNESS_PROVIDER": self.WELLNESS_PROVIDER,
            "ENABLE_PROACTIVE": self.ENABLE_PROACTIVE,
            "CHECKIN_REMINDER_HOUR": self.CHECKIN_REMINDER_HOUR,
            "SLEEP_REMINDER_HOUR": self.SLEEP_REMINDER_HOUR,
        }


# Global settings instance
settings = Settings()
settings.load_runtime()


def get_settings() -> Settings:
    """Get application settings"""
    return settings


def is_production() -> bool:
    """Check if running in production environment"""
    return settings.is_production()


def is_docker() -> bool:
    """Check if running inside Docker container"""
    return settings.is_docker()


def get_logger(name: str = __name__):
    """Get structlog logger with standard logging fallback if structlog is not installed"""
    try:
        import structlog
        return structlog.get_logger(name)
    except ImportError:
        import logging
        base_logger = logging.getLogger(name)
        if not base_logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
            base_logger.addHandler(handler)
            base_logger.setLevel(logging.INFO)

        class StructuredLoggerAdapter:
            def __init__(self, lg):
                self._lg = lg
            def info(self, event, **kw):
                self._lg.info(f"{event} {kw}" if kw else str(event))
            def debug(self, event, **kw):
                self._lg.debug(f"{event} {kw}" if kw else str(event))
            def warning(self, event, **kw):
                self._lg.warning(f"{event} {kw}" if kw else str(event))
            def error(self, event, **kw):
                self._lg.error(f"{event} {kw}" if kw else str(event))
        return StructuredLoggerAdapter(base_logger)
