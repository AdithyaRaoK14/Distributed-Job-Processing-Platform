from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/jobqueue"
    redis_url: str = "redis://localhost:6379"
    heartbeat_timeout: int = 30       # seconds before worker is marked dead
    orchestrator_interval: int = 5    # seconds between orchestrator sweeps

    class Config:
        env_file = ".env"


settings = Settings()
