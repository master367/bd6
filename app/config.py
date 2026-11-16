import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    mongo_uri: str
    database: str
    jwt_secret: str
    recommendation_cache_seconds: float = 60.0

    def __post_init__(self):
        if not 0 <= self.recommendation_cache_seconds <= 3600:
            raise ValueError("RECOMMENDATION_CACHE_SECONDS must be between 0 and 3600")

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env")
        return cls(
            mongo_uri=os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/"),
            database=os.getenv("MONGODB_DB", "edge_catalog"),
            jwt_secret=os.getenv("JWT_SECRET", ""),
            recommendation_cache_seconds=float(os.getenv("RECOMMENDATION_CACHE_SECONDS", "60")),
        )

    def check_secret(self):
        if len(self.jwt_secret) < 32 or self.jwt_secret.startswith("replace-"):
            raise RuntimeError(
                "Set JWT_SECRET to a random secret of at least 32 characters in .env"
            )
