"""
Configuration centrale de l'API.

Toutes les valeurs sensibles viennent des variables d'environnement (.env),
jamais codées en dur. En local, copie `.env.example` vers `.env`.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "CongoBet AI API"
    ENV: str = "development"

    # JWT interne à l'API (distinct du token Firebase, voir services/auth_service.py)
    JWT_SECRET: str = "CHANGE_ME_IN_PROD"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24h

    # CORS — restreindre en prod au(x) domaine(s) réel(s) du frontend
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "https://congobet.ai",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
