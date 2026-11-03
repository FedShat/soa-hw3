from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    grpc_api_key: SecretStr = Field(min_length=16)
    grpc_target: str = "flight:50051"
    grpc_port: int = 50051
    grpc_timeout: float = Field(default=2.0, gt=0)
    grpc_max_attempts: int = Field(default=3, ge=1, le=3)
    grpc_retry_backoff: float = Field(default=0.1, gt=0)
    circuit_failure_threshold: int = Field(default=5, ge=1)
    circuit_reset_timeout: float = Field(default=15.0, gt=0)
    circuit_window: float = Field(default=30.0, gt=0)
    redis_sentinels: str = "sentinel-1:26379,sentinel-2:26379,sentinel-3:26379"
    redis_master_name: str = "flight-cache"
    cache_ttl: int = Field(default=300, ge=300, le=600)
    recovery_interval: float = Field(default=2.0, gt=0)
    seed_demo: bool = True
    log_level: str = "INFO"
